"""Static local acceptance fixture for the monitor lifecycle soak."""
from __future__ import annotations

import tempfile
from pathlib import Path


class _Scheduler:
    def __init__(self):
        self.created = []

    def create_monitor_job(self, source, schedule):
        self.created.append(schedule)
        return {"id": f"runtime-{len(self.created)}"}


class _Delivery:
    def bind_job(self, job, mode):
        return None

    def run_due(self):
        return []


def _jobs(root: Path):
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
    from jarvis.monitoring.source_registry_store import PersistentSourceRegistry

    sources = PersistentSourceRegistry(root / "sources.sqlite")
    source = sources.add("Fixture", "https://example.org/feed", "rss", rate_limit_s=60)
    sources.select(source.id)
    jobs = MonitorJobRegistry(root / "jobs.sqlite", sources)
    enabled = jobs.register_selected("*/5 * * * *", "desktop_only")
    disabled = jobs.register_selected("*/10 * * * *", "desktop_only")
    jobs.set_enabled(disabled.id, False)
    return sources, jobs, enabled, disabled


def run_fixture(name: str) -> bool:
    from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
    from jarvis.monitoring.worker import MonitorWorker

    if name not in {"enabled", "disabled", "safe_failure", "restart"}:
        return False
    with tempfile.TemporaryDirectory(prefix="monitor-soak-") as raw:
        root = Path(raw)
        sources, jobs, enabled, disabled = _jobs(root)
        scheduler = _Scheduler()
        delivery = _Delivery()
        worker = MonitorWorker(jobs=jobs, scheduler=scheduler, delivery=delivery, now=lambda: 10.0)
        if not worker.start() or worker.start():
            return False
        if name == "enabled":
            return scheduler.created == [enabled.schedule]
        if name == "disabled":
            return disabled.schedule not in scheduler.created
        if name == "safe_failure":
            class BrokenDelivery(_Delivery):
                def run_due(self):
                    raise RuntimeError("hidden")
            failed = MonitorWorker(jobs=jobs, scheduler=_Scheduler(), delivery=BrokenDelivery(), now=lambda: 11.0)
            failed.start(); failed.tick_once()
            return failed.status()["last_status"] == "source_failed"
        worker.tick_once(); worker.stop()
        reopened = MonitorJobRegistry(jobs.path, sources)
        restarted_scheduler = _Scheduler()
        restarted = MonitorWorker(jobs=reopened, scheduler=restarted_scheduler, delivery=_Delivery())
        ok = restarted.start() and restarted_scheduler.created == [enabled.schedule]
        restarted.stop()
        return ok


def main() -> int:
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("fixture", choices=("enabled", "disabled", "safe_failure", "restart"))
    args = parser.parse_args()
    accepted = bool(run_fixture(args.fixture))
    print({"accepted": accepted, "verified": accepted})
    return 0 if accepted else 1


if __name__ == "__main__":
    raise SystemExit(main())
