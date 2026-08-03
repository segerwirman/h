"""17K: monitor jobs rehydrate safely after a local runtime restart."""
from __future__ import annotations


def _persisted_jobs(tmp_path):
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
    from jarvis.monitoring.source_registry_store import PersistentSourceRegistry

    sources = PersistentSourceRegistry(tmp_path / "sources.sqlite")
    source = sources.add("News", "https://example.org/feed", "rss", rate_limit_s=60)
    sources.select(source.id)
    jobs = MonitorJobRegistry(tmp_path / "jobs.sqlite", sources)
    enabled = jobs.register_selected("*/5 * * * *", "desktop_only")
    disabled = jobs.register_selected("*/10 * * * *", "desktop_only")
    jobs.set_enabled(disabled.id, False)
    jobs.record_safe_status(enabled.id, "ok", 123.0)
    return sources, jobs.path, enabled, disabled


class _Scheduler:
    def __init__(self):
        self.created = []

    def create_monitor_job(self, source, schedule):
        self.created.append((source, schedule))
        return {"id": f"runtime-{len(self.created)}"}


class _Delivery:
    def __init__(self):
        self.bound = []

    def bind_job(self, job, mode):
        self.bound.append((job["id"], mode))

    def run_due(self):
        return []


def test_restart_rehydrates_only_enabled_job_once_and_preserves_safe_metadata(tmp_path):
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
    from jarvis.monitoring.worker import MonitorWorker

    sources, path, enabled, disabled = _persisted_jobs(tmp_path)
    first = MonitorWorker(jobs=MonitorJobRegistry(path, sources), scheduler=_Scheduler(), delivery=_Delivery(), now=lambda: 200.0)
    assert first.start() is True
    first.tick_once()
    first.stop()

    restarted_jobs = MonitorJobRegistry(path, sources)
    scheduler, delivery = _Scheduler(), _Delivery()
    restarted = MonitorWorker(jobs=restarted_jobs, scheduler=scheduler, delivery=delivery, now=lambda: 300.0)
    assert restarted.start() is True
    assert restarted.start() is False

    persisted = {job.id: job for job in restarted_jobs.list()}
    assert [schedule for _, schedule in scheduler.created] == [enabled.schedule]
    assert delivery.bound == [("runtime-1", "desktop_only")]
    assert persisted[enabled.id].enabled is True
    assert persisted[enabled.id].last_status == "ok"
    assert persisted[enabled.id].last_status_at == 200.0
    assert persisted[disabled.id].enabled is False
    assert persisted[disabled.id].last_status == "not_started"
    assert persisted[disabled.id].last_status_at is None
    for job in persisted.values():
        assert set(job.public_dict()) == {
            "id", "source_id", "source", "schedule", "delivery_mode", "enabled",
            "last_status", "last_status_at",
        }
    restarted.stop()


def test_stop_joins_launched_worker_before_runtime_reconstruction(tmp_path):
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
    from jarvis.monitoring.worker import MonitorWorker

    sources, path, _, _ = _persisted_jobs(tmp_path)
    first = MonitorWorker(jobs=MonitorJobRegistry(path, sources), scheduler=_Scheduler(), delivery=_Delivery())
    assert first.launch() is True
    assert first.thread is not None and first.thread.is_alive()
    first.stop()
    assert first.thread is not None and not first.thread.is_alive()


def test_restart_lifecycle_has_no_generic_execution_or_raw_result_surface():
    from jarvis.monitoring import monitor_job_store, runtime, worker

    combined = "\n".join(open(module.__file__, encoding="utf-8").read() for module in (monitor_job_store, runtime, worker))
    for forbidden in ("agent.cron", "dispatch.run_sync", "subprocess", "webbrowser", "raw_result", "exception_text", "browser_login"):
        assert forbidden not in combined
    assert not hasattr(runtime, "start_remote")
    assert not hasattr(worker.MonitorWorker, "run_task")
