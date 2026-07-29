"""Scoped, redacted session excerpts for continuity and local audit search."""
from __future__ import annotations

import re
import sqlite3
import time
import uuid
from pathlib import Path

from jarvis.agent.memory_policy import can_access, owner_for

_SECRET = re.compile(
    r"(?i)\b(token|api[_-]?key|password|secret)\s*=\s*[^\s,;]+"
)


def redact(text: object) -> str:
    return _SECRET.sub(lambda match: f"{match.group(1)}=[REDACTED]", str(text or ""))


class SessionStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS session_excerpts (
                id TEXT PRIMARY KEY, source TEXT, actor_id TEXT, scope TEXT,
                owner TEXT, excerpt TEXT, created_at INTEGER)""")
            try:
                conn.execute("CREATE VIRTUAL TABLE IF NOT EXISTS session_excerpts_fts "
                             "USING fts5(excerpt, content=session_excerpts, content_rowid=rowid)")
                conn.execute("""CREATE TRIGGER IF NOT EXISTS session_excerpts_ai
                    AFTER INSERT ON session_excerpts BEGIN
                    INSERT INTO session_excerpts_fts(rowid, excerpt)
                    VALUES (new.rowid, new.excerpt); END""")
            except sqlite3.OperationalError:
                pass

    def _conn(self) -> sqlite3.Connection:
        return sqlite3.connect(self.path)

    def record(self, source: str, actor_id: str, excerpt: str, *,
               scope: str = "platform-actor", owner: str = "") -> str:
        source, actor_id = str(source), str(actor_id)
        actual_owner = str(owner) or owner_for(scope=scope, source=source, actor_id=actor_id)
        item_id = uuid.uuid4().hex[:16]
        with self._conn() as conn:
            conn.execute("INSERT INTO session_excerpts VALUES (?, ?, ?, ?, ?, ?, ?)",
                         (item_id, source[:32], actor_id[:96], scope, actual_owner[:160],
                          redact(excerpt)[:1200], int(time.time())))
        return item_id

    def search(self, query: str, *, source: str, actor_id: str, limit: int = 12) -> list[dict]:
        safe_query = str(query or "").strip()
        if not safe_query:
            return []
        with self._conn() as conn:
            try:
                rows = conn.execute(
                    "SELECT s.id, s.source, s.scope, s.owner, s.excerpt FROM session_excerpts s "
                    "JOIN session_excerpts_fts f ON f.rowid = s.rowid "
                    "WHERE f.excerpt MATCH ? ORDER BY s.created_at DESC LIMIT ?",
                    (" ".join(f'\"{part}\"' for part in safe_query.split()), max(1, min(limit, 50))),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = conn.execute(
                    "SELECT id, source, scope, owner, excerpt FROM session_excerpts "
                    "WHERE excerpt LIKE ? ORDER BY created_at DESC LIMIT ?",
                    (f"%{safe_query}%", max(1, min(limit, 50))),
                ).fetchall()
        return [
            {"id": row[0], "source": row[1], "scope": row[2], "excerpt": row[4]}
            for row in rows
            if can_access(scope=row[2], owner=row[3], source=str(source),
                          actor_id=str(actor_id), operation="read")
        ]
