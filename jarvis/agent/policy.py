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
        # Schema visibility is deliberately separate from execution authority.
        # The selected-tab surface owner added in the next slice performs the
        # exact task/session/target binding before this branch can allow calls.
        return PolicyDecision(False, False, "selected_tab_share_required")
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
    """Require exact process-local Screen Control session and task ownership."""
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
    if str(snapshot.session_id or "") != runtime_session_id:
        return "screen_control_session_mismatch"
    if str(snapshot.task_id or "") != runtime_task_id:
        return "screen_control_task_mismatch"
    return ""
