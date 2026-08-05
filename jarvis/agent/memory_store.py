"""Memori agent (jarvis.md §4) — episodic | semantic | procedural | reflective.

SQLite + FTS5 + vektor embedding (BLOB numpy float32; cosine in-memory —
dataset kecil, tetap cepat; sesuai fallback yang diizinkan spec §4.2).

Retrieval hybrid (§4.3):
    score = 0.45·semantic + 0.25·keyword(BM25) + 0.15·recency + 0.15·importance
Top-8, dedupe, dibatasi ~800 token saat diinjeksi ke system prompt.
"""
from __future__ import annotations

import json
import math
import sqlite3
import threading
import time
import uuid

from jarvis.core import config, log
from jarvis.agent.paths import db_path
from jarvis.agent.memory_policy import SCOPES, retention_seconds

_logger = log.get("agent.memory")
_lock = threading.Lock()

TYPES = ("episodic", "semantic", "procedural", "reflective")


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(db_path())
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    with _lock, _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS memories (
                id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                content TEXT NOT NULL,
                embedding BLOB,
                tags TEXT,
                importance REAL DEFAULT 0.5,
                access_count INTEGER DEFAULT 0,
                created_at INTEGER,
                last_accessed INTEGER,
                source_session TEXT,
                superseded_by TEXT,
                scope TEXT DEFAULT 'device-local',
                owner TEXT DEFAULT 'device',
                retention_until INTEGER
            )""")
        _ensure_columns(c)
        try:
            c.execute("""
                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, content=memories, content_rowid=rowid)
            """)
            c.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ai
                AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content)
                    VALUES (new.rowid, new.content);
                END""")
            c.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_ad
                AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
                END""")
            c.execute("""
                CREATE TRIGGER IF NOT EXISTS memories_au
                AFTER UPDATE OF content ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES ('delete', old.rowid, old.content);
                    INSERT INTO memories_fts(rowid, content)
                    VALUES (new.rowid, new.content);
                END""")
        except sqlite3.OperationalError:
            pass


def _ensure_columns(conn: sqlite3.Connection) -> None:
    """Small forward migration for databases created before scoped memory."""
    names = {row[1] for row in conn.execute("PRAGMA table_info(memories)")}
    if "scope" not in names:
        conn.execute("ALTER TABLE memories ADD COLUMN scope TEXT DEFAULT 'device-local'")
    if "owner" not in names:
        conn.execute("ALTER TABLE memories ADD COLUMN owner TEXT DEFAULT 'device'")
    if "retention_until" not in names:
        conn.execute("ALTER TABLE memories ADD COLUMN retention_until INTEGER")


# ── embedding helpers ─────────────────────────────────────────────────────

def _embed(texts: list[str]) -> list[list[float]] | None:
    try:
        # §3.3 — embedding adalah side-task murah: SELALU lane ringan.
        # Ini juga menstabilkan dimensi vektor: model embedding tidak lagi
        # ikut berpindah saat provider aktif/berat diganti (catatan §4.2 di
        # auxiliary.py). Lane ringan default = provider yang sama dengan
        # perilaku lama (gemini), jadi vektor tersimpan tetap kompatibel.
        from jarvis.agent import model_routing
        cl = model_routing.light_client()
        if not cl.available():
            return None
        return cl.embed(texts)
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("memory.embed_failed", error=str(e)[:100])
        return None


def _to_blob(vec: list[float] | None) -> bytes | None:
    if not vec:
        return None
    import numpy as np
    return np.asarray(vec, dtype=np.float32).tobytes()


def backfill_embeddings(batch_size: int = 32,
                        limit: int | None = None) -> dict:
    """Isi ulang vektor memori yang kosong (Fase 13.0, temuan S-9).

    Baris ``embedding IS NULL`` tertinggal setiap kali lane ringan menunjuk
    provider yang tidak melayani embedding: ``_embed`` mengembalikan ``None``
    dan ``write``/``update`` tetap menyimpan barisnya tanpa vektor. Memori itu
    tidak pernah pulih sendiri saat provider diperbaiki, sehingga pencarian
    semantik terus melewatinya.

    Sengaja memakai ``_embed`` yang sama dengan jalur tulis — dimensi vektor
    harus punya satu sumber, kalau tidak ``_cosine`` diam-diam mengembalikan
    0.0 untuk vektor berdimensi beda (baris 125).

    Kontrak kejujuran (sama seperti S-1): provider yang tidak bisa embed
    membuat fungsi ini **melapor gagal**, bukan menulis vektor kosong atau
    mengaku selesai. Batch yang sudah mendarat tidak ditarik kembali.

    Return ``{"pending", "embedded", "failed", "reason"}`` — ``pending`` adalah
    jumlah baris kosong yang tersisa SETELAH backfill.
    """
    init_db()
    size = max(1, min(128, int(batch_size or 32)))
    embedded = 0
    reason = ""

    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT id, content FROM memories WHERE embedding IS NULL "
            "ORDER BY created_at ASC" + (" LIMIT ?" if limit else ""),
            (int(limit),) if limit else ()).fetchall()

    for start in range(0, len(rows), size):
        batch = rows[start:start + size]
        try:
            vecs = _embed([str(content) for _, content in batch])
        except Exception as e:                               # noqa: BLE001
            vecs, reason = None, f"{type(e).__name__}: {str(e)[:120]}"
        if not vecs or len(vecs) != len(batch):
            reason = reason or ("provider lane ringan tidak mengembalikan "
                                "embedding — vektor tidak diubah")
            break
        # Commit per batch: kegagalan batch berikutnya tidak boleh menghapus
        # pekerjaan yang sudah berhasil.
        with _lock, _conn() as c:
            for (mem_id, _), vec in zip(batch, vecs):
                blob = _to_blob(vec)
                if blob is None:
                    continue
                c.execute("UPDATE memories SET embedding = ? WHERE id = ?",
                          (blob, mem_id))
                embedded += 1

    with _lock, _conn() as c:
        pending = int(c.execute(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NULL"
        ).fetchone()[0])

    failed = bool(reason)
    _logger.info("memory.backfill", embedded=embedded, pending=pending,
                 failed=failed, reason=reason[:160] or None)
    return {"pending": pending, "embedded": embedded, "failed": failed,
            "reason": reason}


def _cosine(a: bytes, b: list[float]) -> float:
    import numpy as np
    va = np.frombuffer(a, dtype=np.float32)
    vb = np.asarray(b, dtype=np.float32)
    if va.size != vb.size or va.size == 0:
        return 0.0
    denom = float(np.linalg.norm(va) * np.linalg.norm(vb))
    return float(va @ vb) / denom if denom else 0.0


# ── operasi dasar ─────────────────────────────────────────────────────────

def write(mtype: str, content: str, importance: float = 0.5,
          tags: list[str] | None = None, source_session: str = "",
          scope: str = "device-local", owner: str = "") -> str:
    if mtype not in TYPES:
        mtype = "semantic"
    if scope not in SCOPES:
        raise ValueError("memory_scope_invalid")
    init_db()
    mid = uuid.uuid4().hex[:16]
    now = int(time.time())
    retention = retention_seconds(scope)
    retention_until = now + retention if retention is not None else None
    vecs = _embed([content])
    with _lock, _conn() as c:
        c.execute(
            "INSERT INTO memories (id, type, content, embedding, tags, "
            "importance, created_at, last_accessed, source_session, scope, owner, retention_until) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (mid, mtype, content, _to_blob(vecs[0] if vecs else None),
             json.dumps(tags or [], ensure_ascii=False),
             max(0.0, min(1.0, float(importance))), now, now,
             source_session, scope, str(owner or "device")[:160], retention_until))
    _logger.info("memory.written", type=mtype, id=mid,
                 importance=importance)
    return mid


def update(mem_id: str, content: str, scope: str | None = None,
           owner: str | None = None) -> bool:
    init_db()
    vecs = _embed([content])
    with _lock, _conn() as c:
        where = "id = ?"
        params: list = [content, _to_blob(vecs[0] if vecs else None),
                        int(time.time()), mem_id]
        if scope is not None and owner is not None:
            where += " AND scope = ? AND owner = ?"
            params.extend([scope, owner])
        cur = c.execute("UPDATE memories SET content = ?, embedding = ?, "
                        "last_accessed = ? WHERE " + where, params)
        return cur.rowcount > 0


def forget(mem_id: str, scope: str | None = None, owner: str | None = None) -> bool:
    init_db()
    with _lock, _conn() as c:
        where = "id = ?"
        params: list = [mem_id]
        if scope is not None and owner is not None:
            where += " AND scope = ? AND owner = ?"
            params.extend([scope, owner])
        cur = c.execute("DELETE FROM memories WHERE " + where, params)
        return cur.rowcount > 0


def export(*, scope: str, owner: str, limit: int = 500) -> list[dict]:
    """Return a bounded, secret-redacted export from one explicit scope."""
    if scope not in SCOPES or not owner:
        return []
    from jarvis.agent.session_store import redact

    init_db()
    with _lock, _conn() as c:
        c.row_factory = sqlite3.Row
        rows = c.execute(
            "SELECT id, type, content, tags, importance, created_at, scope "
            "FROM memories WHERE scope = ? AND owner = ? "
            "AND (retention_until IS NULL OR retention_until > ?) "
            "ORDER BY created_at ASC LIMIT ?",
            (scope, owner, int(time.time()), max(1, min(int(limit), 500))),
        ).fetchall()
    return [{
        "id": row["id"],
        "type": row["type"],
        "content": redact(row["content"]),
        "tags": json.loads(row["tags"] or "[]"),
        "importance": row["importance"],
        "created_at": row["created_at"],
        "scope": row["scope"],
    } for row in rows]


def scope_counts() -> dict[str, int]:
    """Management-only aggregate; it intentionally exposes no memory content."""
    init_db()
    with _lock, _conn() as c:
        rows = c.execute(
            "SELECT scope, COUNT(*) FROM memories "
            "WHERE superseded_by IS NULL OR superseded_by = '' GROUP BY scope"
        ).fetchall()
    return {str(scope): int(count) for scope, count in rows if scope in SCOPES}


def supersede(mem_id: str, by: str = "", *, scope: str | None = None,
              owner: str | None = None) -> bool:
    init_db()
    with _lock, _conn() as c:
        where = "id = ?"
        params: list = [by or "retracted", mem_id]
        if scope is not None and owner is not None:
            where += " AND scope = ? AND owner = ?"
            params.extend([scope, owner])
        cur = c.execute("UPDATE memories SET superseded_by = ? WHERE " + where,
                        params)
        return cur.rowcount > 0


def get_reflective(min_importance: float = 0.6, limit: int = 12, *,
                   scope: str | None = None, owner: str | None = None) -> list[dict]:
    """Guardrail §4.4 — pelajaran dari kegagalan, injeksi ke system prompt."""
    init_db()
    with _lock, _conn() as c:
        c.row_factory = sqlite3.Row
        where = ("type = 'reflective' AND importance >= ? "
                 "AND (superseded_by IS NULL OR superseded_by = '') "
                 "AND (retention_until IS NULL OR retention_until > ?)")
        params: list = [min_importance, int(time.time())]
        if scope is not None:
            where += " AND scope = ?"
            params.append(scope)
        if owner is not None:
            where += " AND owner = ?"
            params.append(owner)
        rows = c.execute("SELECT id, content, importance FROM memories WHERE "
                         + where + " ORDER BY importance DESC LIMIT ?",
                         [*params, limit]).fetchall()
        return [dict(r) for r in rows]


# ── retrieval hybrid (§4.3) ───────────────────────────────────────────────

def _embed_within(query: str, deadline_s: float):
    """Embedding dengan TENGGAT. ``None`` bila terlambat (Fase 24).

    Terukur: ``search`` memakan 3250 ms dingin dan 422 ms hangat, hampir
    seluruhnya embedding — round trip jaringan SEBELUM model ditanya sama
    sekali. Pencarian keyword (FTS5) sepenuhnya lokal dan sudah ada, jadi
    giliran yang terlambat memakainya saja.

    Permintaan yang telat TIDAK dibatalkan (tidak bisa), tetapi hasilnya
    diabaikan dan tidak pernah menahan giliran ini.
    """
    if deadline_s <= 0:
        return _embed([query])
    result: dict = {}
    done = threading.Event()

    def _worker() -> None:
        try:
            result["vecs"] = _embed([query])
        except Exception:                                    # noqa: BLE001
            result["vecs"] = None
        finally:
            done.set()

    threading.Thread(target=_worker, daemon=True,
                     name="memory-embed").start()
    if not done.wait(max(0.01, float(deadline_s))):
        _logger.info("memory.embed_deadline", deadline_s=round(deadline_s, 2))
        return None
    return result.get("vecs")


def _embed_deadline() -> float:
    try:
        return float(config.get("agent.memory.embed_deadline_s", 0.4))
    except (TypeError, ValueError):
        return 0.4


def search(query: str, mtype: str | None = None, limit: int = 8,
           max_tokens: int = 800, *, scope: str | None = None,
           owner: str | None = None,
           embed_deadline_s: float | None = None) -> list[dict]:
    init_db()
    if scope is not None and scope not in SCOPES:
        return []
    now = time.time()
    w_sem, w_kw, w_rec, w_imp = 0.45, 0.25, 0.15, 0.15

    with _lock, _conn() as c:
        c.row_factory = sqlite3.Row
        base_where = "(superseded_by IS NULL OR superseded_by = '') " \
                     "AND (retention_until IS NULL OR retention_until > :now)"
        params = {"now": int(now)}
        if mtype:
            base_where += " AND type = :t"
            params["t"] = mtype
        if scope is not None:
            base_where += " AND scope = :scope"
            params["scope"] = scope
        if owner is not None:
            base_where += " AND owner = :owner"
            params["owner"] = owner
        rows = [dict(r) for r in c.execute(
            f"SELECT rowid, * FROM memories WHERE {base_where}", params).fetchall()]
        if not rows:
            return []

        # BM25 via FTS5 — peta rowid → skor keyword (dinormalkan 0..1)
        kw_score: dict[int, float] = {}
        try:
            fts = c.execute(
                "SELECT rowid, bm25(memories_fts) AS s FROM memories_fts "
                "WHERE memories_fts MATCH ? LIMIT 64",
                (_fts_quote(query),)).fetchall()
            if fts:
                best = min(r["s"] for r in fts)              # bm25: kecil = baik
                worst = max(r["s"] for r in fts)
                span = (worst - best) or 1.0
                for r in fts:
                    kw_score[r["rowid"]] = 1.0 - (r["s"] - best) / span
        except sqlite3.OperationalError:
            q = query.lower()
            for r in rows:
                if q and q in r["content"].lower():
                    kw_score[r["rowid"]] = 1.0

    q_vec = None
    deadline = (_embed_deadline() if embed_deadline_s is None
                else float(embed_deadline_s))
    vecs = _embed_within(query, deadline) if query.strip() else None
    if vecs:
        q_vec = vecs[0]

    scored: list[tuple[float, dict]] = []
    for r in rows:
        sem = _cosine(r["embedding"], q_vec) \
            if (q_vec is not None and r["embedding"]) else 0.0
        kw = kw_score.get(r["rowid"], 0.0)
        age_days = max(0.0, (now - (r["created_at"] or now)) / 86400.0)
        rec = math.exp(-age_days / 30.0)
        score = (w_sem * max(0.0, sem) + w_kw * kw + w_rec * rec
                 + w_imp * float(r["importance"] or 0.5))
        scored.append((score, r))

    scored.sort(key=lambda t: t[0], reverse=True)

    out: list[dict] = []
    seen: set[str] = set()
    budget = max_tokens * 4                                  # ≈ karakter
    used = 0
    for score, r in scored:
        key = r["content"][:80].lower()
        if key in seen or score <= 0.01:
            continue
        seen.add(key)
        used += len(r["content"])
        if used > budget and out:
            break
        out.append({"id": r["id"], "type": r["type"],
                    "content": r["content"],
                    "importance": r["importance"],
                    "scope": r.get("scope", "device-local"),
                    "score": round(score, 4)})
        if len(out) >= limit:
            break

    if out:
        ids = [m["id"] for m in out]
        with _lock, _conn() as c:
            c.executemany(
                "UPDATE memories SET access_count = access_count + 1, "
                "last_accessed = ? WHERE id = ?",
                [(int(now), i) for i in ids])
    return out


def _fts_quote(q: str) -> str:
    toks = [t.replace('"', '""') for t in q.split() if t.strip()]
    return " ".join(f'"{t}"' for t in toks) or '""'


# ── konsolidasi berkala (§4.4) ────────────────────────────────────────────

def consolidate() -> dict:
    """Mingguan (dijadwalkan cron internal): gabung duplikat, decay yang tak
    pernah diakses, ringkas episodic tua, hapus noise."""
    init_db()
    stats = {"merged": 0, "decayed": 0, "summarized": 0, "deleted": 0}
    now = int(time.time())
    import numpy as np

    with _lock, _conn() as c:
        c.row_factory = sqlite3.Row
        rows = [dict(r) for r in c.execute(
            "SELECT rowid, * FROM memories "
            "WHERE (superseded_by IS NULL OR superseded_by = '')").fetchall()]

        # 1. duplikat semantik (similarity > 0.92) — pertahankan importance max
        with_vec = [r for r in rows if r["embedding"]]
        dropped: set[str] = set()
        for i, a in enumerate(with_vec):
            if a["id"] in dropped:
                continue
            va = np.frombuffer(a["embedding"], dtype=np.float32)
            na = float(np.linalg.norm(va)) or 1.0
            for b in with_vec[i + 1:]:
                if (b["id"] in dropped or b["type"] != a["type"]
                        or b["scope"] != a["scope"] or b["owner"] != a["owner"]):
                    continue
                vb = np.frombuffer(b["embedding"], dtype=np.float32)
                if va.size != vb.size:
                    continue
                sim = float(va @ vb) / (na * (float(np.linalg.norm(vb)) or 1.0))
                if sim > 0.92:
                    keep, drop = (a, b) if (a["importance"] or 0) >= \
                        (b["importance"] or 0) else (b, a)
                    c.execute("UPDATE memories SET superseded_by = ? "
                              "WHERE id = ?", (keep["id"], drop["id"]))
                    dropped.add(drop["id"])
                    stats["merged"] += 1

        # 2. decay importance memori yang tak pernah diakses > 30 hari
        cur = c.execute(
            "UPDATE memories SET importance = importance * 0.9 "
            "WHERE access_count = 0 AND last_accessed < ?", (now - 30 * 86400,))
        stats["decayed"] = cur.rowcount

        # 3. episodic > 90 hari → satu ringkasan semantic ekstraktif
        old = [dict(r) for r in c.execute(
            "SELECT * FROM memories WHERE type = 'episodic' "
            "AND created_at < ? AND (superseded_by IS NULL OR "
            "superseded_by = '') LIMIT 200", (now - 90 * 86400,)).fetchall()]
        grouped: dict[tuple[str, str], list[dict]] = {}
        for row in old:
            grouped.setdefault((str(row["scope"]), str(row["owner"])), []).append(row)
        for (scope, owner), rows in grouped.items():
            if len(rows) < 5:
                continue
            samples = "; ".join(r["content"][:100] for r in rows[:8])
            summary = (f"Ringkasan {len(rows)} kejadian lama "
                       f"(otomatis): {samples}")
            sid = uuid.uuid4().hex[:16]
            c.execute(
                "INSERT INTO memories (id, type, content, importance, "
                "created_at, last_accessed, scope, owner) "
                "VALUES (?, 'semantic', ?, 0.4, ?, ?, ?, ?)",
                (sid, summary, now, now, scope, owner))
            c.executemany("UPDATE memories SET superseded_by = ? "
                          "WHERE id = ?", [(sid, r["id"]) for r in rows])
            stats["summarized"] += len(rows)

        # 4. hapus noise: importance < 0.15 dan tak pernah diakses
        cur = c.execute(
            "DELETE FROM memories WHERE importance < 0.15 "
            "AND access_count = 0")
        stats["deleted"] = cur.rowcount

    _logger.info("memory.consolidated", **stats)
    return stats
