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
