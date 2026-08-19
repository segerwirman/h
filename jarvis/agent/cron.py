"""Cron jobs (§3.1.L) — croniter + SQLite persist; job = sesi agent otonom.

Job berjalan TANPA clarify (NullAdapter, interactive=False). Hasil dikirim ke
Telegram bila adapter Telegram aktif. Scheduler = satu thread tick 20 s.
Konsolidasi memori mingguan didaftarkan sebagai job internal.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid

from jarvis.core import config, log
from jarvis.agent.paths import db_path

_logger = log.get("agent.cron")
_lock = threading.Lock()

_INTERNAL_CONSOLIDATE = "internal-memory-consolidate"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(db_path())
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS cron_jobs (
                id TEXT PRIMARY KEY,
                name TEXT UNIQUE,
                schedule TEXT NOT NULL,
                task TEXT NOT NULL,
                skills TEXT DEFAULT '[]',
                enabled INTEGER DEFAULT 1,
                internal INTEGER DEFAULT 0,
                created_at REAL,
                last_run REAL,
                next_run REAL,
                last_result TEXT,
                run_count INTEGER DEFAULT 0
            )""")


def _next_run(schedule: str, base: float | None = None) -> float | None:
    try:
        from croniter import croniter
        # basis float (epoch), BUKAN datetime naive — croniter 6 menafsirkan
        # datetime naive sebagai UTC sehingga next_run meleset sebesar offset
        # timezone (terbukti +7 jam di WIB)
        it = croniter(schedule, base or time.time())
        return it.get_next(float)
    except Exception as e:                                   # noqa: BLE001
        _logger.error("cron.bad_schedule", schedule=schedule,
                      error=str(e)[:80])
        return None


# ── CRUD ──────────────────────────────────────────────────────────────────

def create(name: str, schedule: str, task: str,
           skills: list[str] | None = None, enabled: bool = True,
           internal: bool = False) -> tuple[bool, str]:
    init_db()
    nxt = _next_run(schedule)
    if nxt is None:
        return False, f"cron expression tidak valid: {schedule}"
    jid = uuid.uuid4().hex[:10]
    try:
        with _lock, _conn() as c:
            c.execute(
                "INSERT INTO cron_jobs (id, name, schedule, task, skills, "
                "enabled, internal, created_at, next_run) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (jid, name, schedule, task,
                 json.dumps(skills or [], ensure_ascii=False),
                 int(enabled), int(internal), time.time(), nxt))
    except sqlite3.IntegrityError:
        return False, f"job bernama '{name}' sudah ada"
    _logger.info("cron.created", id=jid, name=name, schedule=schedule)
    return True, jid


def list_jobs(include_internal: bool = True) -> list[dict]:
    init_db()
    with _lock, _conn() as c:
        c.row_factory = sqlite3.Row
        q = "SELECT * FROM cron_jobs"
        if not include_internal:
            q += " WHERE internal = 0"
        rows = [dict(r) for r in c.execute(q + " ORDER BY created_at")]
    for r in rows:
        r["skills"] = json.loads(r.get("skills") or "[]")
    return rows


def get_job(job_id: str) -> dict | None:
    init_db()
    with _lock, _conn() as c:
        c.row_factory = sqlite3.Row
        r = c.execute("SELECT * FROM cron_jobs WHERE id = ? OR name = ?",
                      (job_id, job_id)).fetchone()
        return dict(r) if r else None


def update(job_id: str, **fields) -> bool:
    allowed = {"name", "schedule", "task", "enabled", "skills"}
    sets, params = [], []
    for k, v in fields.items():
        if k not in allowed or v is None:
            continue
        if k == "skills":
            v = json.dumps(v, ensure_ascii=False)
        if k == "enabled":
            v = int(bool(v))
        sets.append(f"{k} = ?")
        params.append(v)
    if not sets:
        return False
    if "schedule" in fields and fields["schedule"]:
        nxt = _next_run(str(fields["schedule"]))
        if nxt is None:
            return False
        sets.append("next_run = ?")
        params.append(nxt)
    params.append(job_id)
    init_db()
    with _lock, _conn() as c:
        cur = c.execute(
            f"UPDATE cron_jobs SET {', '.join(sets)} "
            "WHERE id = ? OR name = ?", (*params, params[-1]))
        return cur.rowcount > 0


def set_enabled(job_id: str, enabled: bool) -> bool:
    return update(job_id, enabled=enabled)


def delete(job_id: str) -> bool:
    init_db()
    with _lock, _conn() as c:
        cur = c.execute("DELETE FROM cron_jobs WHERE id = ? OR name = ?",
                        (job_id, job_id))
        return cur.rowcount > 0


# ── eksekusi ──────────────────────────────────────────────────────────────

def run_job_now(job_id: str) -> tuple[bool, str]:
    job = get_job(job_id)
    if job is None:
        return False, "job tidak ditemukan"
    threading.Thread(target=_execute, args=(job,), daemon=True,
                     name=f"cron-{job['id']}").start()
    return True, f"job {job['name']} dijalankan sekarang"


