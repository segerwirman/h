"""Persisted, payload-free approval state for high-risk capabilities."""
from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ApprovalRequest:
    id: str
    trace_hash: str
    capability: str
    reason: str
    state: str
    created_at: float
    resolved_at: float | None = None

    def safe_dict(self) -> dict:
        return {
            "id": self.id, "trace_hash": self.trace_hash,
            "capability": self.capability, "reason": self.reason,
            "state": self.state, "created_at": self.created_at,
            "resolved_at": self.resolved_at,
        }


class ApprovalStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS approvals (
                id TEXT PRIMARY KEY, trace_hash TEXT, capability TEXT, reason TEXT,
                state TEXT, created_at REAL, resolved_at REAL)""")

    def _conn(self):
        return sqlite3.connect(self.path)

    def request(self, trace_id: str, capability: str, reason: str) -> ApprovalRequest:
        item = ApprovalRequest(uuid.uuid4().hex[:16],
            hashlib.sha256(str(trace_id).encode()).hexdigest()[:16],
            str(capability), str(reason), "pending", time.time())
        with self._conn() as conn:
            conn.execute("INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (item.id, item.trace_hash, item.capability, item.reason,
                          item.state, item.created_at, item.resolved_at))
        return item

    def get(self, request_id: str) -> ApprovalRequest | None:
        with self._conn() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE id = ?", (request_id,)).fetchone()
        return ApprovalRequest(*row) if row else None

    def pending(self, limit: int = 100) -> list[ApprovalRequest]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM approvals WHERE state='pending' ORDER BY created_at ASC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
        return [ApprovalRequest(*row) for row in rows]

    def approved_for(self, request_id: str, trace_id: str, capability: str) -> bool:
        """Bind a durable approval to the original trace and capability."""
        item = self.get(request_id)
        trace_hash = hashlib.sha256(str(trace_id).encode()).hexdigest()[:16]
        return bool(item and item.state == "approved"
                    and item.trace_hash == trace_hash
                    and item.capability == str(capability))

    def resolve(self, request_id: str, *, approved: bool) -> ApprovalRequest:
        existing = self.get(request_id)
        if existing is None:
            raise KeyError(request_id)
        if existing.state != "pending":
            return existing
        state, resolved_at = ("approved" if approved else "denied"), time.time()
        with self._conn() as conn:
            conn.execute("UPDATE approvals SET state = ?, resolved_at = ? WHERE id = ? AND state='pending'",
                         (state, resolved_at, request_id))
        item = self.get(request_id)
        return item or existing
