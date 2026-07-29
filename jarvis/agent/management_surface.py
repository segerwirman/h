"""Read-only, secret-safe state model for Jarvis management surfaces."""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.agent import dispatch, providers, session


def memory_scope_counts() -> dict[str, int]:
    try:
        from jarvis.agent import memory_store
        return memory_store.scope_counts()
    except Exception:  # noqa: BLE001
        return {}


@dataclass(frozen=True)
class Surface:
    id: str
    title: str
    required_capability: str = ""


class SurfaceRegistry:
    """Capability-gated list for opt-in, read-only management surfaces."""

    def __init__(self, capabilities: dict[str, bool] | None = None) -> None:
        self._capabilities = dict(capabilities or {})
        self._surfaces: dict[str, Surface] = {}

    def register(self, surface_id: str, title: str,
                 required_capability: str = "") -> None:
        self._surfaces[surface_id] = Surface(surface_id, title, required_capability)

    def get(self, surface_id: str) -> Surface | None:
        surface = self._surfaces.get(surface_id)
        if surface is None or (surface.required_capability and not self._capabilities.get(
                surface.required_capability, True)):
            return None
        return surface

    def visible_ids(self) -> tuple[str, ...]:
        return tuple(surface_id for surface_id in self._surfaces
                     if self.get(surface_id) is not None)


def _session_item(row: dict) -> dict:
    ended = row.get("ended_at")
    return {
        "id": str(row.get("id", ""))[:32],
        "source": str(row.get("adapter", "unknown"))[:32],
        "status": "completed" if ended and row.get("ok") else "failed" if ended else "running",
        "turn_count": max(0, int(row.get("turn_count", 0) or 0)),
    }


def _provider_item(provider) -> dict:
    safe = provider.safe_dict()
    return {
        "name": str(safe.get("name", ""))[:64],
        "configured": bool(safe.get("api_key_set")) or bool(safe.get("enabled")),
        "model": str(safe.get("model", ""))[:128],
    }


def snapshot(session_limit: int = 12) -> dict:
    """Compact state only. Never return task/result/error/base URL/auth data."""
    try:
        sessions = session.recent_sessions(max(1, min(int(session_limit), 50)))
    except Exception:  # noqa: BLE001
        sessions = []
    return {
        "sessions": [_session_item(row) for row in sessions],
        "providers": [_provider_item(provider) for provider in all_providers()],
        "active_task_count": len(dispatch.active_tasks()),
        "memory_scopes": memory_scope_counts(),
    }


def all_providers() -> list:
    out = []
    for name in providers.list_names():
        try:
            out.append(providers.get_provider(name))
        except Exception:  # noqa: BLE001
            continue
    return out
