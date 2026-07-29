"""Framework maturity Phase 9 — memory scope never crosses remote actors."""
from __future__ import annotations


def test_policy_remote_actor_tidak_membaca_memori_pribadi_local():
    from jarvis.agent.memory_policy import can_access

    assert can_access(
        scope="user",
        owner="desktop-user",
        source="telegram",
        actor_id="remote-actor",
        operation="read",
    ) is False


def test_policy_actor_platform_hanya_bisa_scope_dirinya_sendiri():
    from jarvis.agent.memory_policy import can_access

    assert can_access(
        scope="platform-actor",
        owner="telegram:actor-a",
        source="telegram",
        actor_id="actor-a",
        operation="read",
    ) is True
    assert can_access(
        scope="platform-actor",
        owner="telegram:actor-a",
        source="telegram",
        actor_id="actor-b",
        operation="read",
    ) is False


def test_memory_store_memfilter_scope_dan_owner(tmp_path, monkeypatch):
    from jarvis.agent import memory_store

    monkeypatch.setattr(memory_store, "db_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(memory_store, "_embed", lambda _texts: None)
    memory_store.write(
        "semantic",
        "Preferensi actor A",
        scope="platform-actor",
        owner="telegram:actor-a",
    )

    allowed = memory_store.search("Preferensi", scope="platform-actor",
                                  owner="telegram:actor-a")
    denied = memory_store.search("Preferensi", scope="platform-actor",
                                 owner="telegram:actor-b")

    assert len(allowed) == 1
    assert denied == []


def test_policy_retention_ephemeral_berakhir_dan_local_tidak_automatic_expire():
    from jarvis.agent.memory_policy import retention_seconds

    assert retention_seconds("ephemeral-task") == 24 * 60 * 60
    assert retention_seconds("device-local") is None


def test_memory_store_menyaring_ephemeral_yang_expired(tmp_path, monkeypatch):
    import sqlite3
    from jarvis.agent import memory_store

    db = tmp_path / "memory.sqlite"
    monkeypatch.setattr(memory_store, "db_path", lambda: db)
    monkeypatch.setattr(memory_store, "_embed", lambda _texts: None)
    memory_store.write("episodic", "task ephemeral", scope="ephemeral-task", owner="task-1")
    with sqlite3.connect(db) as conn:
        conn.execute("UPDATE memories SET retention_until = 0")

    assert memory_store.search("ephemeral", scope="ephemeral-task", owner="task-1") == []


def test_memory_export_scope_terbatas_dan_redacted(tmp_path, monkeypatch):
    from jarvis.agent import memory_store

    monkeypatch.setattr(memory_store, "db_path", lambda: tmp_path / "memory.sqlite")
    monkeypatch.setattr(memory_store, "_embed", lambda _texts: None)
    memory_store.write(
        "semantic",
        "API_KEY=super-rahasia untuk actor A",
        scope="platform-actor",
        owner="telegram:actor-a",
    )

    rows = memory_store.export(scope="platform-actor", owner="telegram:actor-a")

    assert len(rows) == 1
    assert rows[0]["scope"] == "platform-actor"
    assert "super-rahasia" not in rows[0]["content"]
