"""Monitor-only worker lifecycle with persisted safe job status metadata."""
from __future__ import annotations

import threading
import time


class MonitorWorker:
    def __init__(self, *, jobs, scheduler, delivery, interval_s=30.0, now=time.time):
        self.jobs = jobs
        self.scheduler = scheduler
        self.delivery = delivery
        self.interval = max(5.0, float(interval_s))
        self._now = now
        self._stop = threading.Event()
        self._started = False
        self._lock = threading.Lock()
        self._thread = None
        self._last_tick_at = None
        self._last_delivery_count = 0
        self._last_status = "not_started"
        self._installed_job_ids: list[str] = []

    def start(self):
        with self._lock:
            if self._started:
                return False
            self._started = True
            for job in self.jobs.list():
                if not getattr(job, "enabled", False):
                    continue
                source = self.jobs.sources.get(job.source_id)
                if source is None:
                    continue
                runtime = self.scheduler.create_monitor_job(source.monitor_source(), job.schedule)
                self.delivery.bind_job(runtime, job.delivery_mode)
                self._installed_job_ids.append(job.id)
            return True

    def _record_status(self, status: str, timestamp: float) -> None:
        record = getattr(self.jobs, "record_safe_status", None)
        if not callable(record):
            return
        for job_id in self._installed_job_ids:
            try:
                record(job_id, status, timestamp)
            except (TypeError, ValueError):
                continue

    def tick_once(self):
        if not self._started:
            return []
        self._last_tick_at = float(self._now())
        try:
            results = self.delivery.run_due()
            self._last_delivery_count = len(results)
            self._last_status = "ok"
            self._record_status("ok", self._last_tick_at)
            return results
        except Exception:
            self._last_delivery_count = 0
            self._last_status = "source_failed"
            self._record_status("source_failed", self._last_tick_at)
            return []

    def status(self):
        return {
            "running": self._started and not self._stop.is_set(),
            "last_tick_at": self._last_tick_at,
            "last_delivery_count": self._last_delivery_count,
            "last_status": self._last_status,
        }

    def run_forever(self):
        while not self._stop.wait(self.interval):
            self.tick_once()

    def launch(self):
        if not self.start():
            return False
        self._thread = threading.Thread(target=self.run_forever, name="monitor-worker", daemon=False)
        self._thread.start()
        return True

    def stop(self):
        self._stop.set()
        thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=self.interval + 1.0)

    @property
    def thread(self):
        return self._thread


__all__ = ["MonitorWorker"]
