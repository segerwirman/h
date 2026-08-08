"""Memory System (Modul 6, extended by redesign §12) — layered memory.

Episodic Log:   SQLite, deduplicated within a configurable time window so
                repeated/heartbeat-style events merge instead of piling up.
Semantic Memory: FAISS vector store for semantic retrieval of past facts
                (unchanged from Modul 6 — degrades to no-op without faiss).
Working Memory: small in-process ring buffer, never persisted.
Procedural Memory: named macros (parameterized step sequences), stored only
                after explicit approval — nothing here executes automatically.

Retention/compaction keeps the episodic table bounded: rows older than the
configured retention window are dropped, and once the table exceeds
``max_rows`` the oldest chunk is collapsed into a single summary row instead
of being deleted outright, so long-run history degrades gracefully rather
than vanishing or growing without bound.

The public surface used elsewhere in the codebase — ``MemoryManager.get()``,
``add_episodic(role, content, meta=None)``, ``get_recent_episodes(limit)``,
``add_semantic(text)``, ``search_semantic(query, top_k)`` — is unchanged in
signature and behaviour; every new capability is additive.
"""
from __future__ import annotations

import difflib
import hashlib
import json
import sqlite3
import time
from collections import deque
from pathlib import Path

from jarvis.core import config, log, llm

_logger = log.get("core.memory")

#: §33 (T5) — pesan yang benar-benar dikirim, sebagai konstanta supaya bisa
#: diuji tanpa menebak-nebak teks sumber.
FAISS_MISSING_DETAIL = (
    "indeks vektor lama core.memory nonaktif (faiss tidak terpasang); "
    "memori semantik agent tetap jalan lewat memory_store")

_SCHEMA_VERSION = 2


