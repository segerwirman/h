"""Explicit scoped-memory resolution for agent execution contexts."""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.agent.memory_policy import can_access, owner_for


@dataclass(frozen=True)
class MemoryScope:
    scope: str
    owner: str


def resolve(context=None) -> MemoryScope:
    """Return the narrowest durable memory scope available to this execution."""
    if context is None:
        return MemoryScope("device-local", "device")
    source = str(getattr(context, "source", "") or "local")
    actor_id = str(getattr(context, "actor_id", "") or "device")
    surface = str(getattr(context, "surface", "") or "")
    if surface == "remote":
        owner = owner_for(scope="platform-actor", source=source, actor_id=actor_id)
        if can_access(scope="platform-actor", owner=owner, source=source,
                      actor_id=actor_id, operation="read"):
            return MemoryScope("platform-actor", owner)
        raise PermissionError("memory_scope_denied")
    scope = "user"
    owner = owner_for(scope=scope, source=source, actor_id=actor_id)
    if can_access(scope=scope, owner=owner, source=source, actor_id=actor_id,
                  operation="read"):
        return MemoryScope(scope, owner)
    return MemoryScope("device-local", "device")
