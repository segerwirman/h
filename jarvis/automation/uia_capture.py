"""Windows UIA capture backend for the deliberately narrow safe-click slice.

It reads the active UIA window into a semantic tree.  It does not capture
pixels, send data to a vision model, or perform actions itself.  The only
execution wrapper below consumes an already-issued semantic ref and delegates
one left click through ``SafeClickPlan`` while holding the desktop lease.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame, SafeClickPlan, SafeClickOutcome
from jarvis.automation.cua_safety import (
    ConfirmationClass,
    CuaSafetyGate,
    SemanticTargetRef,
)
from jarvis.automation.cua_driver import DRIVER
from jarvis.automation.desktop_service import DESKTOP
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement
from jarvis.core.privacy_denylist import is_denylisted


_ROLE_BY_UIA = {
    "button": "button",
    "hyperlink": "link",
    "edit": "text_field",
    "checkbox": "checkbox",
    "radiobutton": "radio",
    "combobox": "dropdown",
    "slider": "slider",
    "scrollbar": "scrollbar",
    "tabitem": "tab",
    "menuitem": "menu_item",
    "listitem": "card",
}


@dataclass(frozen=True)
class _WindowIdentity:
    surface_id: str
    title: str


class UIACaptureBackend:
    """Read the foreground pywinauto UIA tree into ``CaptureFrame``.

    ``desktop`` is injectable for tests. The real backend is constructed lazily
    so import/discovery remains harmless when UIA is unavailable.
    """

    def __init__(self, desktop=None, *, max_elements: int = 500, driver=None):
        self._desktop = desktop
        self._real_desktop = desktop is None
        self._max_elements = max(1, int(max_elements))
        self._driver = driver or DRIVER

    def capture(self) -> CaptureFrame:
        window = self._active_window()
        identity = self._identity(window)
        if is_denylisted(identity.title, identity.title):
            return CaptureFrame(identity.surface_id, ScreenElementTree(), "redacted")
        tree = ScreenElementTree()
        for index, control in enumerate(_descendants(window)[:self._max_elements], start=1):
            element = _element_from_control(control, index)
            if element is not None:
                tree.add(element)
        return CaptureFrame(identity.surface_id, tree, "normal")

    def click_semantic(self, ref: SemanticTargetRef) -> None:
        """Click only the matching current UIA target; ref identity is mandatory."""
        self._matching_control(ref, expected_role=None)
        x, y, width, height = ref.rect
        self._driver.click(x + width // 2, y + height // 2, button="left", double=False)

    def scroll_semantic(self, ref: SemanticTargetRef, delta: int) -> None:
        """Scroll only the matching current UIA scrollbar with fixed internal delta."""
        self._matching_control(ref, expected_role="scrollbar")
        x, y, width, height = ref.rect
        self._driver.scroll(x + width // 2, y + height // 2, int(delta))

    def _matching_control(self, ref: SemanticTargetRef, *, expected_role: str | None):
        window = self._active_window()
        if self._identity(window).surface_id != ref.surface_id:
            raise RuntimeError("surface desktop berubah sebelum action")
        if not ref.native_identity:
            raise RuntimeError("target tidak memiliki identitas UIA stabil")
        for index, control in enumerate(_descendants(window)[:self._max_elements], start=1):
            if f"uia-{index}" != ref.element_id:
                continue
            element = _element_from_control(control, index)
            if (element is None or element.rect != ref.rect
                    or (expected_role is not None and element.role != expected_role)):
                raise RuntimeError("target semantik tidak lagi cocok dengan observasi")
            if _uia_runtime_identity(control) != ref.native_identity:
                raise RuntimeError("identitas UIA target berubah sebelum action")
            return control
        raise RuntimeError("target semantik tidak ditemukan pada UIA aktif")

    def set_slider_value(self, ref: SemanticTargetRef, value: float) -> None:
        """Apply UIA RangeValue only to the still-matching semantic slider.

        ``ref`` is issued by the safety gate; callers never supply a control
        query or coordinate. A changed foreground surface or stale UIA index
        fails before invoking the native pattern.
        """
        window = self._active_window()
        if self._identity(window).surface_id != ref.surface_id:
            raise RuntimeError("surface desktop berubah sebelum set_value")
        for index, control in enumerate(_descendants(window)[:self._max_elements], start=1):
            if f"uia-{index}" != ref.element_id:
                continue
            element = _element_from_control(control, index)
            if element is None or element.role != "slider" or element.rect != ref.rect:
                raise RuntimeError("semantic slider tidak lagi cocok dengan observasi")
            if not ref.native_identity or _uia_runtime_identity(control) != ref.native_identity:
                raise RuntimeError("identitas UIA slider berubah sebelum set_value")
            try:
                pattern = control.iface_range_value
                requested = float(value)
                current = float(pattern.CurrentValue)
                minimum = _range_bound(pattern, "CurrentMinimum", "Minimum")
                maximum = _range_bound(pattern, "CurrentMaximum", "Maximum")
                if (not all(math.isfinite(item) for item in (current, minimum, maximum, requested))
                        or minimum > maximum or not minimum <= current <= maximum):
                    raise RuntimeError("range slider UIA non-finite atau tidak valid")
                if not minimum <= requested <= maximum:
                    raise RuntimeError("nilai di luar rentang slider UIA saat ini")
                pattern.SetValue(requested)
            except Exception as exc:
                if isinstance(exc, RuntimeError):
                    raise
                raise RuntimeError(f"UIA RangeValue gagal: {type(exc).__name__}") from exc
            return
        raise RuntimeError("semantic slider tidak ditemukan pada UIA aktif")







    def toggle_checkbox_semantic(self, ref: SemanticTargetRef) -> None:
        """Invoke UIA Toggle once on one current binary checkbox only."""
        control = self._matching_control(ref, expected_role="checkbox")
        try:
            state = int(control.iface_toggle.CurrentToggleState)
            if state not in {0, 1}:
                raise RuntimeError("checkbox UIA tidak memiliki state biner")
            control.iface_toggle.Toggle()
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"UIA Toggle gagal: {type(exc).__name__}") from exc

    def select_option_semantic(self, ref: SemanticTargetRef) -> bool:
        """Select once and report whether the parent ComboBox value changed."""
        control = self._matching_control(ref, expected_role="dropdown_option")
        try:
            parent = control.parent()
            if str(getattr(getattr(parent, "element_info", None), "control_type", "") or "").casefold() != "list":
                raise RuntimeError("option UIA tidak berada pada list dropdown aktif")
            dropdown = parent.parent()
            if str(getattr(getattr(dropdown, "element_info", None), "control_type", "") or "").casefold() != "combobox":
                raise RuntimeError("option UIA tidak terikat pada dropdown aktif")
            if (not ref.parent_native_identity
                    or _uia_runtime_identity(dropdown) != ref.parent_native_identity):
                raise RuntimeError("identitas UIA dropdown berubah sebelum select_option")
            try:
                before_value = str(dropdown.iface_value.CurrentValue)
            except Exception as exc:
                raise RuntimeError("dropdown tidak memiliki ValuePattern verifikasi") from exc
            control.iface_selection_item.Select()
            try:
                after_value = str(dropdown.iface_value.CurrentValue)
            except Exception as exc:
                raise RuntimeError("nilai dropdown tidak dapat diverifikasi setelah select") from exc
            return before_value != after_value
        except Exception as exc:
            if isinstance(exc, RuntimeError):
                raise
            raise RuntimeError(f"UIA SelectionItem gagal: {type(exc).__name__}") from exc

    def _active_window(self):
        if self._desktop is None:
            from pywinauto import Desktop
            self._desktop = Desktop(backend="uia")
            self._real_desktop = True
        if self._real_desktop:
            # ``Desktop`` is a selector facade, not an active-window API.
            # Resolve the genuine foreground HWND first, then create its UIA
            # wrapper; this also avoids ambiguous title matching.
            import win32gui
            handle = win32gui.GetForegroundWindow()
            if not handle:
                raise RuntimeError("tidak ada foreground window untuk capture UIA")
            return self._desktop.window(handle=handle).wrapper_object()
        get_active = getattr(self._desktop, "get_active", None)
        if callable(get_active):
            return get_active()
        raise RuntimeError("backend UIA test tidak menyediakan active window")

    @staticmethod
    def _identity(window) -> _WindowIdentity:
        handle = getattr(window, "handle", None)
        if handle in (None, ""):
            handle = id(window)
        title = _text(window)
        return _WindowIdentity(f"uia:{handle}", title)


class UIASafeClickService:
    """Lease-guarded bridge from semantic ref to exactly one driver click."""

    def __init__(self, gate: CuaSafetyGate, capture: CaptureAdapter,
                 *, driver=None, desktop=None, audit=None):
        self._gate = gate
        self._capture = capture
        self._driver = driver or DRIVER
        self._desktop = desktop or DESKTOP
        if audit is None:
            from jarvis.core import log
            audit = log.get("automation.uia_safe_click").info
        self._audit = audit

    def click(self, ref: SemanticTargetRef, *, session_id: str) -> SafeClickOutcome:
        self._emit("cua.safe_click.capture", capture_id=ref.observation_id,
                   surface_id=ref.surface_id, ref_id=ref.element_id)
        try:
            decision = self._gate.evaluate(ref, action="click")
            self._emit("cua.safe_click.decision", capture_id=ref.observation_id,
                       ref_id=ref.element_id, classification=decision.classification.value)
        except Exception as exc:
            self._emit("cua.safe_click.decision", capture_id=ref.observation_id,
                       ref_id=ref.element_id, classification="block",
                       error_type=type(exc).__name__)
            return SafeClickOutcome(False, False, False, False, str(exc))
        if decision.classification is not ConfirmationClass.ALLOW:
            return SafeClickOutcome(False, False, False,
                                    decision.requires_confirmation, decision.reason)

        owner = str(session_id or "safe-click")
        acquired = bool(self._desktop.claim(owner))
        self._emit("cua.safe_click.lease", capture_id=ref.observation_id,
                   acquired=acquired)
        if not acquired:
            return SafeClickOutcome(False, False, False, False,
                                    "desktop sedang dikendalikan sesi lain")
        try:
            def click_rect(rect: tuple[int, int, int, int]) -> None:
                x, y, width, height = rect
                self._emit("cua.safe_click.attempt", capture_id=ref.observation_id,
                           ref_id=ref.element_id, attempted=True)
                self._driver.click(
                    x + width // 2, y + height // 2,
                    button="left", double=False,
                )
            outcome = SafeClickPlan(self._gate, self._capture, click_rect).execute(ref)
            self._emit("cua.safe_click.recapture", capture_id=ref.observation_id,
                       after_capture_id=(outcome.after.id if outcome.after else ""),
                       verified=outcome.verified)
            return outcome
        finally:
            self._desktop.release(owner)

    def _emit(self, event: str, **fields) -> None:
        """Audit contains opaque IDs/statuses only — never UI labels or text."""
        self._audit(event, **fields)


def _descendants(window) -> list:
    try:
        return list(window.descendants())
    except Exception:
        return []


def _text(control) -> str:
    for attr in ("window_text",):
        method = getattr(control, attr, None)
        if callable(method):
            try:
                return " ".join(str(method() or "").split())[:160]
            except Exception:
                continue
    return ""


def _scope_for(control, left: int, top: int) -> ElementScope:
    """Conservative UIA scope classifier; unknown surfaces remain page main."""
    info = getattr(control, "element_info", None)
    if bool(getattr(info, "is_dialog", False)):
        return ElementScope.PAGE_DIALOG
    label = _text(control).casefold()
    if top < 48 and label in {"minimize", "maximize", "restore", "close"}:
        return ElementScope.WINDOW_CHROME
    kind = str(getattr(info, "control_type", "") or "").casefold()
    automation_id = str(getattr(info, "automation_id", "") or "").casefold()
    class_name = str(getattr(info, "class_name", "") or "").casefold()
    chrome = "chrome" in class_name
    if chrome and kind == "tabitem":
        return ElementScope.BROWSER_TAB_STRIP
    if chrome and kind == "edit" and "address" in automation_id:
        return ElementScope.BROWSER_ADDRESS
    if chrome and kind == "button" and automation_id in {
            "back", "forward", "reload", "home"}:
        return ElementScope.BROWSER_NAV
    if kind == "edit" and "composer" in automation_id:
        return ElementScope.PAGE_COMPOSER
    return ElementScope.PAGE_MAIN


def _element_from_control(control, index: int) -> UIElement | None:
    try:
        info = getattr(control, "element_info", None)
        raw_kind = str(getattr(info, "control_type", "") or "")
        kind = raw_kind.casefold()
        role = _ROLE_BY_UIA.get(kind, "unknown")
        label = _text(control)
        rect = control.rectangle()
        left, top, right, bottom = (int(rect.left), int(rect.top),
                                    int(rect.right), int(rect.bottom))
        width, height = right - left, bottom - top
        visible = bool(control.is_visible())
        enabled = bool(control.is_enabled())
    except Exception:
        return None
    if width <= 0 or height <= 0:
        return None
    states = {"disabled": not enabled}
    if role in {"button", "link", "scrollbar", "slider", "checkbox", "dropdown_option"}:
        runtime_id = _uia_runtime_identity(control)
        if not runtime_id:
            return None
        states["_uia_runtime_id"] = runtime_id
    if role == "checkbox":
        try:
            toggle_state = int(control.iface_toggle.CurrentToggleState)
            if toggle_state not in {0, 1}:
                return None
            states["checked"] = bool(toggle_state)
        except Exception:
            return None
    if role == "scrollbar":
        try:
            states["position"] = float(control.iface_range_value.CurrentValue)
        except Exception:
            return None
    if role == "slider":
        try:
            pattern = control.iface_range_value
            runtime_id = _uia_runtime_identity(control)
            if not runtime_id:
                return None
            states["value"] = float(pattern.CurrentValue)
            states["minimum"] = _range_bound(pattern, "CurrentMinimum", "Minimum")
            states["maximum"] = _range_bound(pattern, "CurrentMaximum", "Maximum")
            if (not all(math.isfinite(states[key]) for key in ("value", "minimum", "maximum"))
                    or states["minimum"] > states["maximum"]
                    or not states["minimum"] <= states["value"] <= states["maximum"]):
                return None
            states["_uia_runtime_id"] = runtime_id
        except Exception:
            return None
    if raw_kind.casefold() == "listitem":
        try:
            option_parent = control.parent()
            parent_kind = str(getattr(getattr(option_parent, "element_info", None), "control_type", "") or "").casefold()
            dropdown_parent = option_parent.parent()
            dropdown_kind = str(getattr(getattr(dropdown_parent, "element_info", None), "control_type", "") or "").casefold()
            dropdown_identity = _uia_runtime_identity(dropdown_parent)
            if parent_kind != "list" or dropdown_kind != "combobox" or not dropdown_identity:
                return None
            states["_uia_runtime_id"] = _uia_runtime_identity(control)
            states["_uia_parent_runtime_id"] = dropdown_identity
            if not states["_uia_runtime_id"]:
                return None
            states["selected"] = bool(control.iface_selection_item.CurrentIsSelected)
            role = "dropdown_option"
        except Exception:
            return None
    if role == "dropdown":
        try:
            selected = list(control.iface_selection.GetSelection())
            if len(selected) != 1:
                return None
            selected_id = str(getattr(selected[0].element_info, "automation_id", "") or "")
            if not selected_id:
                return None
            states["selected_id"] = selected_id
        except Exception:
            return None
    if role == "dropdown_option":
        try:
            states["selected"] = bool(control.iface_selection_item.CurrentIsSelected)
        except Exception:
            return None
    return UIElement(
        element_id=f"uia-{index}",
        scope=_scope_for(control, left, top),
        role=role,
        name=label,
        label=label,
        rect=(left, top, width, height),
        visible=visible,
        confidence=0.95 if role != "unknown" else 0.45,
        provenance="uia",
        states=states,
    )


def _range_bound(pattern, current_name: str, legacy_name: str) -> float:
    """Read real UIA ``Current*`` properties, retaining test-backend fallback."""
    value = getattr(pattern, current_name, None)
    if value is None:
        value = getattr(pattern, legacy_name)
    return float(value)


def _uia_runtime_identity(control) -> str:
    """Opaque per-control UIA identity; never returned to an agent or log."""
    info = getattr(control, "element_info", None)
    raw = getattr(info, "runtime_id", None)
    if raw in (None, ""):
        return ""
    if isinstance(raw, (tuple, list)):
        return ".".join(str(part) for part in raw)
    return str(raw)


__all__ = ["UIACaptureBackend", "UIASafeClickService"]
