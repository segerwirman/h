"""Fase 10 — management snapshot is safe, compact, and read-only."""
from __future__ import annotations

import importlib


def test_control_plane_snapshot_menyaring_raw_session_dan_provider_secret(monkeypatch):
    try:
        surface = importlib.import_module("jarvis.agent.management_surface")
    except ModuleNotFoundError:
        surface = None

    assert surface is not None
    monkeypatch.setattr(surface.session, "recent_sessions", lambda limit: [{
        "id": "s1", "adapter": "ui", "task": "secret task", "result": "raw result",
        "started_at": 10, "ended_at": 20, "turn_count": 3, "ok": 1,
    }])
    monkeypatch.setattr(surface, "all_providers", lambda: [type("P", (), {
        "safe_dict": lambda self: {"name": "local", "api_key_set": True,
                                   "base_url": "http://private", "model": "m"}
    })()])
    monkeypatch.setattr(surface.dispatch, "active_tasks", lambda: ["raw active task"])

    snapshot = surface.snapshot()

    assert snapshot["sessions"] == [{"id": "s1", "source": "ui", "status": "completed",
                                      "turn_count": 3}]
    assert snapshot["providers"] == [{"name": "local", "configured": True, "model": "m"}]
    assert snapshot["active_task_count"] == 1
    assert "secret task" not in repr(snapshot)
    assert "private" not in repr(snapshot)
    assert "raw active task" not in repr(snapshot)


def test_surface_registry_menolak_panel_bila_capability_dimatikan():
    surface = importlib.import_module("jarvis.agent.management_surface")
    registry = surface.SurfaceRegistry({"sessions": False})

    registry.register("sessions", "Sessions", required_capability="sessions")
    registry.register("health", "Provider Health")

    assert registry.visible_ids() == ("health",)
    assert registry.get("sessions") is None


def test_control_plane_snapshot_hanya_memuat_count_scope_memory(monkeypatch):
    surface = importlib.import_module("jarvis.agent.management_surface")
    monkeypatch.setattr(surface, "memory_scope_counts",
                        lambda: {"device-local": 3, "platform-actor": 2})

    snapshot = surface.snapshot()

    assert snapshot["memory_scopes"] == {"device-local": 3, "platform-actor": 2}
