"""Desktop-local semantic observe/click authority; inactive until registry exposure."""
from __future__ import annotations

import asyncio
import math

from dataclasses import dataclass
from functools import wraps
from threading import RLock

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult

from jarvis.automation.cua_safe_click import CaptureAdapter, SafeClickPlan
from jarvis.automation.cua_safety import CuaSafetyGate
from jarvis.automation.desktop_service import DESKTOP
from jarvis.automation.cua_driver import DRIVER
from jarvis.automation.uia_capture import UIACaptureBackend


def _lifecycle_serialized(method):
    """Keep revocation and one semantic action in one local critical section."""
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lifecycle_lock:
            return method(self, *args, **kwargs)
    return wrapped


@dataclass
class SafeDesktopSession:
    """In-memory authority for a short-lived trusted UIA observation chain."""

    gate: CuaSafetyGate

    capture: CaptureAdapter

    click_rect: object

    desktop: object = DESKTOP

    set_value_native: object | None = None

    click_native: object | None = None

    toggle_native: object | None = None

    select_option_native: object | None = None

    def __post_init__(self) -> None:
        self._owners: dict[str, str] = {}
        self._lifecycle_lock = RLock()

    def _disown(self, observation_id: str) -> None:
        """Retire an observation from the gate and drop its ownership entry."""
        self.gate.invalidate(observation_id)
        self._owners.pop(str(observation_id), None)

    @_lifecycle_serialized
    def observe_for(self, session_id: str):
        observation = self.capture.capture()
        self._owners[observation.id] = str(session_id or "")
        return observation

    def observe(self):
        """Compatibility seam; production observations must use ``observe_for``."""
        return self.observe_for("desktop-safe-click")

    @_lifecycle_serialized
    def clear_session(self, session_id: str) -> int:
        """Revoke every pending ref when a local task/session terminates."""
        owner = str(session_id or "")
        revoked = [obs_id for obs_id, issued_to in self._owners.items()
                   if issued_to == owner]
        for observation_id in revoked:
            self._disown(observation_id)
            self._owners.pop(observation_id, None)
        return len(revoked)

    @_lifecycle_serialized
    def clear_all(self) -> int:
        """UI teardown boundary: revoke every in-memory desktop observation."""
        owners = tuple(set(self._owners.values()))
        return sum(self.clear_session(owner) for owner in owners)

    @_lifecycle_serialized
    def set_value(self, observation_id: str, element_id: str, value: float,
                  *, session_id: str):
        """Set exactly one bounded slider value, then require UIA proof.

        No coordinates or keyboard fallback: the injected native setter accepts
        only the gate-issued semantic ref and uses UIA RangeValue directly.
        """
        owner = str(session_id or "")
        if self._owners.get(str(observation_id)) != owner:
            return None, "observasi tidak diterbitkan untuk sesi desktop ini"
        try:
            ref = self.gate.reference(observation_id, element_id)
            decision = self.gate.evaluate(ref, action="set_value")
            before = self.gate._observations[ref.observation_id]
            element = before.tree._by_id.get(ref.element_id)
            requested = float(value)
        except Exception as exc:
            return None, f"observasi atau nilai tidak aman: {exc}"
        if element is None or element.role != "slider" or not decision.allowed:
            return None, "target bukan slider semantik yang aman"
        try:
            current = float(element.states["value"])
            minimum = float(element.states["minimum"])
            maximum = float(element.states["maximum"])
        except Exception:
            return None, "slider tidak memiliki rentang UIA yang lengkap"
        if (not all(math.isfinite(item) for item in (current, minimum, maximum, requested))
                or minimum > maximum or not minimum <= current <= maximum):
            return None, "slider memiliki nilai atau rentang UIA non-finite/tidak valid"
        if not minimum <= requested <= maximum:
            return None, "nilai di luar rentang slider yang diizinkan"
        if not ref.native_identity:
            return None, "slider tidak memiliki identitas UIA stabil"
        if self.set_value_native is None:
            return None, "executor set_value UIA belum tersedia"
        if not self.desktop.claim(owner):
            return None, "desktop sedang dikendalikan sesi lain"
        try:
            self.set_value_native(ref, requested)
            self._disown(ref.observation_id)
            try:
                after = self.capture.capture()
            except Exception as exc:
                return (type("SetValueOutcome", (), {
                    "ok": False, "executed": True, "verified": False,
                    "after": None,
                    "reason": f"set_value terkirim; recapture gagal: {type(exc).__name__}",
                })(), "")
            after_element = after.tree._by_id.get(ref.element_id)
            after_value = float(after_element.states.get("value")) if after_element else float("nan")
            verified = bool(
                self.gate.verify_recapture(before, after)
                and after_element is not None
                and after_element.states.get("_uia_runtime_id") == ref.native_identity
                and math.isfinite(after_value)
                and after_value == requested
                and current != requested
            )
            return (type("SetValueOutcome", (), {
                "ok": verified, "executed": True, "verified": verified,
                "after": after,
                "reason": ("set_value semantik terverifikasi" if verified else
                           "set_value terkirim tetapi marker UIA tidak cocok dengan nilai target"),
            })(), "")
        except Exception as exc:
            self._disown(observation_id)
            return None, f"set_value gagal: {type(exc).__name__}"
        finally:
            self.desktop.release(owner)

    @_lifecycle_serialized
    def toggle(self, observation_id: str, element_id: str, *, session_id: str):
        """Toggle exactly one safe checkbox through UIA TogglePattern once."""
        owner = str(session_id or "")
        if self._owners.get(str(observation_id)) != owner:
            return None, "observasi tidak diterbitkan untuk sesi desktop ini"
        try:
            ref = self.gate.reference(observation_id, element_id)
            decision = self.gate.evaluate(ref, action="toggle")
            before = self.gate._observations[ref.observation_id]
            element = before.tree._by_id.get(ref.element_id)
            before_checked = bool(element.states.get("checked")) if element else None
        except Exception as exc:
            return None, f"observasi atau checkbox tidak aman: {exc}"
        if (element is None or element.role != "checkbox" or not decision.allowed
                or bool(element.states.get("disabled"))
                or not isinstance(element.states.get("checked"), bool)):
            return None, "target bukan checkbox semantik biner yang aman"
        if decision.requires_confirmation:
            return None, "checkbox membutuhkan konfirmasi desktop-local; tidak diterbitkan"
        if not ref.native_identity:
            return None, "checkbox tidak memiliki identitas UIA stabil"
        if self.toggle_native is None:
            return None, "executor toggle UIA belum tersedia"
        if not self.desktop.claim(owner):
            return None, "desktop sedang dikendalikan sesi lain"
        try:
            self.toggle_native(ref)
            self._disown(ref.observation_id)
            try:
                after = self.capture.capture()
            except Exception as exc:
                return (type("ToggleOutcome", (), {
                    "ok": False, "executed": True, "verified": False, "after": None,
                    "reason": f"toggle terkirim; recapture gagal: {type(exc).__name__}",
                })(), "")
            after_element = after.tree._by_id.get(ref.element_id)
            verified = bool(
                self.gate.verify_recapture(before, after)
                and after_element is not None
                and after_element.states.get("_uia_runtime_id") == ref.native_identity
                and isinstance(after_element.states.get("checked"), bool)
                and after_element.states.get("checked") is not before_checked
            )
            return (type("ToggleOutcome", (), {
                "ok": verified, "executed": True, "verified": verified, "after": after,
                "reason": ("toggle semantik terverifikasi" if verified else
                           "toggle terkirim tetapi recapture tidak membuktikan perubahan checkbox"),
            })(), "")
        except Exception as exc:
            self._disown(observation_id)
            return (type("ToggleOutcome", (), {
                "ok": False, "executed": True, "verified": False, "after": None,
                "reason": f"toggle terkirim; executor gagal: {type(exc).__name__}",
            })(), "")
        finally:
            self.desktop.release(owner)

    @_lifecycle_serialized
    def click(self, observation_id: str, element_id: str, *, session_id: str):
        owner = str(session_id or "")
        if self._owners.get(str(observation_id)) != owner:
            return None, "observasi tidak diterbitkan untuk sesi desktop ini"
        try:
            ref = self.gate.reference(observation_id, element_id)
            decision = self.gate.evaluate(ref, action="click")
        except Exception as exc:  # stale/unknown refs never reach executor
            return None, f"observasi atau elemen tidak aman: {exc}"
        if not decision.allowed or not ref.native_identity:
            return None, "target click tidak memiliki identitas UIA stabil atau tidak aman"
        if decision.requires_confirmation:
            return None, "target click membutuhkan konfirmasi desktop-local; tidak diterbitkan untuk safe-click"
        owner = str(session_id or "desktop-safe-click")
        if not self.desktop.claim(owner):
            return None, "desktop sedang dikendalikan sesi lain"
        try:
            if self.click_native is not None:
                before = self.gate._observations.get(ref.observation_id)
                try:
                    self.click_native(ref)
                except Exception as exc:
                    self._disown(ref.observation_id)
                    return type("ClickOutcome", (), {
                        "ok": False, "executed": True, "verified": False,
                        "requires_confirmation": False, "after": None,
                        "reason": f"click terkirim; executor gagal: {type(exc).__name__}",
                    })(), ""
                self._disown(ref.observation_id)
                try:
                    after = self.capture.capture()
                except Exception as exc:
                    return type("ClickOutcome", (), {
                        "ok": False, "executed": True, "verified": False,
                        "requires_confirmation": False, "after": None,
                        "reason": f"click terkirim; recapture gagal: {type(exc).__name__}",
                    })(), ""
                after_element = after.tree._by_id.get(ref.element_id)
                verified = bool(
                    before is not None and self.gate.verify_recapture(before, after)
                    and after_element is not None
                    and after_element.states.get("_uia_runtime_id") == ref.native_identity
                )
                outcome = type("ClickOutcome", (), {
                    "ok": verified, "executed": True, "verified": verified,
                    "requires_confirmation": False, "after": after,
                    "reason": ("click semantik terverifikasi" if verified else
                               "click terkirim tetapi identitas UIA recapture berubah"),
                })()
            else:
                outcome = SafeClickPlan(self.gate, self.capture, self.click_rect).execute(ref)
                self._owners.pop(str(ref.observation_id), None)
                after_element = outcome.after.tree._by_id.get(ref.element_id) if outcome.after else None
                if (outcome.executed and (after_element is None or
                        after_element.states.get("_uia_runtime_id") != ref.native_identity)):
                    outcome = type("ClickOutcome", (), {
                        "ok": False, "executed": True, "verified": False,
                        "requires_confirmation": False, "after": outcome.after,
                        "reason": "click terkirim tetapi identitas UIA recapture berubah",
                    })()
            return outcome, ""
        finally:
            self.desktop.release(owner)


    @_lifecycle_serialized
    def select_option(self, observation_id: str, element_id: str, *, session_id: str):
        """Select exactly one already-visible UIA option, then require recapture."""
        owner = str(session_id or "")
        if self._owners.get(str(observation_id)) != owner:
            return None, "observasi tidak diterbitkan untuk sesi desktop ini"
        try:
            ref = self.gate.reference(observation_id, element_id)
            decision = self.gate.evaluate(ref, action="select_option")
            before = self.gate._observations[ref.observation_id]
            element = before.tree._by_id.get(ref.element_id)
        except Exception as exc:
            return None, f"observasi atau option tidak aman: {exc}"
        if element is None or element.role != "dropdown_option" or not decision.allowed:
            return None, "target bukan option dropdown semantik yang aman"
        if decision.requires_confirmation:
            return None, "option dropdown membutuhkan konfirmasi desktop-local; tidak diterbitkan"
        if not ref.native_identity or not ref.parent_native_identity:
            return None, "option dropdown tidak memiliki identitas UIA stabil"
        if self.select_option_native is None:
            return None, "executor select_option UIA belum tersedia"
        if not self.desktop.claim(owner):
            return None, "desktop sedang dikendalikan sesi lain"
        try:
            parent_value_changed = self.select_option_native(ref)
            self._disown(ref.observation_id)
            try:
                after = self.capture.capture()
            except Exception as exc:
                return (type("SelectOutcome", (), {
                    "ok": False, "executed": True, "verified": False,
                    "after": None,
                    "reason": f"select_option terkirim; recapture gagal: {type(exc).__name__}",
                })(), "")
            after_element = after.tree._by_id.get(ref.element_id)
            verified = bool(
                parent_value_changed is True
                and self.gate.verify_recapture(before, after)
                and after_element is not None
                and after_element.states.get("_uia_runtime_id") == ref.native_identity
                and after_element.states.get("selected") is True
            )
            return (type("SelectOutcome", (), {
                "ok": verified, "executed": True, "verified": verified, "after": after,
                "reason": ("select_option semantik terverifikasi" if verified else
                           "select_option terkirim tetapi recapture tidak membuktikan pilihan"),
            })(), "")
        except Exception as exc:
            self._disown(observation_id)
            return (type("SelectOutcome", (), {
                "ok": False, "executed": True, "verified": False, "after": None,
                "reason": f"select_option terkirim; executor gagal: {type(exc).__name__}",
            })(), "")
        finally:
            self.desktop.release(owner)

