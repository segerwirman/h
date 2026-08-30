"""Read-only semantic observation for one explicitly selected Chrome tab."""
from __future__ import annotations

from dataclasses import asdict

from pydantic import BaseModel

from jarvis.agent.base import Tool, ToolResult
from jarvis.integrations.selected_tab_browser import get_host


class _NoParams(BaseModel):
    pass


class _SelectedTabCaptchaAuthority:
    """Narrow CAPTCHA seam; it owns refs, never desktop resources or input."""

    surface_kind = "browser_tab"

    def __init__(self, host) -> None:
        self._host = host

    def clear_session(self, session_id: str) -> int:
        return self._host.clear_semantic_session(session_id)


class SelectedTabObserve(Tool):
    name = "selected_tab_observe"
    description = (
        "Observasi semantik read-only atas tepat satu tab Chrome yang sudah dipilih "
        "secara lokal. Menghasilkan ID observasi/elemen opaque dan deskriptor bounded; "
        "tidak menampilkan tab lain, selector, koordinat, screenshot, atau storage."
    )
    params_schema = _NoParams
    read_only = True
    wants_context = True
    timeout_s = 20

    def __init__(self, *, host=None) -> None:
        self._host = host
        self._snapshot_provider = None

    async def run(self, _session=None, _context=None, **_) -> ToolResult:
        from jarvis.agent.policy import selected_tab_context_error

        context_error = selected_tab_context_error(
            _context,
            capability="selected_tab.observe",
            risk="low",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        session_id = str(getattr(_session, "id", "") or "").strip()
        task_id = str(getattr(_session, "registry_task_id", "") or "").strip()
        if not session_id or not task_id:
            return ToolResult.fail("selected_tab_runtime_task_binding_required")
        try:
            snapshot = self._snapshot()
            target_id = str(getattr(snapshot, "surface_id", "") or "").strip()
            target_generation = getattr(snapshot, "surface_generation", 0)
            if not target_id or type(target_generation) is not int or target_generation <= 0:
                return ToolResult.fail("selected_tab_target_binding_required")
            host = self._host or get_host()
            result = host.observe_selected(
                session_id=session_id,
                task_id=task_id,
                target_id=target_id,
                target_generation=target_generation,
            )
            if not result.ok:
                host.clear_semantic_session(session_id)
                if result.state == "captcha_handoff":
                    from jarvis.agent.captcha_handoff import OWNER

                    OWNER.stage(
                        session_id=session_id,
                        task_id=task_id,
                        authority=_SelectedTabCaptchaAuthority(host),
                    )
                    return ToolResult.fail("selected_tab_handoff_required")
                return ToolResult.fail(str(result.reason or "selected_tab_observe_failed"))
            content = {
                "observation_id": result.observation_id,
                "origin": result.origin,
                "target_generation": result.target_generation,
                "document_generation": result.document_generation,
                "observation_generation": result.observation_generation,
                "expires_at": result.expires_at,
                "elements": [asdict(element) for element in result.elements],
            }
            return ToolResult.success(
                content,
                display=f"{len(result.elements)} elemen tab aman tersedia",
                observation_id=result.observation_id,
                safe_element_count=len(result.elements),
                target_generation=result.target_generation,
                document_generation=result.document_generation,
                observation_generation=result.observation_generation,
            )
        except Exception as exc:
            return ToolResult.fail(f"selected_tab_observe_failed:{type(exc).__name__}")

    def _snapshot(self):
        provider = self._snapshot_provider
        if callable(provider):
            return provider()
        from jarvis.ui.screen_control import COORDINATOR

        return COORDINATOR.snapshot()


__all__ = ["SelectedTabObserve"]
