"""Small fail-closed RBAC matrix for local Jarvis operations."""
from __future__ import annotations

_ROLES = {
    "observer": frozenset({"snapshot.read", "trace.read", "audit.read", "gateway.read",
                            "approval.read"}),
    "local-admin": frozenset({
        "snapshot.read", "trace.read", "audit.read", "gateway.pair", "gateway.revoke",
        "gateway.stop", "gateway.restart", "approval.read", "approval.approve",
        "approval.deny", "plugins.disable", "mcp.disable", "jobs.pause", "jobs.cancel",
        "memory.delete", "memory.export", "release.rollback",
    }),
}


def authorize(role: str, action: str) -> bool:
    return str(action) in _ROLES.get(str(role), frozenset())


def actions_for(role: str) -> tuple[str, ...]:
    return tuple(sorted(_ROLES.get(str(role), frozenset())))
