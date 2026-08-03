"""Desktop-local persistent registrations and safe monitor-job metadata."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from jarvis.monitoring.delivery import delivery_allowed
from jarvis.monitoring.scheduler import _next
from jarvis.monitoring.source_registry_store import PersistentSourceRegistry

_SAFE_STATUSES = frozenset({"not_started", "ok", "source_failed"})


@dataclass(frozen=True)
class MonitorJob:
    id: str
    source_id: str
    source: str
    schedule: str
    delivery_mode: str
    enabled: bool
    last_status: str = "not_started"
    last_status_at: float | None = None

    def public_dict(self) -> dict:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "source": self.source,
            "schedule": self.schedule,
            "delivery_mode": self.delivery_mode,
            "enabled": self.enabled,
            "last_status": self.last_status,
            "last_status_at": self.last_status_at,
        }


class MonitorJobRegistry:
    """Local metadata registry; it cannot execute arbitrary scheduled work."""

    def __init__(self, path: Path, sources: PersistentSourceRegistry):
        self.path = Path(path)
        self.sources = sources
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self):
        return sqlite3.connect(self.path)

    def _init(self) -> None:
        conn = self._conn()
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS monitor_jobs "
                "(id TEXT PRIMARY KEY, source_id TEXT, source TEXT, schedule TEXT, "
                "delivery_mode TEXT, enabled INTEGER, last_status TEXT, last_status_at REAL)"
            )
            columns = {row[1] for row in conn.execute("PRAGMA table_info(monitor_jobs)")}
            if "last_status" not in columns:
                conn.execute("ALTER TABLE monitor_jobs ADD COLUMN last_status TEXT")
            if "last_status_at" not in columns:
                conn.execute("ALTER TABLE monitor_jobs ADD COLUMN last_status_at REAL")
            conn.execute("UPDATE monitor_jobs SET last_status='not_started' WHERE last_status IS NULL")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _job(row) -> MonitorJob:
        status = str(row[6]) if row[6] in _SAFE_STATUSES else "not_started"
        timestamp = float(row[7]) if isinstance(row[7], (int, float)) else None
        return MonitorJob(str(row[0]), str(row[1]), str(row[2]), str(row[3]), str(row[4]), bool(row[5]), status, timestamp)

    def register_selected(self, schedule, delivery_mode):
        source = self.sources.selected()
        if source is None:
            raise ValueError("selected source required")
        _next(str(schedule), 0.0)
        if not delivery_allowed(delivery_mode):
            raise ValueError("monitor delivery mode rejected")
        job = MonitorJob(uuid.uuid4().hex[:16], source.id, source.name, str(schedule), str(delivery_mode), True)
        conn = self._conn()
        try:
            conn.execute(
                "INSERT INTO monitor_jobs "
                "(id,source_id,source,schedule,delivery_mode,enabled,last_status,last_status_at) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (job.id, job.source_id, job.source, job.schedule, job.delivery_mode, 1, job.last_status, None),
            )
            conn.commit()
        finally:
            conn.close()
        return job

    def list(self) -> list[MonitorJob]:
        conn = self._conn()
        try:
            rows = conn.execute(
                "SELECT id,source_id,source,schedule,delivery_mode,enabled,last_status,last_status_at "
                "FROM monitor_jobs ORDER BY rowid"
            ).fetchall()
            return [self._job(row) for row in rows]
        finally:
            conn.close()

    def _get(self, job_id: str) -> MonitorJob:
        conn = self._conn()
        try:
            row = conn.execute(
                "SELECT id,source_id,source,schedule,delivery_mode,enabled,last_status,last_status_at "
                "FROM monitor_jobs WHERE id=?", (str(job_id),)
            ).fetchone()
            if row is None:
                raise ValueError("monitor job tidak ditemukan")
            return self._job(row)
        finally:
            conn.close()

    def set_enabled(self, job_id: str, enabled: bool) -> MonitorJob:
        if not isinstance(enabled, bool):
            raise ValueError("monitor job enabled harus boolean")
        self._get(job_id)
        conn = self._conn()
        try:
            conn.execute("UPDATE monitor_jobs SET enabled=? WHERE id=?", (int(enabled), str(job_id)))
            conn.commit()
        finally:
            conn.close()
        return self._get(job_id)

    def record_safe_status(self, job_id: str, status: str, timestamp: float) -> MonitorJob:
        if status not in _SAFE_STATUSES or status == "not_started":
            raise ValueError("monitor safe status rejected")
        if not isinstance(timestamp, (int, float)):
            raise ValueError("monitor safe status timestamp rejected")
        self._get(job_id)
        conn = self._conn()
        try:
            conn.execute(
                "UPDATE monitor_jobs SET last_status=?,last_status_at=? WHERE id=?",
                (status, float(timestamp), str(job_id)),
            )
            conn.commit()
        finally:
            conn.close()
        return self._get(job_id)

    def install_into(self, scheduler):
        out = []
        for job in self.list():
            if not job.enabled:
                continue
            source = self.sources.get(job.source_id)
            if source is None:
                continue
            runtime = scheduler.create_monitor_job(source.monitor_source(), job.schedule)
            out.append({"persisted_id": job.id, "runtime_job_id": runtime["id"], "delivery_mode": job.delivery_mode})
        return out


__all__ = ["MonitorJob", "MonitorJobRegistry"]
