"""SQLite-backed, bounded lifecycle trace for durable Jarvis jobs."""
from __future__ import annotations

import hashlib
import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class JobRun:
    id: str
    job_id: str
    trace_hash: str
    state: str
    started_at: float
    ended_at: float | None = None
    result: str = ""

    def safe_dict(self) -> dict:
        return {
            "id": self.id,
            "job_id": self.job_id,
            "trace_hash": self.trace_hash,
            "state": self.state,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "result": self.result,
        }


class JobStore:
    def __init__(self, path: Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._conn() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS job_runs (
                id TEXT PRIMARY KEY, job_id TEXT, trace_hash TEXT, state TEXT,
                started_at REAL, ended_at REAL, result TEXT)""")

    def _conn(self):
        return sqlite3.connect(self.path)

    def start(self, job_id: str, trace_id: str) -> JobRun:
        with self._conn() as conn:
            active = conn.execute(
                "SELECT 1 FROM job_runs WHERE job_id = ? AND state = 'running'",
                (job_id,),
            ).fetchone()
            if active:
                raise RuntimeError("job_already_running")
            item = JobRun(
                uuid.uuid4().hex[:16],
                str(job_id),
                hashlib.sha256(str(trace_id).encode()).hexdigest()[:16],
                "running",
                time.time(),
            )
            conn.execute(
                "INSERT INTO job_runs VALUES (?, ?, ?, ?, ?, ?, ?)",
                (item.id, item.job_id, item.trace_hash, item.state,
                 item.started_at, item.ended_at, item.result),
            )
        return item

    def finish(self, run_id: str, *, ok: bool, result: str) -> JobRun:
        state = "completed" if ok else "failed"
        ended_at = time.time()
        bounded = str(result or "")[:2000]
        with self._conn() as conn:
            conn.execute(
                "UPDATE job_runs SET state = ?, ended_at = ?, result = ? WHERE id = ?",
                (state, ended_at, bounded, run_id),
            )
            row = conn.execute("SELECT * FROM job_runs WHERE id = ?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return JobRun(*row)
