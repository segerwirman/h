"""Durable task lifecycle ledger + recovery classification (Fase 38).

A task that dies mid-flight must never be silently replayed or claimed safe.
This module persists lifecycle transitions transactionally in ``agent.sqlite``
and reconciles non-terminal records of a prior process incarnation into
explicit recovery dispositions that the Task Deck surfaces as non-active
records — never as running workers, never auto-replayed.

Privacy boundary: the ledger stores only a safe title/summary, source,
owner-scope, state, safe step, and an optional pending tool NAME.  It NEVER
stores raw tool arguments, secrets, actor IDs, or raw tool results.
"""
from __future__ import annotations

import dataclasses
import os
import sqlite3
import threading
import time
from enum import Enum
from pathlib import Path

from jarvis.core import log
from jarvis.agent.paths import db_path

_logger = log.get("agent.task_ledger")


def process_incarnation() -> str:
    """Process-unique incarnation id for ledger rows.

    Boot time + pid distinguishes one Jarvis process from the next even when
    the pid is reused.  This is the boundary that separates a *live* task from
    a stale prior-incarnation record during boot reconciliation.
    """
    return f"{os.getpid()}-{int(time.time())}"


_DDL = """
CREATE TABLE IF NOT EXISTS task_records (
    task_id TEXT PRIMARY KEY,
    incarnation TEXT NOT NULL,
    title TEXT NOT NULL,
    source TEXT NOT NULL DEFAULT 'agent',
    owner_scope TEXT NOT NULL DEFAULT '',
    state TEXT NOT NULL,
    step TEXT NOT NULL DEFAULT '',
    pending_tool TEXT NOT NULL DEFAULT '',
    pending_read_only INTEGER,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
)
"""


class RecoveryDisposition(str, Enum):
    """How a prior-incarnation non-terminal task may be resumed.

    ``str`` base keeps each member equal to its raw value, so membership tests
    against string sets (``status in dispositions()``, ``status not in
    ACTIVE_STATES``) behave the way callers expect.
    """

    RECOVERABLE = "recoverable"          # checkpoint contract verified
    INTERRUPTED = "interrupted"          # no verified checkpoint; explicit restart
    OUTCOME_UNCERTAIN = "outcome_uncertain"  # pending non-read-only side effect

    @classmethod
    def dispositions(cls) -> frozenset[str]:
        return frozenset(item.value for item in cls)


class RecoveryAction(str, Enum):
    CONTINUE = "continue"
    RESTART = "restart"
    ASK_INSTRUCTION = "ask_instruction"
    INSPECT = "inspect"


@dataclasses.dataclass(frozen=True)
class LedgerView:
    """Immutable ledger row safe to cross threads."""

    task_id: str
    incarnation: str
    title: str
    source: str
    owner_scope: str
    state: str
    step: str
    pending_tool: str
    pending_read_only: bool | None
    created_at: float
    updated_at: float

    @property
    def recovery(self) -> RecoveryDisposition | None:
        return (
            RecoveryDisposition(self.state)
            if self.state in RecoveryDisposition.dispositions()
            else None
        )

    @property
    def recovery_action(self) -> str:
        """Safe, disposition-appropriate action label.

        Never offers generic replay for an unknown-outcome side effect; only
        ``inspect`` is safe there.
        """
        disposition = self.recovery
        if disposition is RecoveryDisposition.OUTCOME_UNCERTAIN:
            return RecoveryAction.INSPECT.value
        if disposition is RecoveryDisposition.RECOVERABLE:
            return RecoveryAction.CONTINUE.value
        if disposition is RecoveryDisposition.INTERRUPTED:
            return RecoveryAction.ASK_INSTRUCTION.value
        return RecoveryAction.ASK_INSTRUCTION.value


