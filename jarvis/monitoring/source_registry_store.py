"""17E: persistent metadata-only registry for validated public monitor sources."""
from __future__ import annotations

import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path

from jarvis.monitoring.sources import MonitorSource


@dataclass(frozen=True)
class PersistedSource:
    id: str
    name: str
    url: str
    mode: str
    rate_limit_s: int

    @classmethod
    def from_monitor(cls, source_id: str, source: MonitorSource) -> "PersistedSource":
        return cls(source_id, source.name, source.url, source.mode, source.rate_limit_s)

    def monitor_source(self) -> MonitorSource:
        return MonitorSource.create(self.name, self.url, self.mode, rate_limit_s=self.rate_limit_s)

    def public_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "url": self.url,
                "mode": self.mode, "rate_limit_s": self.rate_limit_s}


class PersistentSourceRegistry:
    """Small SQLite registry; only validated source metadata and selection persist."""

    def __init__(self, path: Path, *, max_sources: int = 50) -> None:
        self.path = Path(path)
        self.max_sources = max(1, min(int(max_sources), 100))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init()

    def _conn(self):
        return sqlite3.connect(self.path)

    def _init(self) -> None:
        conn = self._conn()
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, name TEXT, url TEXT UNIQUE, mode TEXT, rate_limit_s INTEGER)")
            conn.execute("CREATE TABLE IF NOT EXISTS selection (singleton INTEGER PRIMARY KEY CHECK(singleton=1), source_id TEXT)")
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _row(row) -> PersistedSource:
        candidate = PersistedSource(str(row[0]), str(row[1]), str(row[2]), str(row[3]), int(row[4]))
        # Re-validate persisted state; manually altered DB rows cannot bypass 17A policy.
        safe = candidate.monitor_source()
        return PersistedSource.from_monitor(candidate.id, safe)

    def add(self, name: str, url: str, mode: str, *, rate_limit_s: int) -> PersistedSource:
        source = MonitorSource.create(name, url, mode, rate_limit_s=rate_limit_s)
        conn = self._conn()
        try:
            if conn.execute("SELECT 1 FROM sources WHERE url=?", (source.url,)).fetchone():
                raise ValueError("source URL sudah terdaftar")
            if conn.execute("SELECT COUNT(*) FROM sources").fetchone()[0] >= self.max_sources:
                raise ValueError("batas source registry tercapai")
            item = PersistedSource.from_monitor(uuid.uuid4().hex[:16], source)
            conn.execute("INSERT INTO sources VALUES (?,?,?,?,?)", (item.id, item.name, item.url, item.mode, item.rate_limit_s))
            conn.commit()
            return item
        finally:
            conn.close()

    def list(self) -> list[PersistedSource]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT id,name,url,mode,rate_limit_s FROM sources ORDER BY name COLLATE NOCASE").fetchall()
            return [self._row(row) for row in rows]
        finally:
            conn.close()

    def get(self, source_id: str) -> PersistedSource | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT id,name,url,mode,rate_limit_s FROM sources WHERE id=?", (str(source_id),)).fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def select(self, source_id: str) -> PersistedSource:
        item = self.get(source_id)
        if item is None:
            raise ValueError("selected source tidak ditemukan")
        conn = self._conn()
        try:
            conn.execute("INSERT INTO selection(singleton,source_id) VALUES(1,?) ON CONFLICT(singleton) DO UPDATE SET source_id=excluded.source_id", (item.id,))
            conn.commit()
            return item
        finally:
            conn.close()

    def selected(self) -> PersistedSource | None:
        conn = self._conn()
        try:
            row = conn.execute("SELECT s.id,s.name,s.url,s.mode,s.rate_limit_s FROM selection x JOIN sources s ON s.id=x.source_id WHERE x.singleton=1").fetchone()
            return self._row(row) if row else None
        finally:
            conn.close()

    def clear_selection(self) -> None:
        conn = self._conn()
        try:
            conn.execute("DELETE FROM selection WHERE singleton=1")
            conn.commit()
        finally:
            conn.close()

    def public_view(self) -> list[dict]:
        return [item.public_dict() for item in self.list()]


__all__ = ["PersistedSource", "PersistentSourceRegistry"]