def _execute(job: dict) -> None:
    t0 = time.time()
    _logger.info("cron.run", id=job["id"], name=job["name"])
    from jarvis.agent.job_store import JobStore
    run_store = JobStore(db_path().with_name("job_runs.sqlite"))
    try:
        run = run_store.start(job["id"], f"cron:{job['id']}:{t0}")
    except RuntimeError:
        _logger.info("cron.run_already_active", id=job["id"])
        return
    result_text = ""
    ok = False
    try:
        if job["id"] == _INTERNAL_CONSOLIDATE or \
                job["name"] == _INTERNAL_CONSOLIDATE:
            from jarvis.agent import memory_store
            stats = memory_store.consolidate()
            result_text = f"konsolidasi memori: {stats}"
            ok = True
        else:
            task = job["task"]
            skills_attached = json.loads(job.get("skills") or "[]") \
                if isinstance(job.get("skills"), str) else \
                (job.get("skills") or [])
            if skills_attached:
                from jarvis.agent import skills as skills_mod
                bodies = []
                for s in skills_attached:
                    body = skills_mod.view(s)
                    if body:
                        bodies.append(f"--- SKILL {s} ---\n{body[:4000]}")
                if bodies:
                    task = ("\n\n".join(bodies)
                            + f"\n\n--- TUGAS ---\n{task}")
            from jarvis.agent import dispatch
            result_text = dispatch.run_sync(
                task, timeout_s=float(config.get("agent.cron_timeout_s",
                                                 900)))
            ok = bool(result_text)
    except Exception as e:                                   # noqa: BLE001
        result_text = f"error: {str(e)[:200]}"
    finally:
        run_store.finish(run.id, ok=ok, result=result_text)
        with _lock, _conn() as c:
            c.execute(
                "UPDATE cron_jobs SET last_run = ?, next_run = ?, "
                "last_result = ?, run_count = run_count + 1 WHERE id = ?",
                (t0, _next_run(job["schedule"], t0),
                 (result_text or "")[:2000], job["id"]))
    _notify_result(job, ok, result_text)


def _notify_result(job: dict, ok: bool, text: str) -> None:
    if int(job.get("internal", 0)):
        return
    try:
        from jarvis.agent.adapters import telegram as tg
        status = "✅" if ok else "⚠️"
        tg.send_from_anywhere(
            f"{status} Cron '{job['name']}' selesai:\n{(text or '-')[:3500]}")
    except Exception:                                        # noqa: BLE001
        pass
    try:
        from jarvis.core.bus import BUS
        BUS.publish("agent.cron.done", name=job["name"], ok=ok,
                    text=(text or "")[:400])
    except Exception as exc:                                # noqa: BLE001
        from jarvis.core import quiet
        quiet.swallowed(
            "agent.cron.bus_publish_failed",
            exc,
            name=job["name"],
            ok=ok,
        )


# ── scheduler thread ──────────────────────────────────────────────────────

class CronScheduler:
    _instance: "CronScheduler | None" = None

    @classmethod
    def get(cls) -> "CronScheduler":
        if cls._instance is None:
            cls._instance = CronScheduler()
        return cls._instance

    def __init__(self):
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._interval = 20.0   # Phase 24: tick interval, dipakai stop() join

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        init_db()
        self._ensure_internal_jobs()
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="agent-cron")
        self._thread.start()
        _logger.info("cron.scheduler_started")

    def stop(self) -> None:
        """Stop scheduler dan join thread dengan batas bounded (Phase 24)."""
        self._stop.set()
        thread = self._thread
        if (thread is not None and thread.is_alive()
                and thread is not threading.current_thread()):
            thread.join(timeout=self._interval + 1.0)
        if thread is not None and not thread.is_alive():
            self._thread = None

    def _ensure_internal_jobs(self) -> None:
        if get_job(_INTERNAL_CONSOLIDATE) is None:
            create(_INTERNAL_CONSOLIDATE, "0 4 * * 0",
                   "konsolidasi memori mingguan", enabled=True,
                   internal=True)

    def _loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                now = time.time()
                for job in list_jobs():
                    if not job["enabled"]:
                        continue
                    nxt = job.get("next_run")
                    if nxt is None:
                        update(job["id"], schedule=job["schedule"])
                        continue
                    if nxt <= now:
                        # klaim dulu (set next_run) agar tidak dobel
                        with _lock, _conn() as c:
                            c.execute(
                                "UPDATE cron_jobs SET next_run = ? "
                                "WHERE id = ? AND next_run = ?",
                                (_next_run(job["schedule"], now),
                                 job["id"], nxt))
                            claimed = c.total_changes > 0
                        if claimed:
                            threading.Thread(
                                target=_execute, args=(job,), daemon=True,
                                name=f"cron-{job['id']}").start()
            except Exception as e:                           # noqa: BLE001
                _logger.error("cron.tick_failed", error=str(e)[:120])
