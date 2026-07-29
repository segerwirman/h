"""Framework maturity Phase 8 — durable job-run trace is payload bounded."""
from __future__ import annotations


def test_job_store_merekam_lifecycle_dan_result_terpotong(tmp_path):
    from jarvis.agent.job_store import JobStore

    store = JobStore(tmp_path / "jobs.sqlite")
    run = store.start("job-1", "trace-rahasia")
    done = store.finish(run.id, ok=True, result="x" * 5000)

    assert done.state == "completed"
    assert len(done.result) == 2000
    assert "trace-rahasia" not in repr(done.safe_dict())


def test_job_store_menolak_run_kedua_yang_masih_active(tmp_path):
    from jarvis.agent.job_store import JobStore

    store = JobStore(tmp_path / "jobs.sqlite")
    store.start("job-1", "t1")

    try:
        store.start("job-1", "t2")
    except RuntimeError as exc:
        assert str(exc) == "job_already_running"
    else:
        raise AssertionError("concurrent run must be rejected")
