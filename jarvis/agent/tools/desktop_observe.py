"""Read-only semantic observation for inactive desktop-local click/toggle chaining."""
from __future__ import annotations

import asyncio
import math

from pydantic import BaseModel

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, desktop_safe_session


class _NoParams(BaseModel):
    pass


class DesktopObserve(Tool):
    name = "desktop_observe"
    description = (
        "Observasi UIA read-only untuk sesi desktop lokal dan keluarkan ID "
        "elemen semantik aman yang terbatas. Tidak membaca gambar atau data teks "
        "UI; gunakan ID hasil ini hanya dengan action desktop_safe yang sesuai."
    )
    params_schema = _NoParams
    read_only = True
    wants_context = True
    timeout_s = 20

    def __init__(self, *, session: SafeDesktopSession | None = None):
        self._session = session

    async def run(self, _session=None, _context=None, **_) -> ToolResult:
        from jarvis.agent.policy import desktop_safe_context_error

        context_error = desktop_safe_context_error(
            _context, capability="desktop_safe.desktop_observe", risk="low",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        authority = self._session or desktop_safe_session()
        session_id = str(getattr(_session, "id", "") or "desktop-safe-click")
        try:
            observation = await asyncio.to_thread(authority.observe_for, session_id)
            elements = []
            for scope in observation.tree.scopes():
                for element in observation.tree.by_scope(scope):
                    descriptor = _safe_descriptor(authority, observation.id, element, scope.value)
                    if descriptor is not None:
                        elements.append(descriptor)
            elements.sort(key=lambda item: (item["scope"], item["role"], item["element_id"]))
            return ToolResult.success(
                {"observation_id": observation.id, "elements": elements[:50]},
                display=f"{min(len(elements), 50)} elemen desktop aman tersedia",
                observation_id=observation.id,
                safe_element_count=min(len(elements), 50),
            )
        except Exception as exc:  # no raw UI text escapes failure path
            return ToolResult.fail(f"observasi desktop gagal: {type(exc).__name__}")


def _safe_descriptor(authority: SafeDesktopSession, observation_id: str, element, scope: str) -> dict | None:
    """Expose only stable IDs supported by the recovered click/toggle authority."""
    try:
        ref = authority.gate.reference(observation_id, element.element_id)
    except Exception:
        return None
    if element.role == "checkbox":
        try:
            decision = authority.gate.evaluate(ref, action="toggle")
        except Exception:
            return None
        if (not decision.allowed or decision.requires_confirmation
                or not ref.native_identity or not isinstance(element.states.get("checked"), bool)):
            return None
        return {"element_id": element.element_id, "role": "checkbox", "scope": scope,
                "actions": ["toggle"]}
    if element.role in {"button", "link", "scrollbar"}:
        try:
            decision = authority.gate.evaluate(ref, action="click")
        except Exception:
            return None
        if not decision.allowed or decision.requires_confirmation:
            return None
        return {"element_id": element.element_id, "role": element.role, "scope": scope}
    if element.role != "slider":
        return None
    if not ref.label or not ref.native_identity:
        return None
    try:
        decision = authority.gate.evaluate(ref, action="set_value")
        minimum = float(element.states["minimum"])
        maximum = float(element.states["maximum"])
        value = float(element.states["value"])
    except Exception:
        return None
    if (not decision.allowed or decision.requires_confirmation
            or not all(math.isfinite(item) for item in (minimum, maximum, value))
            or minimum > maximum):
        return None
    if not minimum <= value <= maximum:
        return None
    return {
        "element_id": element.element_id,
        "role": "slider",
        "scope": scope,
        "actions": ["set_value"],
        "value_domain": {"minimum": minimum, "maximum": maximum},
    }


__all__ = ["DesktopObserve"]
