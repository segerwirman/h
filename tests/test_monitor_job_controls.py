"""Desktop-local monitor job control persists only enablement and safe status metadata."""
from __future__ import annotations

_APP = None


def _registry(tmp_path):
    from jarvis.monitoring.source_registry_store import PersistentSourceRegistry

    sources = PersistentSourceRegistry(tmp_path / "sources.sqlite")
    source = sources.add("News", "https://example.org/feed", "rss", rate_limit_s=60)
    sources.select(source.id)
    return sources


def test_local_enable_disable_persists_across_reopen_without_task_or_result(tmp_path):
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry

    path = tmp_path / "jobs.sqlite"
    jobs = MonitorJobRegistry(path, _registry(tmp_path))
    job = jobs.register_selected("*/5 * * * *", "desktop_only")

    disabled = jobs.set_enabled(job.id, False)
    assert disabled.enabled is False
    reopened = MonitorJobRegistry(path, jobs.sources)
    persisted = reopened.list()[0]
    assert persisted.enabled is False
    assert set(persisted.public_dict()) == {
        "id", "source_id", "source", "schedule", "delivery_mode", "enabled",
        "last_status", "last_status_at",
    }
    assert persisted.last_status == "not_started"
    assert persisted.last_status_at is None
    assert "task" not in persisted.public_dict()
    assert "result" not in persisted.public_dict()


def test_registry_persists_only_allowlisted_safe_status_and_timestamp(tmp_path):
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry

    jobs = MonitorJobRegistry(tmp_path / "jobs.sqlite", _registry(tmp_path))
    job = jobs.register_selected("*/5 * * * *", "desktop_only")

    updated = jobs.record_safe_status(job.id, "ok", 123.5)
    assert updated.last_status == "ok"
    assert updated.last_status_at == 123.5
    reopened = MonitorJobRegistry(jobs.path, jobs.sources).list()[0]
    assert reopened.last_status == "ok"
    assert reopened.last_status_at == 123.5

    import pytest
    for unsafe in ("Traceback: private", "raw body", "exception", "arbitrary"):
        with pytest.raises(ValueError):
            jobs.record_safe_status(job.id, unsafe, 124.0)


def test_disabled_job_is_not_installed_and_worker_records_safe_tick_status(tmp_path):
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
    from jarvis.monitoring.worker import MonitorWorker

    jobs = MonitorJobRegistry(tmp_path / "jobs.sqlite", _registry(tmp_path))
    disabled = jobs.register_selected("*/5 * * * *", "desktop_only")
    enabled = jobs.register_selected("*/10 * * * *", "desktop_only")
    jobs.set_enabled(disabled.id, False)
    created = []

    class Scheduler:
        def create_monitor_job(self, source, schedule):
            created.append(schedule)
            return {"id": schedule}

    class Delivery:
        def bind_job(self, job, mode):
            return None
        def run_due(self):
            return []

    worker = MonitorWorker(jobs=jobs, scheduler=Scheduler(), delivery=Delivery(), now=lambda: 456.0)
    assert worker.start() is True
    worker.tick_once()
    by_id = {job.id: job for job in MonitorJobRegistry(jobs.path, jobs.sources).list()}
    assert created == [enabled.schedule]
    assert by_id[disabled.id].last_status == "not_started"
    assert by_id[enabled.id].last_status == "ok"
    assert by_id[enabled.id].last_status_at == 456.0
    worker.stop()


def test_sheet_exposes_local_enable_disable_and_only_safe_job_summary(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    global _APP
    _APP = QApplication.instance() or QApplication([])
    from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
    from jarvis.ui.monitor_source_sheet import MonitorSourceSheet

    sources = PersistentSourceRegistry(tmp_path / "sources.sqlite")
    source = sources.add("News", "https://example.org/feed", "rss", rate_limit_s=60)
    sources.select(source.id)
    jobs = MonitorJobRegistry(tmp_path / "jobs.sqlite", sources)
    job = jobs.register_selected("*/5 * * * *", "desktop_only")
    sheet = MonitorSourceSheet(sources)
    sheet.jobs = jobs

    assert sheet.set_job_enabled(job.id, False) is True
    assert jobs.list()[0].enabled is False
    assert "dinonaktifkan" in sheet.summary_text().lower()
    assert sheet.set_job_enabled(job.id, True) is True
    assert jobs.list()[0].enabled is True


def test_sheet_renders_finite_job_states_in_indonesian_without_timestamp_or_error_detail(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    global _APP
    _APP = QApplication.instance() or QApplication([])
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
    from jarvis.ui.monitor_source_sheet import MonitorSourceSheet

    sources = _registry(tmp_path)
    jobs = MonitorJobRegistry(tmp_path / "jobs.sqlite", sources)
    active = jobs.register_selected("*/5 * * * *", "desktop_only")
    disabled = jobs.register_selected("*/10 * * * *", "desktop_only")
    jobs.set_enabled(disabled.id, False)
    jobs.record_safe_status(active.id, "source_failed", 123456.0)
    sheet = MonitorSourceSheet(sources)
    sheet.jobs = jobs
    sheet.refresh()

    text = sheet.summary_text()
    assert "Aktif" in text
    assert "Dinonaktifkan" in text
    assert "Gagal mengambil sumber" in text
    assert "Belum pernah berjalan" in text
    job_text = "\n".join(line for line in text.splitlines() if line.startswith("Job:"))
    for forbidden in ("123456", "Traceback", "Exception", "body", "token", "cookie", "header"):
        assert forbidden.lower() not in job_text.lower()


def test_selected_source_without_job_cannot_toggle_another_job(tmp_path):
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    global _APP
    _APP = QApplication.instance() or QApplication([])
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
    from jarvis.ui.monitor_source_sheet import MonitorSourceSheet

    sources = _registry(tmp_path)
    first = sources.selected()
    second = sources.add("Other", "https://example.org/other", "rss", rate_limit_s=60)
    jobs = MonitorJobRegistry(tmp_path / "jobs.sqlite", sources)
    job = jobs.register_selected("*/5 * * * *", "desktop_only")
    sources.select(second.id)
    sheet = MonitorSourceSheet(sources)
    sheet.jobs = jobs
    sheet._set_selected_job_enabled(False)

    assert jobs.list()[0].enabled is True
    assert sheet.summary_text() == "Belum ada job untuk source dipilih."
    assert first is not None


def test_control_store_has_no_generic_cron_or_raw_result_authority():
    from jarvis.monitoring import monitor_job_store

    source = open(monitor_job_store.__file__, encoding="utf-8").read()
    for forbidden in ("agent.cron", "dispatch.run_sync", "subprocess", "webbrowser", "raw_result", "exception_text"):
        assert forbidden not in source
    assert not hasattr(monitor_job_store.MonitorJobRegistry, "register_remote")
    assert not hasattr(monitor_job_store.MonitorJobRegistry, "run_task")
