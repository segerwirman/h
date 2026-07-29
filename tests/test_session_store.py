"""Framework maturity Phase 9 — session search returns redacted safe excerpts."""
from __future__ import annotations


def test_session_store_search_merahasiakan_token_dan_menemukan_excerpt(tmp_path):
    from jarvis.agent.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions.sqlite")
    store.record("telegram", "actor-a", "build Orion selesai token=super-rahasia")

    rows = store.search("Orion", source="telegram", actor_id="actor-a")

    assert len(rows) == 1
    assert rows[0]["source"] == "telegram"
    assert "Orion" in rows[0]["excerpt"]
    assert "super-rahasia" not in rows[0]["excerpt"]


def test_session_store_hanya_mencari_scope_yang_diizinkan(tmp_path):
    from jarvis.agent.session_store import SessionStore

    store = SessionStore(tmp_path / "sessions.sqlite")
    store.record("telegram", "actor-a", "catatan actor A", scope="platform-actor")

    assert store.search("catatan", source="telegram", actor_id="actor-b") == []
