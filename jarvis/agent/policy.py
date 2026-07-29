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