class MemoryManager:
    _instance = None

    @classmethod
    def get(cls) -> MemoryManager:
        if cls._instance is None:
            cls._instance = MemoryManager()
        return cls._instance

    @classmethod
    def _reset_for_tests(cls) -> None:
        cls._instance = None

    def __init__(self, db_dir: Path | None = None):
        # db_dir lets tests point a standalone instance at a temp directory
        # without touching the process-wide singleton returned by get().
        base = db_dir if db_dir is not None else config.resolve_path(".")
        self.db_path = base / "memory.sqlite"
        self.faiss_path = base / "memory.faiss"
        self.semantic_index_path = base / "memory_index.json"
        self._init_db()
        self._migrate()
        self._init_faiss()

        max_working = int(config.get("memory.working_memory.max_items", 40))
        self._working: deque[dict] = deque(maxlen=max_working)

    # ── schema / migrations ──────────────────────────────────────────────

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS episodic_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL,
                    role TEXT,
                    content TEXT,
                    meta TEXT
                )
            ''')
            conn.execute('''
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at REAL
                )
            ''')

    def _applied_versions(self, conn: sqlite3.Connection) -> set[int]:
        try:
            rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
            return {r[0] for r in rows}
        except sqlite3.OperationalError:
            return set()

    def _migrate(self) -> None:
        """Versioned, idempotent, reversible-by-construction migrations —
        every step only ADDs columns/tables, so re-running is always safe
        and no prior data is ever destroyed."""
        with sqlite3.connect(self.db_path) as conn:
            applied = self._applied_versions(conn)

            if 1 not in applied:
                for ddl in (
                    "ALTER TABLE episodic_log ADD COLUMN session_id TEXT DEFAULT ''",
                    "ALTER TABLE episodic_log ADD COLUMN app TEXT DEFAULT ''",
                    "ALTER TABLE episodic_log ADD COLUMN action_type TEXT DEFAULT ''",
                    "ALTER TABLE episodic_log ADD COLUMN target TEXT DEFAULT ''",
                    "ALTER TABLE episodic_log ADD COLUMN result TEXT DEFAULT ''",
                    "ALTER TABLE episodic_log ADD COLUMN confidence REAL DEFAULT NULL",
                    "ALTER TABLE episodic_log ADD COLUMN dedup_hash TEXT DEFAULT ''",
                    "ALTER TABLE episodic_log ADD COLUMN dup_count INTEGER DEFAULT 1",
                    "ALTER TABLE episodic_log ADD COLUMN privacy TEXT DEFAULT 'normal'",
                ):
                    try:
                        conn.execute(ddl)
                    except sqlite3.OperationalError:
                        pass  # column already present (re-run safety)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_dedup "
                            "ON episodic_log(dedup_hash, timestamp)")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_episodic_ts "
                            "ON episodic_log(timestamp)")
                conn.execute("INSERT OR REPLACE INTO schema_migrations VALUES (1, ?)",
                            (time.time(),))

            if 2 not in applied:
                conn.execute('''
                    CREATE TABLE IF NOT EXISTS procedural_macros (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT UNIQUE,
                        steps_json TEXT,
                        preconditions_json TEXT,
                        created_at REAL,
                        last_used_at REAL,
                        use_count INTEGER DEFAULT 0,
                        approved INTEGER DEFAULT 0
                    )
                ''')
                conn.execute("INSERT OR REPLACE INTO schema_migrations VALUES (2, ?)",
                            (time.time(),))
            conn.commit()

    def _init_faiss(self):
        try:
            import faiss
            import numpy as np

            self.dimension = 768  # Assuming Gemini embedding dimension
            if self.faiss_path.exists():
                self.index = faiss.read_index(str(self.faiss_path))
            else:
                self.index = faiss.IndexFlatL2(self.dimension)

            if self.semantic_index_path.exists():
                with open(self.semantic_index_path, "r", encoding="utf-8") as f:
                    self.docs = json.load(f)
            else:
                self.docs = []
        except ImportError:
            # §33 (T5) — pesan lama berbunyi "Semantic memory disabled" dan
            # itu MELEBIH-LEBIHKAN kerugiannya. Yang mati hanyalah indeks
            # vektor lama di modul ini; memori semantik yang benar-benar
            # dipakai agent hidup di jarvis/agent/memory_store.py (SQLite +
            # embedding, cosine in-memory, tanpa FAISS) — diukur 298 dari 298
            # baris punya embedding. Kegagalan palsu sama merusaknya dengan
            # sukses palsu, hanya arahnya terbalik.
            _logger.info("memory.faiss_missing", detail=FAISS_MISSING_DETAIL)
            self.index = None
            self.docs = []

    # ── episodic (unchanged public signature; dedup + richer meta inside) ──

    @staticmethod
    def _dedup_hash(role: str, content: str, meta: dict) -> str:
        basis = f"{role}|{content}|{meta.get('target', '')}|{meta.get('action_type', '')}"
        return hashlib.sha1(basis.encode("utf-8", "ignore")).hexdigest()

    def add_episodic(self, role: str, content: str, meta: dict = None) -> None:
        meta = meta or {}
        meta_str = json.dumps(meta)
        now = time.time()
        dedup_hash = self._dedup_hash(role, content, meta)
        window_s = float(config.get("memory.deduplication.window_s", 30))

        with sqlite3.connect(self.db_path) as conn:
            if window_s > 0:
                row = conn.execute(
                    "SELECT id, dup_count FROM episodic_log WHERE dedup_hash = ? "
                    "AND timestamp >= ? ORDER BY timestamp DESC LIMIT 1",
                    (dedup_hash, now - window_s)).fetchone()
                if row is not None:
                    conn.execute(
                        "UPDATE episodic_log SET timestamp = ?, dup_count = ? WHERE id = ?",
                        (now, row[1] + 1, row[0]))
                    return
            conn.execute(
                "INSERT INTO episodic_log (timestamp, role, content, meta, session_id, "
                "app, action_type, target, result, confidence, dedup_hash, dup_count, privacy) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?)",
                (now, role, content, meta_str,
                 str(meta.get("session_id", "")), str(meta.get("app", "")),
                 str(meta.get("action_type", "")), str(meta.get("target", "")),
                 str(meta.get("result", "")), meta.get("confidence"),
                 dedup_hash, str(meta.get("privacy", "normal"))))

    def get_recent_episodes(self, limit: int = 50) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM episodic_log ORDER BY timestamp DESC LIMIT ?",
                                (limit,)).fetchall()
            return [dict(r) for r in reversed(rows)]

    # ── Context Timeline read API ────────────────────────────────────────

    def get_timeline(self, app: str | None = None, action_type: str | None = None,
                     since: float | None = None, until: float | None = None,
                     text_contains: str | None = None, limit: int = 100) -> list[dict]:
        clauses, params = [], []
        if app:
            clauses.append("app = ?"); params.append(app)
        if action_type:
            clauses.append("action_type = ?"); params.append(action_type)
        if since is not None:
            clauses.append("timestamp >= ?"); params.append(since)
        if until is not None:
            clauses.append("timestamp <= ?"); params.append(until)
        if text_contains:
            clauses.append("(content LIKE ? OR target LIKE ?)")
            like = f"%{text_contains}%"
            params.extend([like, like])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                f"SELECT * FROM episodic_log {where} ORDER BY timestamp DESC LIMIT ?",
                (*params, limit)).fetchall()
            return [dict(r) for r in rows]

    # ── working memory (in-process, not persisted) ───────────────────────

    def push_working(self, item: dict) -> None:
        self._working.append({**item, "ts": time.time()})

    def working(self, limit: int | None = None) -> list[dict]:
        items = list(self._working)
        return items[-limit:] if limit else items

    # ── procedural memory (macros — never auto-created or auto-run) ─────

    def save_macro(self, name: str, steps: list[dict],
                   preconditions: list[dict] | None = None,
                   approved: bool = False) -> None:
        now = time.time()
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO procedural_macros (name, steps_json, preconditions_json, "
                "created_at, last_used_at, use_count, approved) VALUES (?, ?, ?, ?, ?, 0, ?) "
                "ON CONFLICT(name) DO UPDATE SET steps_json=excluded.steps_json, "
                "preconditions_json=excluded.preconditions_json, approved=excluded.approved",
                (name, json.dumps(steps), json.dumps(preconditions or []), now, now,
                 int(approved)))

    def list_macros(self, approved_only: bool = False) -> list[dict]:
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            q = "SELECT * FROM procedural_macros"
            if approved_only:
                q += " WHERE approved = 1"
            rows = conn.execute(q + " ORDER BY use_count DESC").fetchall()
            out = []
            for r in rows:
                d = dict(r)
                d["steps"] = json.loads(d.pop("steps_json") or "[]")
                d["preconditions"] = json.loads(d.pop("preconditions_json") or "[]")
                out.append(d)
            return out

    def approve_macro(self, name: str) -> bool:
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("UPDATE procedural_macros SET approved = 1 WHERE name = ?", (name,))
            return cur.rowcount > 0

    def record_macro_use(self, name: str) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("UPDATE procedural_macros SET use_count = use_count + 1, "
                        "last_used_at = ? WHERE name = ?", (time.time(), name))

    # ── retention / compaction ───────────────────────────────────────────

    def compact(self, summarizer=None) -> dict:
        """Age-based deletion + size-based summarization. ``summarizer`` is
        an optional ``callable(list[dict]) -> str``; without one, a light
        extractive fallback is used so compaction works with zero network
        dependency."""
        retention_days = config.get("memory.retention.days", None)
        max_rows = int(config.get("memory.retention.max_rows", 20000))
        chunk_size = int(config.get("memory.compaction.chunk_size", 200))
        stats = {"deleted_by_age": 0, "summarized": 0, "kept": 0}

        with sqlite3.connect(self.db_path) as conn:
            if retention_days:
                cutoff = time.time() - float(retention_days) * 86400
                cur = conn.execute("DELETE FROM episodic_log WHERE timestamp < ?", (cutoff,))
                stats["deleted_by_age"] = cur.rowcount

            total = conn.execute("SELECT COUNT(*) FROM episodic_log").fetchone()[0]
            if total > max_rows:
                conn.row_factory = sqlite3.Row
                oldest = conn.execute(
                    "SELECT * FROM episodic_log ORDER BY timestamp ASC LIMIT ?",
                    (chunk_size,)).fetchall()
                if oldest:
                    rows = [dict(r) for r in oldest]
                    summary_text = (summarizer(rows) if summarizer
                                    else self._extractive_summary(rows))
                    t0, t1 = rows[0]["timestamp"], rows[-1]["timestamp"]
                    conn.execute(
                        "INSERT INTO episodic_log (timestamp, role, content, meta, "
                        "action_type, dedup_hash, dup_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (t1, "episode_summary", summary_text,
                         json.dumps({"span": [t0, t1], "n": len(rows)}),
                         "compaction", "", 1))
                    ids = [r["id"] for r in rows]
                    conn.executemany("DELETE FROM episodic_log WHERE id = ?",
                                     [(i,) for i in ids])
                    stats["summarized"] = len(ids)
            stats["kept"] = conn.execute("SELECT COUNT(*) FROM episodic_log").fetchone()[0]
        _logger.info("memory.compacted", **stats)
        return stats

    @staticmethod
    def _extractive_summary(rows: list[dict]) -> str:
        apps = sorted({r.get("app") for r in rows if r.get("app")})
        samples = [r["content"][:80] for r in rows[:5] if r.get("content")]
        n = len(rows)
        parts = [f"{n} events"]
        if apps:
            parts.append(f"across {', '.join(apps[:5])}")
        if samples:
            parts.append("including: " + " | ".join(samples))
        return "; ".join(parts)

    # ── hybrid retrieval (recency + exact + fuzzy + semantic) ────────────

    def retrieve(self, query: str, top_k: int | None = None) -> list[dict]:
        top_k = top_k or int(config.get("memory.retrieval.top_k_default", 5))
        w = config.section("memory.retrieval")
        w_sem = float(w.get("weight_semantic", 1.0))
        w_exact = float(w.get("weight_exact", 0.9))
        w_fuzzy = float(w.get("weight_fuzzy", 0.6))
        w_recency = float(w.get("weight_recency", 0.5))

        recent = self.get_recent_episodes(limit=200)
        scored: dict[int, tuple[float, dict, str]] = {}
        q_norm = query.strip().lower()

        for rank, row in enumerate(reversed(recent)):
            recency_score = w_recency * max(0.0, 1.0 - rank / max(1, len(recent)))
            content = (row.get("content") or "").lower()
            score, source = recency_score, "recency"
            if q_norm and q_norm in content:
                score = max(score, w_exact)
                source = "exact"
            elif q_norm:
                ratio = difflib.SequenceMatcher(None, q_norm, content[:200]).ratio()
                if ratio > 0.3:
                    fuzzy_score = w_fuzzy * ratio
                    if fuzzy_score > score:
                        score, source = fuzzy_score, "fuzzy"
            if score > 0:
                scored[row["id"]] = (score, row, source)

        if q_norm:
            for text in self.search_semantic(query, top_k=top_k):
                key = hash(("sem", text))
                existing = scored.get(key)
                sem_score = w_sem
                if existing is None or sem_score > existing[0]:
                    scored[key] = (sem_score, {"content": text, "id": key, "role": "semantic"},
                                  "semantic")

        ranked = sorted(scored.values(), key=lambda t: t[0], reverse=True)[:top_k]
        results = []
        for score, row, source in ranked:
            d = dict(row)
            d["_match_score"] = round(score, 4)
            d["_match_source"] = source
            results.append(d)
        return results

    # ── semantic memory (Modul 6, unchanged) ─────────────────────────────

    def add_semantic(self, text: str):
        if self.index is None:
            return

        try:
            from google import genai
            client_key = llm.api_key()
            if not client_key:
                return
            client = genai.Client(api_key=client_key)
            res = client.models.embed_content(model="text-embedding-004", contents=[text])
            import numpy as np
            vector = np.array([res.embeddings[0].values], dtype=np.float32)

            self.index.add(vector)
            self.docs.append({"id": len(self.docs), "text": text, "timestamp": time.time()})

            import faiss
            faiss.write_index(self.index, str(self.faiss_path))
            with open(self.semantic_index_path, "w", encoding="utf-8") as f:
                json.dump(self.docs, f)
        except Exception as e:
            _logger.error("memory.semantic_add_failed", error=str(e)[:80])

    def search_semantic(self, query: str, top_k: int = 3) -> list[str]:
        if self.index is None or not self.docs:
            return []

        try:
            from google import genai
            client_key = llm.api_key()
            if not client_key:
                return []
            client = genai.Client(api_key=client_key)
            res = client.models.embed_content(model="text-embedding-004", contents=[query])
            import numpy as np
            vector = np.array([res.embeddings[0].values], dtype=np.float32)

            D, I = self.index.search(vector, min(top_k, len(self.docs)))
            results = []
            for idx in I[0]:
                if idx >= 0 and int(idx) < len(self.docs):
                    results.append(self.docs[int(idx)]["text"])
            return results
        except Exception as e:
            _logger.error("memory.semantic_search_failed", error=str(e)[:80])
            return []
