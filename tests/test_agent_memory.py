"""Memori agent §4 — tanpa embedding (provider mati), FTS/LIKE tetap jalan."""
from __future__ import annotations

import time

import pytest

import jarvis.agent.memory_store as ms


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "db_path", lambda: tmp_path / "agent.sqlite")
    monkeypatch.setattr(ms, "_embed", lambda texts: None)   # tanpa network
    yield


def test_write_and_search_keyword():
    ms.write("semantic", "User memakai Windows 11 dan workspace di E:",
             importance=0.8)
    ms.write("procedural", "Deploy = build lalu rsync ke server port 8080",
             importance=0.7)
    rows = ms.search("workspace windows")
    assert rows
    assert any("Windows 11" in r["content"] for r in rows)


def test_reflective_guardrail_threshold():
    ms.write("reflective", "Jangan klik sebelum snapshot", importance=0.9)
    ms.write("reflective", "Pelajaran remeh", importance=0.3)
    lessons = ms.get_reflective(min_importance=0.6)
    contents = [m["content"] for m in lessons]
    assert "Jangan klik sebelum snapshot" in contents
    assert "Pelajaran remeh" not in contents


def test_supersede_hides_memory():
    mid = ms.write("semantic", "Port server adalah 8080")
    assert any(r["id"] == mid for r in ms.search("port server"))
    ms.supersede(mid)
    assert not any(r["id"] == mid for r in ms.search("port server"))


def test_update_and_forget():
    mid = ms.write("semantic", "fakta lama")
    assert ms.update(mid, "fakta baru yang benar")
    rows = ms.search("fakta baru")
    assert any(r["id"] == mid for r in rows)
    assert ms.forget(mid)
    assert not ms.forget(mid)


def test_importance_clamped():
    mid = ms.write("semantic", "penting sekali", importance=9.9)
    rows = ms.search("penting sekali")
    row = next(r for r in rows if r["id"] == mid)
    assert row["importance"] <= 1.0


def test_consolidate_deletes_noise(monkeypatch):
    mid = ms.write("semantic", "noise", importance=0.05)
    stats = ms.consolidate()
    assert stats["deleted"] >= 1
    assert not any(r["id"] == mid for r in ms.search("noise"))


def test_reflect_writes_memories(monkeypatch):
    from jarvis.agent import reflect as rf
    from jarvis.agent.session import Session

    class FakeClient:
        def available(self):
            return True

        def generate(self, prompt, system=None, json_mode=False):
            return ('{"semantic": [{"content": "User suka jawaban singkat",'
                    ' "importance": 0.8}], "procedural": [],'
                    ' "reflective": [{"content": "Jangan pakai tool X dulu",'
                    ' "importance": 0.7}], "contradicts": []}')

    import jarvis.agent.llm_client as lc
    monkeypatch.setattr(lc, "client", lambda name=None: FakeClient())

    s = Session(task="tes", adapter_name="test", is_subagent=False)
    s.turn_count = 4
    s.transcript = [{"role": "user", "content": "halo", "ts": time.time()}]
    # is_subagent False + turn_count>=2 → berjalan
    data = rf.reflect(s)
    assert data is not None
    rows = ms.search("jawaban singkat")
    assert rows
    lessons = ms.get_reflective(0.6)
    assert any("tool X" in m["content"] for m in lessons)


def test_reflect_skips_trivial_session(monkeypatch):
    from jarvis.agent import reflect as rf
    from jarvis.agent.session import Session
    s = Session(task="tes")
    s.turn_count = 1
    assert rf.reflect(s) is None
