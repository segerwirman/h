"""Sesi agent — state satu tugas + arsip percakapan untuk ``session_search``.

Arsip: tabel ``agent_sessions`` + FTS5 di ``data/agent.sqlite``. Ringan:
insert per turn, tanpa ORM, tanpa server.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass, field

from jarvis.core import log
from jarvis.agent.paths import db_path

_logger = log.get("agent.session")
_db_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(db_path())
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _db_lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS agent_sessions (
                id TEXT PRIMARY KEY,
                adapter TEXT,
                task TEXT,
                started_at REAL,
                ended_at REAL,
                turn_count INTEGER DEFAULT 0,
                result TEXT,
                ok INTEGER DEFAULT 1
            )""")
        c.execute("""
            CREATE TABLE IF NOT EXISTS agent_turns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id TEXT,
                ts REAL,
                role TEXT,
                content TEXT
            )""")
        try:
            c.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS agent_turns_fts
                USING fts5(content, content=agent_turns, content_rowid=id)
            """)
            c.execute("""
                CREATE TRIGGER IF NOT EXISTS agent_turns_ai
                AFTER INSERT ON agent_turns BEGIN
                    INSERT INTO agent_turns_fts(rowid, content)
                    VALUES (new.id, new.content);
                END""")
        except sqlite3.OperationalError:
            pass                                  # build tanpa FTS5 → LIKE


@dataclass
class Session:
    task: str = ""
    adapter_name: str = "ui"
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    started_at: float = field(default_factory=time.time)
    cancelled: bool = False
    is_subagent: bool = False
    turn_count: int = 0
    tool_calls: list[dict] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    transcript: list[dict] = field(default_factory=list)
    todos: list[dict] = field(default_factory=list)
    # §17 — permintaan berkonfirmasi yang sudah ditolak user, agar tidak
    # ditanyakan berulang dan menghabiskan iterasi.
    denied_confirmations: set[str] = field(default_factory=set, repr=False)
    execution_context: object | None = field(default=None, repr=False)
    conversation_context: str = field(default="", repr=False)
    # Opaque process-local grant IDs. Never prompt text or secrets.
    execution_grant_id: str = field(default="", repr=False)
    communication_grant_id: str = field(default="", repr=False)
    # Real TaskRegistry identity used only for exact grant verification.
    registry_task_id: str = field(default="", repr=False)
    _persisted: bool = False

    def cancel(self) -> None:
        self.cancelled = True

    # ── perekaman ─────────────────────────────────────────────────────────

    def record_turn(self, role: str, content: str) -> None:
        self.transcript.append({"role": role, "content": content,
                                "ts": time.time()})
        self.turn_count += 1
        if self.is_subagent:
            return                                # sub-agent tidak diarsip
        try:
            self._ensure_row()
            with _db_lock, _conn() as c:
                c.execute("INSERT INTO agent_turns (session_id, ts, role, "
                          "content) VALUES (?, ?, ?, ?)",
                          (self.id, time.time(), role, content[:20_000]))
                c.execute("UPDATE agent_sessions SET turn_count = ? "
                          "WHERE id = ?", (self.turn_count, self.id))
        except Exception as e:                               # noqa: BLE001
            _logger.warning("session.persist_failed", error=str(e)[:100])

    def record_tool(self, name: str, args: dict, res, elapsed_s: float) -> None:
        self.tool_calls.append({
            "tool": name, "ok": res.ok, "error": res.error,
            "elapsed_ms": round(elapsed_s * 1000, 1)})
        if not res.ok and res.error:
            self.errors.append(f"{name}: {res.error}")

    def record_evidence(self, name: str, args: dict, res) -> None:
        """Kanal bukti kontrak — hasil tool UTUH, tidak diarsip (S-12).

        Terpisah dari ``record_tool`` dengan sengaja. ``record_tool`` memberi
        makan transkrip sesi dan telemetry, jadi ``registry`` menyerahkan hasil
        yang sudah diredaksi ke sana — dan itu benar. Tetapi validator kontrak
        membutuhkan isi hasil yang sebenarnya, sehingga membonceng kanal audit
        membuat setiap kontrak menerima ``content=None`` dan tidak pernah bisa
        lolos.

        Default no-op: hanya pemanggil yang benar-benar memvalidasi bukti
        (``dispatch._observe_session``) yang menggantinya, dan datanya hidup di
        memori selama satu run saja — tidak pernah ditulis ke disk atau log.
        """

    def record_plan(self, name: str, args: dict, res) -> None:
        """Kanal rencana — argumen ASLI, hanya di memori (§25).

        ``record_tool`` dan ``record_evidence`` keduanya menerima argumen yang
        sudah diredaksi ``registry._audit_args``, dan itu benar untuk audit.
        Tetapi rencana yang akan DIJALANKAN ULANG besok tidak boleh berisi
        nilai bertopeng, jadi ia butuh kanalnya sendiri.

        Default no-op: hanya ``dispatch`` yang menggantinya, datanya hidup
        selama satu run, dan penyaringan apa yang layak ditulis ke disk ada di
        ``command_plan`` — bukan di sini.
        """

    def finish(self, result: str, ok: bool = True) -> None:
        if self.is_subagent:
            return
        try:
            self._ensure_row()
            with _db_lock, _conn() as c:
                c.execute("UPDATE agent_sessions SET ended_at = ?, "
                          "result = ?, ok = ? WHERE id = ?",
                          (time.time(), result[:4000], int(ok), self.id))
        except Exception as e:                               # noqa: BLE001
            _logger.warning("session.finish_failed", error=str(e)[:100])

    def _ensure_row(self) -> None:
        if self._persisted:
            return
        init_db()
        with _db_lock, _conn() as c:
            c.execute("INSERT OR IGNORE INTO agent_sessions "
                      "(id, adapter, task, started_at) VALUES (?, ?, ?, ?)",
                      (self.id, self.adapter_name, self.task[:2000],
                       self.started_at))
        self._persisted = True


# ── pencarian arsip (tool session_search) ─────────────────────────────────

def search(query: str, limit: int = 8, after: float | None = None,
           before: float | None = None) -> list[dict]:
    init_db()
    rows: list[dict] = []
    try:
        with _db_lock, _conn() as c:
            c.row_factory = sqlite3.Row
            try:
                sql = ("SELECT t.session_id, t.ts, t.role, "
                       "snippet(agent_turns_fts, 0, '[', ']', ' … ', 18) "
                       "AS snip FROM agent_turns_fts f "
                       "JOIN agent_turns t ON t.id = f.rowid "
                       "WHERE agent_turns_fts MATCH ?")
                params: list = [_fts_quote(query)]
                if after:
                    sql += " AND t.ts >= ?"; params.append(after)
                if before:
                    sql += " AND t.ts <= ?"; params.append(before)
                sql += " ORDER BY rank LIMIT ?"; params.append(limit)
                rows = [dict(r) for r in c.execute(sql, params).fetchall()]
            except sqlite3.OperationalError:
                like = f"%{query}%"
                sql = ("SELECT session_id, ts, role, "
                       "substr(content, 1, 240) AS snip FROM agent_turns "
                       "WHERE content LIKE ?")
                params = [like]
                if after:
                    sql += " AND ts >= ?"; params.append(after)
                if before:
                    sql += " AND ts <= ?"; params.append(before)
                sql += " ORDER BY ts DESC LIMIT ?"; params.append(limit)
                rows = [dict(r) for r in c.execute(sql, params).fetchall()]
    except Exception as e:                                   # noqa: BLE001
        # S-41 — dulu di sini ada `return rows` yang kosong, sehingga
        # PENCARIAN GAGAL tidak bisa dibedakan dari TIDAK ADA HASIL. Pemanggil
        # melaporkannya sebagai "tidak ada sesi yang cocok", dan model
        # membacanya sebagai "sudah dicari, memang tidak ada" — padahal
        # pencariannya tidak pernah terjadi.
        _logger.error("session.search_failed", error=str(e)[:120])
        raise
    return rows


def _fts_quote(q: str) -> str:
    """Kueri user bebas → FTS5 aman (setiap token dikutip)."""
    toks = [t.replace('"', '""') for t in q.split() if t.strip()]
    return " ".join(f'"{t}"' for t in toks) or '""'


def recent_sessions(limit: int = 10) -> list[dict]:
    init_db()
    with _db_lock, _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT * FROM agent_sessions ORDER BY started_at DESC LIMIT ?",
            (limit,)).fetchall()
        return [dict(r) for r in rows]
