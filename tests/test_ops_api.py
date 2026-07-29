"""Framework maturity Phase 13 — ops API returns safe snapshot and audit metadata."""
from __future__ import annotations


def test_ops_api_snapshot_hanya_metadata_dan_audit_hashed_actor(monkeypatch):
    from jarvis.ops import api

    monkeypatch.setattr(api.management_surface, "snapshot", lambda: {
        "sessions": [], "providers": [], "active_task_count": 0, "memory_scopes": {},
    })
    service = api.OpsAPI()

    assert service.snapshot("observer")["active_task_count"] == 0
    event = service.audit("local-admin", "gateway.pair", actor_id="raw-actor")

    assert event["action"] == "gateway.pair"
    assert "raw-actor" not in repr(event)


def test_ops_api_deny_mutation_role_tidak_berhak():
    from jarvis.ops.api import OpsAPI

    service = OpsAPI()
    assert service.audit("observer", "gateway.pair", actor_id="actor") is None


def test_ops_audit_persist_restart_dan_tetap_redacted(tmp_path):
    from jarvis.ops.api import OpsAPI

    path = tmp_path / "audit.sqlite"
    first = OpsAPI(path)
    first.audit("local-admin", "gateway.pair", actor_id="actor-private")

    rows = OpsAPI(path).recent_audit("observer")
    assert len(rows) == 1
    assert "actor-private" not in repr(rows)


def test_ops_restart_gateway_memakai_manager_runtime_dan_diaudit(tmp_path):
    from jarvis.ops.api import OpsAPI

    calls = []

    class Manager:
        def stop(self, platform):
            calls.append(("stop", platform))

        def start(self, platform):
            calls.append(("start", platform))
            return True

    service = OpsAPI(tmp_path / "audit.sqlite", manager=Manager())

    assert service.restart_gateway("local-admin", "telegram", actor_id="local-user")
    assert calls == [("stop", "telegram"), ("start", "telegram")]
    assert service.recent_audit("observer")[0]["action"] == "gateway.restart"


def test_ops_default_menggunakan_manager_runtime_telegram(monkeypatch, tmp_path):
    from jarvis.gateway import runtime
    from jarvis.ops.api import OpsAPI

    calls = []

    class Manager:
        def stop(self, platform):
            calls.append(("stop", platform))

        def start(self, platform):
            calls.append(("start", platform))
            return True

    monkeypatch.setattr(runtime, "telegram_runtime", lambda: type(
        "Runtime", (), {"manager": Manager()})())
    service = OpsAPI(tmp_path / "audit.sqlite")

    assert service.restart_gateway("local-admin", "telegram", actor_id="local-user")
    assert calls == [("stop", "telegram"), ("start", "telegram")]
