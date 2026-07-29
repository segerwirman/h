"""Memory scope policy: fail closed across remote actors and workspaces."""
from __future__ import annotations

SCOPES = frozenset({"device-local", "user", "platform-actor", "workspace", "ephemeral-task"})
_RETENTION_SECONDS = {"ephemeral-task": 24 * 60 * 60}


def retention_seconds(scope: str) -> int | None:
    """Only ephemeral task context expires automatically by default."""
    return _RETENTION_SECONDS.get(scope)


def owner_for(*, scope: str, source: str, actor_id: str, workspace_id: str = "",
              task_id: str = "") -> str:
    if scope == "platform-actor":
        return f"{source}:{actor_id}"
    if scope == "workspace":
        return str(workspace_id)
    if scope == "ephemeral-task":
        return str(task_id)
    return str(actor_id) if scope == "user" else "device"


def can_access(*, scope: str, owner: str, source: str, actor_id: str,
               operation: str) -> bool:
    """Authorize a scoped read/write without ever widening a remote identity."""
    if operation not in {"read", "write", "delete", "export"} or scope not in SCOPES:
        return False
    if scope in {"device-local", "user"}:
        return source in {"desktop", "voice", "local"}
    if scope == "platform-actor":
        return owner == f"{source}:{actor_id}" and bool(actor_id)
    # Workspace/task IDs are supplied by a local resolver; remote ingress cannot infer them.
    return source in {"desktop", "voice", "local"} and bool(owner)
