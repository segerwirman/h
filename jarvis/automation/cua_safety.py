"""Pure, fail-closed safety contract for future native CUA/vision execution.

This module deliberately has no screenshot, vision, UI-Automation, pyautogui,
or network dependency.  It turns an already-observed semantic element tree into
a short-lived reference, classifies the requested action, and requires a fresh
recapture after an action.  An executor may only be wired after it consumes
this contract.
"""
from __future__ import annotations

import time
import unicodedata
import uuid
from collections import OrderedDict
from dataclasses import dataclass
from enum import Enum

from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


class CuaSafetyError(ValueError):
    """Base error for a rejected CUA action plan."""


class StaleObservationError(CuaSafetyError):
    """The reference is expired or superseded by a newer observation."""


class UnsafeTargetError(CuaSafetyError):
    """The target cannot safely receive a semantic action reference."""


class ConfirmationClass(str, Enum):
    ALLOW = "allow"
    CONFIRM = "confirm"
    BLOCK = "block"


@dataclass(frozen=True)
class CuaObservation:
    id: str
    surface_id: str
    captured_at: float
    privacy: str
    tree: ScreenElementTree


@dataclass(frozen=True)
class SemanticTargetRef:
    observation_id: str
    surface_id: str
    element_id: str
    role: str
    label: str
    rect: tuple[int, int, int, int]
    issued_at: float
    native_identity: str = ""
    parent_native_identity: str = ""


@dataclass(frozen=True)
class SafetyDecision:
    classification: ConfirmationClass
    reason: str

    @property
    def allowed(self) -> bool:
        return self.classification is not ConfirmationClass.BLOCK

    @property
    def requires_confirmation(self) -> bool:
        return self.classification is ConfirmationClass.CONFIRM


@dataclass(frozen=True)
class TextEntryAdmission:
    allowed: bool
    reason: str
    text: str = ""


_SENSITIVE_TERMS = (
    "password", "kata sandi", "passcode", "pin", "otp", "one time password",
    "verification code", "verification", "credential", "credentials",
    "sign in", "log in", "login", "credit card", "debit card", "card number",
    "cvv", "cvc", "payment", "checkout", "bank", "transfer", "permission",
    "allow app", "administrator", "elevation", "uac", "security code",
)
_DESTRUCTIVE_TERMS = (
    "delete", "remove", "erase", "format", "reset", "wipe", "discard",
    "uninstall", "overwrite", "send", "submit", "purchase", "pay",
    "transfer", "confirm order",
)
_SUPPORTED_ACTIONS = frozenset({
    "click", "right_click", "double_click", "text_entry", "type", "key",
    "scroll", "drag", "set_value", "select_option", "toggle",
    "set_content_title", "reorder_scene",
})
_TEXT_ENTRY_ROLES = frozenset({"text_field", "search_field", "textarea", "composer"})
_MAX_TEXT_ENTRY_CHARS = 500


def admit_text_entry(element: UIElement, text: str) -> TextEntryAdmission:
    """Admit bounded printable text only for a non-sensitive semantic field."""
    if not isinstance(element, UIElement) or element.role not in _TEXT_ENTRY_ROLES:
        return TextEntryAdmission(False, "target bukan text field semantik")
    if element.scope is ElementScope.BROWSER_ADDRESS:
        return TextEntryAdmission(False, "browser address tidak boleh diisi generik")
    if bool(element.states.get("disabled")):
        return TextEntryAdmission(False, "text field tidak dapat diedit")
    label = " ".join(
        f"{element.name or ''} {element.label or ''} {element.elem_type or ''}".casefold().split()
    )
    if any(term in label for term in _SENSITIVE_TERMS):
        return TextEntryAdmission(False, "field sensitif harus diisi manusia")
    if not isinstance(text, str):
        return TextEntryAdmission(False, "text harus berupa string")
    if not text or len(text) > _MAX_TEXT_ENTRY_CHARS:
        return TextEntryAdmission(False, "panjang text harus 1-500 karakter")
    if any(
        character not in {"\n", "\t"} and unicodedata.category(character).startswith("C")
        for character in text
    ):
        return TextEntryAdmission(False, "text mengandung karakter kontrol yang dilarang")
    return TextEntryAdmission(True, "text bounded dan field non-sensitif", text)


