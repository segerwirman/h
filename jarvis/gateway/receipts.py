"""Durable, payload-free ingress receipts for replay protection."""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path


class GatewayReceipts:
    def __init__(self, path: Path, *, ttl_seconds: float = 7 * 24 * 3600,
                 max_rows: int = 20_000) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.ttl_seconds = max(60.0, float(ttl_seconds))
        self.max_rows = max(100, int(max_rows))
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("CREATE TABLE IF NOT EXISTS gateway_receipts "
                         "(key_hash TEXT PRIMARY KEY, accepted_at REAL NOT NULL)")

    def _conn(self):
        return sqlite3.connect(self.path, timeout=5)

    @staticmethod
    def _hash(platform: str, message_id: str, conversation_id: str) -> str:
        value = "\x1f".join((str(platform), str(conversation_id), str(message_id)))
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    def accept(self, platform: str, message_id: str, conversation_id: str) -> bool:
        if not all(str(v or "").strip() for v in (platform, message_id, conversation_id)):
            return False
        now = time.time()
        key_hash = self._hash(platform, message_id, conversation_id)
        with self._conn() as conn:
            conn.execute("DELETE FROM gateway_receipts WHERE accepted_at < ?", (now - self.ttl_seconds,))
            cursor = conn.execute("INSERT OR IGNORE INTO gateway_receipts VALUES (?, ?)", (key_hash, now))
            if cursor.rowcount:
                conn.execute("DELETE FROM gateway_receipts WHERE key_hash IN ("
                             "SELECT key_hash FROM gateway_receipts ORDER BY accepted_at ASC "
                             "LIMIT MAX(0, (SELECT COUNT(*) FROM gateway_receipts) - ?))", (self.max_rows,))
                return True
        return False

    def stats(self) -> dict[str, int]:
        with self._conn() as conn:
            row = conn.execute("SELECT COUNT(*) FROM gateway_receipts").fetchone()
        return {"count": int(row[0] if row else 0), "max_rows": self.max_rows}
