"""Durable pairing-first authorization for remote gateway actors."""
from __future__ import annotations

import hashlib
import sqlite3
import time
from pathlib import Path

from jarvis.agent.paths import data_dir


def _hash(value: object) -> str:
    return hashlib.sha256(str(value).encode("utf-8")).hexdigest()[:16]


class GatewayAuthz:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_dir() / "gateway.sqlite"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS gateway_pairs (
                platform TEXT, actor_hash TEXT, state TEXT, paired_at REAL,
                paired_by_hash TEXT, revoked_at REAL, revoked_by_hash TEXT,
                PRIMARY KEY(platform, actor_hash))""")

    def _conn(self):
        return sqlite3.connect(self.path)

    def pair(self, platform: str, actor_id: str, *, paired_by: str = "local-admin") -> bool:
        platform, actor_id = str(platform).strip().lower(), str(actor_id).strip()
        if not platform or not actor_id:
            return False
        now = time.time()
        with self._conn() as conn:
            conn.execute("""INSERT INTO gateway_pairs VALUES (?, ?, 'paired', ?, ?, NULL, NULL)
                ON CONFLICT(platform, actor_hash) DO UPDATE SET state='paired', paired_at=excluded.paired_at,
                paired_by_hash=excluded.paired_by_hash, revoked_at=NULL, revoked_by_hash=NULL""",
                (platform, _hash(actor_id), now, _hash(paired_by)))
        return True

    def allowed(self, platform: str, actor_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute("SELECT state FROM gateway_pairs WHERE platform=? AND actor_hash=?",
                (str(platform).strip().lower(), _hash(actor_id))).fetchone()
        return bool(row and row[0] == "paired")

    def revoke(self, platform: str, actor_id: str, *, revoked_by: str = "local-admin") -> None:
        with self._conn() as conn:
            conn.execute("UPDATE gateway_pairs SET state='revoked', revoked_at=?, revoked_by_hash=? WHERE platform=? AND actor_hash=?",
                (time.time(), _hash(revoked_by), str(platform).strip().lower(), _hash(actor_id)))

    def revoke_hash(self, platform: str, actor_hash: str, *,
                    revoked_by: str = "local-admin") -> bool:
        """Revoke a pair shown by the local UI without recovering its raw actor ID."""
        name = str(platform).strip().lower()
        digest = str(actor_hash).strip().lower()
        if not name or len(digest) != 16 or any(ch not in "0123456789abcdef" for ch in digest):
            return False
        with self._conn() as conn:
            cursor = conn.execute(
                "UPDATE gateway_pairs SET state='revoked', revoked_at=?, revoked_by_hash=? "
                "WHERE platform=? AND actor_hash=? AND state='paired'",
                (time.time(), _hash(revoked_by), name, digest),
            )
        return bool(cursor.rowcount)

    def list_pairs(self) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute("SELECT platform, actor_hash, state, paired_at, revoked_at FROM gateway_pairs ORDER BY paired_at DESC").fetchall()
        return [{"platform": r[0], "actor_hash": r[1], "state": r[2], "paired_at": r[3], "revoked_at": r[4]} for r in rows]

    def paired_count(self, platform: str) -> int:
        """Count active durable pairs without exposing raw actor identities."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT COUNT(*) FROM gateway_pairs WHERE platform=? AND state='paired'",
                (str(platform).strip().lower(),),
            ).fetchone()
        return int(row[0] if row else 0)


AUTHZ = GatewayAuthz()