class CuaSafetyGate:
    """Issue and validate short-lived semantic references per observed surface.

    A newer observation for one surface invalidates every ref issued from the
    older snapshot.  The caller must observe again after an action and may only
    treat that newer same-surface observation as post-action verification.
    """

    def __init__(self, *, max_age_s: float = 10.0, min_confidence: float = 0.5,
                 max_retained_observations: int = 64):
        self._max_age_s = max(0.1, float(max_age_s))
        self._min_confidence = min(1.0, max(0.0, float(min_confidence)))
        self._max_retained = max(1, int(max_retained_observations))
        self._observations: "OrderedDict[str, CuaObservation]" = OrderedDict()
        self._latest_by_surface: dict[str, str] = {}

    def observe(self, *, surface_id: str, tree: ScreenElementTree,
                privacy: str = "normal", now: float | None = None) -> CuaObservation:
        """Record an existing semantic observation; never performs capture."""
        captured_at = time.time() if now is None else float(now)
        normalized_surface = str(surface_id or "").strip()
        if not normalized_surface:
            raise UnsafeTargetError("surface_id observasi wajib ada")
        observation = CuaObservation(
            id=uuid.uuid4().hex,
            surface_id=normalized_surface,
            captured_at=captured_at,
            privacy=str(privacy or "normal").casefold(),
            tree=tree,
        )
        self._observations[observation.id] = observation
        self._latest_by_surface[normalized_surface] = observation.id
        self._evict_stale_observations()
        return observation

    def _evict_stale_observations(self) -> None:
        """Bound the snapshot store; never drop a surface's current observation."""
        current_ids = set(self._latest_by_surface.values())
        while len(self._observations) > self._max_retained:
            for candidate_id in list(self._observations.keys()):
                if candidate_id not in current_ids:
                    self._observations.pop(candidate_id, None)
                    break
            else:
                break

    def reference(self, observation_id: str, element_id: str,
                  *, now: float | None = None) -> SemanticTargetRef:
        observation = self._current(observation_id, now=now)
        if observation.privacy != "normal":
            raise UnsafeTargetError("surface privasi/redacted tidak dapat diautomasi")
        element = observation.tree._by_id.get(str(element_id))
        if element is None:
            raise UnsafeTargetError("elemen tidak ada pada observasi ini")
        if (element.stale or not element.visible or element.role == "unknown"
                or element.confidence < self._min_confidence):
            raise UnsafeTargetError("elemen tidak cukup pasti untuk ref semantik")
        label = " ".join(str(element.name or element.label or "").split())[:160]
        return SemanticTargetRef(
            observation_id=observation.id,
            surface_id=observation.surface_id,
            element_id=element.element_id,
            role=element.role,
            label=label,
            rect=tuple(int(value) for value in element.rect),
            issued_at=time.time() if now is None else float(now),
            native_identity=str(element.states.get("_uia_runtime_id", "") or ""),
            parent_native_identity=str(element.states.get("_uia_parent_runtime_id", "") or ""),
        )

    def evaluate(self, ref: SemanticTargetRef, *, action: str,
                 now: float | None = None) -> SafetyDecision:
        """Fail closed for stale refs, unsupported actions, and sensitive UI."""
        observation = self._current(ref.observation_id, now=now)
        if observation.surface_id != ref.surface_id:
            raise UnsafeTargetError("surface ref tidak cocok dengan observasi")
        element = observation.tree._by_id.get(ref.element_id)
        if element is None or element.stale or not element.visible:
            raise StaleObservationError("target tidak lagi tersedia pada observasi")
        normalized_action = str(action or "").casefold().strip()
        if normalized_action not in _SUPPORTED_ACTIONS:
            return SafetyDecision(ConfirmationClass.BLOCK, "aksi CUA tidak didukung")
        label = " ".join((ref.label or "").casefold().split())
        if any(term in label for term in _SENSITIVE_TERMS):
            return SafetyDecision(
                ConfirmationClass.BLOCK,
                "target berada pada surface sensitif; pengguna harus mengambil alih",
            )
        if any(term in label for term in _DESTRUCTIVE_TERMS):
            return SafetyDecision(
                ConfirmationClass.CONFIRM,
                "target berpotensi irreversible atau berdampak eksternal",
            )
        return SafetyDecision(ConfirmationClass.ALLOW, "target semantik segar dan non-sensitif")

    def invalidate(self, observation_id: str) -> None:
        """Retire refs after any attempted action; a new capture is mandatory."""
        observation = self._observations.get(str(observation_id))
        if observation is not None and self._latest_by_surface.get(
                observation.surface_id) == observation.id:
            self._latest_by_surface.pop(observation.surface_id, None)
            self._observations.pop(observation.id, None)

    def verify_recapture(self, before: CuaObservation, after: CuaObservation) -> bool:
        """Only a newer same-surface observation is valid post-action evidence."""
        return (
            before.surface_id == after.surface_id
            and before.id != after.id
            and after.captured_at >= before.captured_at
            and after.privacy == "normal"
            and self._latest_by_surface.get(after.surface_id) == after.id
        )

    def _current(self, observation_id: str, *, now: float | None) -> CuaObservation:
        observation = self._observations.get(str(observation_id))
        if observation is None:
            raise StaleObservationError("observasi tidak dikenal atau sudah dibuang")
        if self._latest_by_surface.get(observation.surface_id) != observation.id:
            raise StaleObservationError("observasi sudah digantikan; capture ulang diperlukan")
        current = time.time() if now is None else float(now)
        if current - observation.captured_at > self._max_age_s:
            raise StaleObservationError("observasi kedaluwarsa; capture ulang diperlukan")
        return observation


__all__ = [
    "ConfirmationClass", "CuaObservation", "CuaSafetyError", "CuaSafetyGate",
    "SafetyDecision", "SemanticTargetRef", "StaleObservationError",
    "TextEntryAdmission", "UnsafeTargetError", "admit_text_entry",
]
