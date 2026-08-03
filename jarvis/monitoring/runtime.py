"""17H monitor-only runtime bootstrap."""
from __future__ import annotations

from jarvis.core import config
from jarvis.monitoring.auto_delivery import MonitorDeliveryCoordinator
from jarvis.monitoring.monitor_job_store import MonitorJobRegistry
from jarvis.monitoring.scheduler import MonitorScheduler
from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
from jarvis.monitoring.store import MonitorStore
from jarvis.monitoring.worker import MonitorWorker


def start() -> MonitorWorker:
    root = config.base_dir() / "data"
    sources = PersistentSourceRegistry(root / "monitor_sources.sqlite")
    jobs = MonitorJobRegistry(root / "monitor_jobs.sqlite", sources)
    store = MonitorStore(root / "monitor_items.sqlite")
    scheduler = MonitorScheduler(store=store)
    delivery = MonitorDeliveryCoordinator(scheduler=scheduler, store=store)
    # Construction is side-effect-free; main.launch() owns the single start/thread boundary.
    return MonitorWorker(jobs=jobs, scheduler=scheduler, delivery=delivery)


__all__ = ["start"]