class _Params(BaseModel):
    observation_id: str = Field(min_length=1, description="ID observasi UIA aktif")
    element_id: str = Field(min_length=1, description="ID elemen semantik dari observasi")


def _default_session() -> SafeDesktopSession:
    backend = UIACaptureBackend()
    gate = CuaSafetyGate()
    capture = CaptureAdapter(gate, backend.capture)
    return SafeDesktopSession(
        gate=gate, capture=capture, click_rect=DRIVER.click_rect, desktop=DESKTOP,
        set_value_native=backend.set_slider_value,
        click_native=backend.click_semantic, toggle_native=backend.toggle_checkbox_semantic,
        select_option_native=backend.select_option_semantic,
    )


_DEFAULT_SESSION: SafeDesktopSession | None = None
_DEFAULT_LOCK = RLock()


def desktop_safe_session() -> SafeDesktopSession:
    global _DEFAULT_SESSION
    with _DEFAULT_LOCK:
        if _DEFAULT_SESSION is None:
            _DEFAULT_SESSION = _default_session()
        return _DEFAULT_SESSION


class DesktopSafeClick(Tool):
    name = "desktop_safe_click"
    description = (
        "Klik sekali target UIA semantik yang sudah diobservasi. Hanya menerima "
        "observation_id dan element_id; koordinat, tombol alternatif, dan "
        "double-click tidak didukung. Selalu membutuhkan recapture verifikasi."
    )
    params_schema = _Params
    wants_context = True
    timeout_s = 30

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    async def run(self, observation_id: str, element_id: str, _session=None,
                  _context=None, **_) -> ToolResult:
        from jarvis.agent.policy import desktop_safe_context_error

        context_error = desktop_safe_context_error(
            _context, capability="desktop_safe.desktop_safe_click",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        session = self._session or desktop_safe_session()
        owner = str(getattr(_session, "id", "") or "desktop-safe-click")
        outcome, error = await asyncio.to_thread(
            session.click, str(observation_id), str(element_id), session_id=owner
        )
        if outcome is None:
            return ToolResult.fail(error)
        if not outcome.ok:
            return ToolResult.fail(
                outcome.reason,
                executed=outcome.executed,
                verified=outcome.verified,
                requires_confirmation=outcome.requires_confirmation,
            )
        return ToolResult.success(
            "Klik semantik selesai dan recapture terverifikasi.",
            display="klik desktop terverifikasi",
            executed=True,
            verified=True,
            after_observation_id=outcome.after.id if outcome.after else "",
        )


__all__ = ["DesktopSafeClick", "SafeDesktopSession", "desktop_safe_session"]
