"""Relay event store — SQLite persistence + event-id dedup (Fase 5)."""
from __future__ import annotations

import sqlite3
import threading

from jarvis.core import config, log
from jarvis.integrations.relay.models import RelayEvent

_logger = log.get("relay.store")


class RelayStore:
    def __init__(self, db_path=None, max_rows: int = 500):
        self.db_path = str(db_path or config.resolve_path(
            config.get("relay.store_file", "relay_events.sqlite")))
        self.max_rows = max_rows
        self._lock = threading.Lock()
        self._init_db()

    def _connect(self):
        return sqlite3.connect(self.db_path, timeout=5.0)

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS relay_events (
                    event_id    TEXT PRIMARY KEY,
                    kind        TEXT,
                    workflow    TEXT,
                    ts          REAL,
                    received_at REAL,
                    data        TEXT
                )
            """)

    def add(self, event: RelayEvent) -> bool:
        """Insert; returns False when the event_id already exists (duplicate)."""
        with self._lock, self._connect() as conn:
            try:
                conn.execute(
                    "INSERT INTO relay_events "
                    "(event_id, kind, workflow, ts, received_at, data) "
                    "VALUES (?, ?, ?, ?, ?, ?)", event.to_row())
            except sqlite3.IntegrityError:
                return False
            # bounded table: keep the newest max_rows
            conn.execute(
                "DELETE FROM relay_events WHERE event_id NOT IN "
                "(SELECT event_id FROM relay_events "
                " ORDER BY received_at DESC LIMIT ?)", (self.max_rows,))
        return True

    def recent(self, limit: int = 10, kind: str | None = None) -> list[RelayEvent]:
        q = ("SELECT event_id, kind, workflow, ts, received_at, data "
             "FROM relay_events ")
        args: tuple = ()
        if kind:
            q += "WHERE kind = ? "
            args = (kind,)
        q += "ORDER BY received_at DESC LIMIT ?"
        with self._lock, self._connect() as conn:
            rows = conn.execute(q, args + (int(limit),)).fetchall()
        return [RelayEvent.from_row(r) for r in rows]

    def by_workflow(self, workflow: str, limit: int = 5) -> list[RelayEvent]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT event_id, kind, workflow, ts, received_at, data "
                "FROM relay_events WHERE workflow = ? "
                "ORDER BY received_at DESC LIMIT ?",
                (workflow, int(limit))).fetchall()
        return [RelayEvent.from_row(r) for r in rows]

    def workflows(self) -> list[str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT workflow FROM relay_events "
                "WHERE workflow != '' ORDER BY workflow").fetchall()
        return [r[0] for r in rows]

    def count(self) -> int:
        with self._lock, self._connect() as conn:
            return conn.execute("SELECT COUNT(*) FROM relay_events").fetchone()[0]
