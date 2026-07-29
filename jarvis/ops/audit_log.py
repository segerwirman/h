"""Persistent immutable, redacted audit metadata for local operations."""
from __future__ import annotations

import hashlib
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AuditEvent:
    at: int
    role: str
    action: str
    actor_hash: str

    def safe_dict(self) -> dict:
        return {
            "at": self.at,
            "role": self.role,
            "action": self.action,
            "actor_hash": self.actor_hash,
        }


def create(role: str, action: str, actor_id: str) -> AuditEvent:
    return AuditEvent(
        int(time.time()),
        str(role)[:32],
        str(action)[:64],
        hashlib.sha256(str(actor_id).encode()).hexdigest()[:16],
    )


class AuditLog:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS ops_audit "
                "(at INTEGER, role TEXT, action TEXT, actor_hash TEXT)"
            )

    def _conn(self):
        return sqlite3.connect(self.path)

    def append(self, event: AuditEvent) -> None:
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO ops_audit VALUES (?, ?, ?, ?)",
                (event.at, event.role, event.action, event.actor_hash),
            )

    def recent(self, limit: int) -> list[AuditEvent]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT at, role, action, actor_hash FROM ops_audit "
                "ORDER BY rowid DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [AuditEvent(*row) for row in reversed(rows)]
