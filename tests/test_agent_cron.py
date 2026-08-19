"""Cron agent — CRUD, klaim jadwal, run_now dengan dispatcher palsu."""
from __future__ import annotations

import time

import pytest

import jarvis.agent.cron as cron
from jarvis.core import bus, quiet




@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(cron, "db_path", lambda: tmp_path / "agent.sqlite")
    yield


def test_create_and_list():
    ok, jid = cron.create("tes-harian", "0 7 * * *", "buat laporan")
    assert ok
    jobs = cron.list_jobs()
    job = next(j for j in jobs if j["id"] == jid)
    assert job["name"] == "tes-harian"
    assert job["enabled"] == 1
    assert job["next_run"] is not None and job["next_run"] > time.time()


def test_invalid_schedule_rejected():
    ok, msg = cron.create("rusak", "bukan cron", "x")
    assert not ok
    assert "tidak valid" in msg


def test_duplicate_name_rejected():
    assert cron.create("dobel", "* * * * *", "a")[0]
    ok, msg = cron.create("dobel", "* * * * *", "b")
    assert not ok
    assert "sudah ada" in msg


def test_pause_resume_delete():
    _, jid = cron.create("toggle", "*/5 * * * *", "x")
    assert cron.set_enabled(jid, False)
    assert cron.get_job(jid)["enabled"] == 0
    assert cron.set_enabled(jid, True)
    assert cron.get_job(jid)["enabled"] == 1
    assert cron.delete(jid)
    assert cron.get_job(jid) is None


def test_update_schedule_recomputes_next_run():
    _, jid = cron.create("ubah", "0 7 * * *", "x")
    before = cron.get_job(jid)["next_run"]
    assert cron.update(jid, schedule="*/1 * * * *")
    after = cron.get_job(jid)["next_run"]
    assert after != before
    assert after - time.time() < 120


def test_notify_result_bus_failure_is_recorded_without_changing_payload(monkeypatch):
    events = []
    published = []

    class Bus:
        def publish(self, *args, **kwargs):
            published.append((args, kwargs))
            raise OSError("bus unavailable")

    monkeypatch.setattr(quiet, "swallowed", lambda event, exc=None, **context: events.append((event, exc, context)))
    monkeypatch.setattr(bus.BUS, "publish", Bus().publish)
    monkeypatch.setattr(cron, "BUS", bus.BUS, raising=False)
    monkeypatch.setattr(
        "jarvis.agent.adapters.telegram.send_from_anywhere",
        lambda _message: None,
    )

    cron._notify_result({"name": "daily", "internal": 0}, True, "completed")

    assert published == [(
        ("agent.cron.done",),
        {"name": "daily", "ok": True, "text": "completed"},
    )]
    assert len(events) == 1
    assert events[0][0] == "agent.cron.bus_publish_failed"
    assert isinstance(events[0][1], OSError)


def test_run_now_uses_dispatch(monkeypatch):
    calls = {}

    def fake_run_sync(task, adapter=None, timeout_s=None,
                      allowed_tools=None):
        calls["task"] = task
        return "hasil palsu"

    import jarvis.agent.dispatch as dispatch
    monkeypatch.setattr(dispatch, "run_sync", fake_run_sync)
    monkeypatch.setattr(cron, "_notify_result", lambda *a, **k: None)

    _, jid = cron.create("sekali", "0 0 1 1 *", "kerjakan hal penting")
    ok, _msg = cron.run_job_now(jid)
    assert ok
    deadline = time.time() + 5
    while time.time() < deadline:
        job = cron.get_job(jid)
        if job["run_count"] > 0:
            break
        time.sleep(0.05)
    job = cron.get_job(jid)
    assert job["run_count"] == 1
    assert calls["task"].endswith("kerjakan hal penting")
    assert "hasil palsu" in (job["last_result"] or "")


def test_run_now_menyimpan_job_lifecycle(monkeypatch, tmp_path):
    import jarvis.agent.job_store as job_store
    import jarvis.agent.dispatch as dispatch

    original_store = job_store.JobStore
    monkeypatch.setattr(job_store, "JobStore", lambda _path: original_store(tmp_path / "runs.sqlite"))
    monkeypatch.setattr(dispatch, "run_sync", lambda *args, **kwargs: "selesai")
    monkeypatch.setattr(cron, "_notify_result", lambda *args, **kwargs: None)

    _, job_id = cron.create("trace-job", "0 0 1 1 *", "kerjakan")
    assert cron.run_job_now(job_id)[0] is True
    deadline = time.time() + 5
    while time.time() < deadline:
        store = job_store.JobStore(tmp_path / "runs.sqlite")
        with store._conn() as conn:
            row = conn.execute("SELECT state, result FROM job_runs WHERE job_id = ?", (job_id,)).fetchone()
        if row and row[0] != "running":
            break
        time.sleep(0.05)

    assert row == ("completed", "selesai")


def test_skills_attached_prepended(monkeypatch, tmp_path):
    import jarvis.agent.skills as skills_mod
    monkeypatch.setattr(skills_mod, "skills_dir", lambda: tmp_path)
    (tmp_path / "resep").mkdir()
    (tmp_path / "resep" / "SKILL.md").write_text(
        "---\nname: resep\ndescription: d\n---\nlangkah rahasia",
        encoding="utf-8")

    seen = {}

    def fake_run_sync(task, adapter=None, timeout_s=None,
                      allowed_tools=None):
        seen["task"] = task
        return "ok"

    import jarvis.agent.dispatch as dispatch
    monkeypatch.setattr(dispatch, "run_sync", fake_run_sync)
    monkeypatch.setattr(cron, "_notify_result", lambda *a, **k: None)

    _, jid = cron.create("dengan-skill", "0 0 1 1 *", "masak",
                         skills=["resep"])
    cron.run_job_now(jid)
    deadline = time.time() + 5
    while time.time() < deadline and "task" not in seen:
        time.sleep(0.05)
    assert "langkah rahasia" in seen["task"]
    assert seen["task"].endswith("masak")
