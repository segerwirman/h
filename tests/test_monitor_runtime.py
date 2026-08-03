"""17H runtime bootstrap is monitor-only and supervisor-friendly."""
from __future__ import annotations
from pathlib import Path


def test_runtime_start_returns_worker_and_registers_persistent_paths(monkeypatch, tmp_path):
    from jarvis.monitoring import runtime
    monkeypatch.setattr(runtime.config, "base_dir", lambda: tmp_path)
    worker = runtime.start()
    assert worker is not None
    assert worker.jobs.path == tmp_path / "data" / "monitor_jobs.sqlite"
    assert worker.jobs.sources.path == tmp_path / "data" / "monitor_sources.sqlite"
    worker.stop()
