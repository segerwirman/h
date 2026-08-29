"""Small, fail-closed capability policy for all Jarvis execution surfaces."""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.agent.execution_context import ExecutionContext


@dataclass(frozen=True)
class PolicyDecision:
    allowed: bool
    needs_approval: bool
    reason: str


def decide(context: ExecutionContext, *, capability: str, risk: str) -> PolicyDecision:
    """Return a safe default; callers execute only when ``allowed`` is true."""
    group = capability.split(".", 1)[0]
    if group == "desktop_safe":
        if context.surface != "desktop":
            return PolicyDecision(False, False, "desktop_local_surface_required")
        if context.source not in {"ui", "agent"}:
            return PolicyDecision(False, False, "desktop_local_source_required")
        if "desktop_safe" not in context.toolsets:
            return PolicyDecision(False, False, "desktop_safe_toolset_required")
        return PolicyDecision(True, False, "desktop_safe_allowed")
    if group == "selected_tab":
        if context.surface != "browser_tab":
            return PolicyDecision(False, False, "selected_tab_surface_required")
        if context.source != "ui":
            return PolicyDecision(False, False, "selected_tab_local_source_required")
        if "selected_tab" not in context.toolsets:
            return PolicyDecision(False, False, "selected_tab_toolset_required")
        # Runtime execution still needs the exact active lease check in
        # ``selected_tab_context_error``; this decision validates only the
        # immutable local execution context.
        return PolicyDecision(True, False, "selected_tab_context_allowed")
    required_toolsets = {
        "agent": "agent",
        "files": "files_write" if risk.lower() in {"high", "critical"}
        else "files_read",
    }
    required = required_toolsets.get(group, group)
    if context.surface == "remote" and group == "desktop":
        return PolicyDecision(False, False, "remote_surface_denied")
    if required not in context.toolsets and "safe" not in context.toolsets:
        return PolicyDecision(False, False, "toolset_denied")
    if risk.lower() in {"high", "critical"}:
        return PolicyDecision(False, True, "approval_required")
    return PolicyDecision(True, False, "allowed")


def desktop_safe_context_error(context, *, capability: str, risk: str = "medium",
                               runtime_session=None) -> str:
    """Return a fail-closed reason when an action lacks local desktop authority."""
    if not isinstance(context, ExecutionContext):
        return "desktop_safe_execution_context_required"
    runtime_session_id = str(getattr(runtime_session, "id", "") or "")
    if runtime_session is not None and runtime_session_id != str(context.session_id or ""):
        return "desktop_safe_context_session_mismatch"
    decision = decide(context, capability=capability, risk=risk)
    if not decision.allowed:
        return f"desktop_safe_policy_denied:{decision.reason}"
    return ""


def screen_control_context_error(context, *, capability: str,
                                 risk: str = "medium", runtime_session=None) -> str:
    """Require exact process-local native desktop session/task ownership."""
    context_error = desktop_safe_context_error(
        context,
        capability=capability,
        risk=risk,
        runtime_session=runtime_session,
    )
    if context_error:
        return context_error
    runtime_session_id = str(getattr(runtime_session, "id", "") or "")
    runtime_task_id = str(getattr(runtime_session, "registry_task_id", "") or "")
    if not runtime_session_id or not runtime_task_id:
        return "screen_control_runtime_task_binding_required"
    try:
        from jarvis.ui import screen_control

        snapshot = screen_control.COORDINATOR.snapshot()
    except Exception:
        return "screen_control_state_unavailable"
    if snapshot.state != screen_control.ACTIVE:
        return "screen_control_not_active"
    surface_kind = str(getattr(snapshot, "surface_kind", "") or "")
    if surface_kind and surface_kind != screen_control.DESKTOP_SURFACE:
        return "screen_control_desktop_surface_required"
    if str(snapshot.session_id or "") != runtime_session_id:
        return "screen_control_session_mismatch"
    if str(snapshot.task_id or "") != runtime_task_id:
        return "screen_control_task_mismatch"
    return ""


def selected_tab_context_error(context, *, capability: str,
                               risk: str = "medium", runtime_session=None) -> str:
    """Require the exact active browser-tab lease for a local parent task."""
    if not isinstance(context, ExecutionContext):
        return "selected_tab_execution_context_required"
    runtime_session_id = str(getattr(runtime_session, "id", "") or "")
    if runtime_session is not None and runtime_session_id != str(context.session_id or ""):
        return "selected_tab_context_session_mismatch"
    decision = decide(context, capability=capability, risk=risk)
    if not decision.allowed:
        return f"selected_tab_policy_denied:{decision.reason}"
    runtime_task_id = str(getattr(runtime_session, "registry_task_id", "") or "")
    if not runtime_session_id or not runtime_task_id:
        return "selected_tab_runtime_task_binding_required"
    try:
        from jarvis.ui import screen_control

        coordinator = screen_control.COORDINATOR
        snapshot = coordinator.snapshot()
    except Exception:
        return "selected_tab_state_unavailable"
    if snapshot.state != screen_control.ACTIVE:
        return "selected_tab_not_active"
    if str(getattr(snapshot, "surface_kind", "") or "") != screen_control.BROWSER_TAB_SURFACE:
        return "selected_tab_surface_mismatch"
    if str(snapshot.session_id or "") != runtime_session_id:
        return "selected_tab_session_mismatch"
    if str(snapshot.task_id or "") != runtime_task_id:
        return "selected_tab_task_mismatch"
    try:
        lease_error = coordinator.selected_tab_binding_error()
    except Exception:
        return "selected_tab_state_unavailable"
    return str(lease_error or "")