class TaskLedger:
    """Thread-safe SQLite ledger. Reopening the same path sees the same rows."""

    def __init__(self, path: Path | None = None):
        self.path = Path(path or db_path())
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._conn() as conn:
            conn.execute(_DDL)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        return conn

    # ── lifecycle writes ────────────────────────────────────────────────────

    def create(self, task_id: str, *, title: str, source: str = "agent",
               conversation: str = "", incarnation: str = "") -> LedgerView:
        now = time.time()
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO task_records VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (str(task_id)[:64], str(incarnation or "")[:40],
                     str(title or "")[:200], str(source or "agent")[:32],
                     str(conversation or "")[:64], "queued", "", "", None,
                     now, now),
                )
        return self.get(task_id)

    def mark(self, task_id: str, *, state: str,
             incarnation: str, step: str = "") -> LedgerView | None:
        return self._update(task_id, state=state, step=step,
                            incarnation=incarnation)

    def finish(self, task_id: str, *, ok: bool, result: str,
               incarnation: str) -> LedgerView | None:
        state = "done" if ok else "failed"
        return self._update(task_id, state=state,
                            incarnation=incarnation)

    def mark_pending_tool(self, task_id: str, *, tool: str,
                          read_only: bool | None,
                          incarnation: str) -> LedgerView | None:
        """Record the pending tool NAME (never its arguments) right before a
        registry execute. ``tool=""`` / ``read_only=None`` clears the marker."""
        return self._update(
            task_id, pending_tool=str(tool or "")[:64],
            pending_read_only=None if read_only is None else bool(read_only),
            incarnation=incarnation)

    def _update(self, task_id: str, *, incarnation: str,
                state: str | None = None, step: str | None = None,
                pending_tool: str | None = None,
                pending_read_only: bool | None = None) -> LedgerView | None:
        if not task_id:
            return None
        now = time.time()
        sets = ["updated_at = ?"]
        params: list = [now]
        if state is not None:
            sets.append("state = ?")
            params.append(str(state)[:32])
        if step is not None:
            step_value = str(step)
            if state == "waiting":
                # WAITING persists a classification code, never human-entered
                # text, semantic references, tool arguments, or CAPTCHA data.
                from jarvis.agent.tasks import _WAIT_REASON_CODES
                if step_value not in _WAIT_REASON_CODES:
                    step_value = "waiting"
            sets.append("step = ?")
            params.append(step_value[:240])
        if pending_tool is not None:
            sets.append("pending_tool = ?")
            params.append(str(pending_tool)[:64])
        if pending_read_only is not None:
            sets.append("pending_read_only = ?")
            params.append(int(bool(pending_read_only)))
        params.append(str(task_id)[:64])
        params.append(str(incarnation or "")[:40])
        with self._lock:
            with self._conn() as conn:
                conn.execute(
                    f"UPDATE task_records SET {', '.join(sets)} "
                    "WHERE task_id = ? AND incarnation = ?",
                    (*params,),
                )
        return self.get(task_id)

    # ── reads ───────────────────────────────────────────────────────────────

    def get(self, task_id: str) -> LedgerView | None:
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT * FROM task_records WHERE task_id = ?",
                    (str(task_id)[:64],),
                ).fetchone()
        return _row_to_view(row)

    def all_records(self) -> list[LedgerView]:
        with self._lock:
            with self._conn() as conn:
                rows = conn.execute(
                    "SELECT * FROM task_records ORDER BY updated_at").fetchall()
        return [_row_to_view(row) for row in rows]

    def active_count(self) -> int:
        """Active (queued/running/waiting) records in the CURRENT incarnation.

        Recovery dispositions are never active, so a reconciled prior-incarnation
        record never contributes to this count.
        """
        with self._lock:
            with self._conn() as conn:
                row = conn.execute(
                    "SELECT COUNT(*) AS n FROM task_records "
                    "WHERE state IN ('queued', 'running', 'waiting')",
                ).fetchone()
        return int(row["n"]) if row else 0

    def clear_all(self) -> None:
        with self._lock:
            with self._conn() as conn:
                conn.execute("DELETE FROM task_records")

    # ── recovery ────────────────────────────────────────────────────────────

    def reconcile(self, *, active_incarnation: str) -> list[LedgerView]:
        """Classify prior-incarnation non-terminal records into dispositions.

        Returns the recovery views.  Nothing is executed or queued here; boot
        hydration is visual/log-first (Fase 38 item 7/8).
        """
        rows = self.all_records()
        recovered: list[LedgerView] = []
        now = time.time()
        with self._lock:
            with self._conn() as conn:
                for row in rows:
                    if row.incarnation == active_incarnation:
                        continue                       # live process, not stale
                    if row.state in ("done", "failed", "cancelled"):
                        continue                       # terminal, no recovery
                    disposition = _classify(row)
                    recovered.append(_with_state(row, disposition, now))
                    conn.execute(
                        "UPDATE task_records SET state = ?, updated_at = ? "
                        "WHERE task_id = ?",
                        (disposition, now, row.task_id),
                    )
        return recovered

    def recovery_views(self) -> list[LedgerView]:
        """Recovery-disposition records currently in the ledger (read-only)."""
        return [row for row in self.all_records()
                if row.state in RecoveryDisposition.dispositions()]


def _classify(row: LedgerView) -> str:
    """Deterministic disposition for one stale non-terminal record."""
    if row.pending_tool and row.pending_read_only is False:
        # A non-read-only side effect was in flight when the process died:
        # its outcome is unknown.  Never offer generic replay.
        return RecoveryDisposition.OUTCOME_UNCERTAIN.value
    if row.state == "running" or row.state == "waiting":
        # Work was in progress with no verified checkpoint.
        return RecoveryDisposition.INTERRUPTED.value
    return RecoveryDisposition.RECOVERABLE.value


def _with_state(row: LedgerView, state: str, now: float) -> LedgerView:
    return dataclasses.replace(row, state=state, updated_at=now)


def _row_to_view(row) -> LedgerView | None:
    if row is None:
        return None
    return LedgerView(
        task_id=row["task_id"],
        incarnation=row["incarnation"],
        title=row["title"],
        source=row["source"],
        owner_scope=row["owner_scope"],
        state=row["state"],
        step=row["step"],
        pending_tool=row["pending_tool"],
        pending_read_only=None if row["pending_read_only"] is None
        else bool(row["pending_read_only"]),
        created_at=row["created_at"],
        updated_at=row["updated_at"],
    )


LEDGER = TaskLedger()


__all__ = [
    "LEDGER",
    "LedgerView",
    "RecoveryAction",
    "RecoveryDisposition",
    "TaskLedger",
]
