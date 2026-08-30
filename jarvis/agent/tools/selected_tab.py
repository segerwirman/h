"""Read-only semantic observation for one explicitly selected Chrome tab."""
from __future__ import annotations

from dataclasses import asdict
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.integrations.selected_tab_browser import get_host


class _NoParams(BaseModel):
    pass


class _TargetParams(BaseModel):
    model_config = ConfigDict(extra="forbid")

    observation_id: str = Field(min_length=1, description="ID observasi tab aktif")
    element_id: str = Field(min_length=1, description="ID elemen semantik opaque")


class _TypeParams(_TargetParams):
    text: str = Field(
        min_length=1,
        max_length=500,
        description="Text bounded 1-500 karakter tanpa implicit submit",
    )


class _ScrollParams(_TargetParams):
    direction: Literal["up", "down"] = Field(description="Arah bounded scroll")
    count: int = Field(ge=1, le=5, strict=True, description="Jumlah langkah 1-5")


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


def _snapshot(provider):
    if callable(provider):
        return provider()
    from jarvis.ui.screen_control import COORDINATOR

    return COORDINATOR.snapshot()


def _runtime_binding(_session, provider):
    session_id = str(getattr(_session, "id", "") or "").strip()
    task_id = str(getattr(_session, "registry_task_id", "") or "").strip()
    if not session_id or not task_id:
        return None, "selected_tab_runtime_task_binding_required"
    snapshot = _snapshot(provider)
    target_id = str(getattr(snapshot, "surface_id", "") or "").strip()
    target_generation = getattr(snapshot, "surface_generation", 0)
    if not target_id or type(target_generation) is not int or target_generation <= 0:
        return None, "selected_tab_target_binding_required"
    return (session_id, task_id, target_id, target_generation), ""


def _observation_content(result):
    if result is None:
        return None
    return {
        "observation_id": result.observation_id,
        "origin": result.origin,
        "target_generation": result.target_generation,
        "document_generation": result.document_generation,
        "observation_generation": result.observation_generation,
        "expires_at": result.expires_at,
        "elements": [asdict(element) for element in result.elements],
    }


def _action_tool_result(result, *, host, session_id: str, task_id: str) -> ToolResult:
    evidence = {
        "attempted": bool(result.attempted),
        "executed": bool(result.executed),
        "verified": bool(result.verified),
        "ambiguous": bool(result.ambiguous),
        "requires_confirmation": bool(result.requires_confirmation),
    }
    if result.ok and result.verified:
        return ToolResult.success(
            {
                "state": "verified",
                **evidence,
                "after_observation": _observation_content(result.after_observation),
            },
            display="aksi selected tab terverifikasi",
            **evidence,
        )
    if result.state == "captcha_handoff":
        from jarvis.agent.captcha_handoff import OWNER

        OWNER.stage(
            session_id=session_id,
            task_id=task_id,
            authority=_SelectedTabCaptchaAuthority(host),
        )
        error = "selected_tab_handoff_required"
    elif result.ambiguous:
        error = "selected_tab_action_unverified_do_not_retry"
    else:
        error = str(result.reason or "selected_tab_action_blocked")
    content = {
        "state": str(result.state or "blocked"),
        **evidence,
        "after_observation": _observation_content(result.after_observation),
    }
    return ToolResult(
        ok=False,
        content=content,
        error=error,
        meta={
            "do_not_retry": bool(result.ambiguous),
            **evidence,
        },
    )


class _SelectedTabActionTool(Tool):
    wants_context = True
    timeout_s = 30
    action = ""
    capability = ""

    def __init__(self, *, host=None) -> None:
        self._host = host
        self._snapshot_provider = None

    def _action_args(self, **_kwargs) -> dict:
        return {}

    def _host_and_binding(self, _session):
        binding, error = _runtime_binding(_session, self._snapshot_provider)
        return self._host or get_host(), binding, error

    def needs_confirmation(self, **kwargs) -> bool:
        _session = kwargs.get("_session")
        host, binding, error = self._host_and_binding(_session)
        if error or binding is None:
            return True
        session_id, task_id, target_id, target_generation = binding
        try:
            decision = host.classify_action(
                action=self.action,
                session_id=session_id,
                task_id=task_id,
                target_id=target_id,
                target_generation=target_generation,
                observation_id=str(kwargs.get("observation_id", "") or ""),
                element_id=str(kwargs.get("element_id", "") or ""),
                **self._action_args(**kwargs),
            )
            if not decision.allowed:
                return False
        except Exception:
            return True
        return bool(decision.requires_confirmation)

    def confirmation_text(self, **_) -> str:
        return "Izinkan satu aksi terikat pada tab Chrome yang dipilih?"

    async def run(
        self,
        observation_id: str,
        element_id: str,
        _session=None,
        _context=None,
        _selected_tab_confirmation: bool = False,
        **kwargs,
    ) -> ToolResult:
        from jarvis.agent.policy import selected_tab_context_error

        context_error = selected_tab_context_error(
            _context,
            capability=self.capability,
            risk="medium",
            runtime_session=_session,
        )
        if context_error:
            return ToolResult.fail(context_error)
        host, binding, error = self._host_and_binding(_session)
        if error or binding is None:
            return ToolResult.fail(error)
        session_id, task_id, target_id, target_generation = binding
        try:
            result = host.act_selected(
                action=self.action,
                session_id=session_id,
                task_id=task_id,
                target_id=target_id,
                target_generation=target_generation,
                observation_id=str(observation_id),
                element_id=str(element_id),
                confirmation=bool(_selected_tab_confirmation),
                **self._action_args(**kwargs),
            )
        except Exception as exc:
            return ToolResult.fail(
                f"selected_tab_action_failed:{type(exc).__name__}",
                attempted=False,
                executed=False,
                verified=False,
                ambiguous=False,
            )
        return _action_tool_result(
            result,
            host=host,
            session_id=session_id,
            task_id=task_id,
        )


class SelectedTabClick(_SelectedTabActionTool):
    name = "selected_tab_click"
    description = (
        "Klik satu exact opaque element reference dari selected tab. Tidak menerima "
        "selector, koordinat, tab identity, JavaScript, atau fallback native."
    )
    params_schema = _TargetParams
    action = "click"
    capability = "selected_tab.click"


class SelectedTabType(_SelectedTabActionTool):
    name = "selected_tab_type"
    description = (
        "Isi satu text field non-sensitif pada selected tab dengan fill bounded. "
        "Tidak mengirim Enter atau submit implicit."
    )
    params_schema = _TypeParams
    action = "type"
    capability = "selected_tab.type"

    def _action_args(self, **kwargs) -> dict:
        return {"text": str(kwargs.get("text", ""))}


class SelectedTabScroll(_SelectedTabActionTool):
    name = "selected_tab_scroll"
    description = (
        "Scroll selected tab ke arah up/down sebanyak 1-5 langkah fixed internal. "
        "Tidak menerima pixel delta atau koordinat."
    )
    params_schema = _ScrollParams
    action = "scroll"
    capability = "selected_tab.scroll"

    def _action_args(self, **kwargs) -> dict:
        return {
            "direction": str(kwargs.get("direction", "")),
            "count": kwargs.get("count", 1),
        }


__all__ = [
    "SelectedTabClick",
    "SelectedTabObserve",
    "SelectedTabScroll",
    "SelectedTabType",
]
