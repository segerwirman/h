"""Perintah yang TERBUKTI berhasil, agar Jarvis belajar dari pemakaian (Fase 26).

Takeda: *"optimalkan semua tools dan jarvis otomatis mengenali kegunaannya
berdasarkan input perintah."*

``tool_selection`` memakai regex kategori yang harus ditulis satu per satu.
Perintah yang tidak cocok jatuh ke registry penuh (90 tool) atau ke LLM. Indeks
ini mengisi celah itu dengan tetangga terdekat atas perintah yang SUDAH pernah
berhasil di mesin ini.

**Hanya yang terbukti yang disimpan.** Mesin kontrak bukti (Fase 14) sudah
memisahkan sukses nyata dari narasi model; menyimpan apa pun selain itu berarti
mengabadikan klaim palsu dan mengulanginya lebih cepat setiap hari.

Kemiripan dihitung ``jarvis.core.local_embed`` — leksikal, lokal, di bawah satu
milidetik. Cukup untuk perintah berulang dengan variasi kecil; bukan pengganti
pemahaman semantik.
"""
from __future__ import annotations

import json
import sqlite3
import threading

from jarvis.core import config, local_embed, log

_logger = log.get("agent.command_index")
_lock = threading.Lock()

MAX_ENTRIES = 400


def _db_path():
    from jarvis.agent.paths import db_path

    return db_path()


#: Diukur, bukan ditebak. Pada perintah lapangan Takeda, parafrasa satu tool
#: terendah 0.814 sedangkan pasangan BEDA tool tertinggi 0.649 ("putar lagu di
#: spotify" vs "hentikan lagu di spotify"). Ambang ditaruh di antaranya dan
#: condong ke atas: saran yang meleset hanya kembali ke perilaku lama, saran
#: yang salah merutekan perintah ke tool yang keliru.
DEFAULT_THRESHOLD = 0.75


def threshold() -> float:
    try:
        return float(config.get("agent.command_index.threshold",
                                DEFAULT_THRESHOLD))
    except (TypeError, ValueError):
        return DEFAULT_THRESHOLD


def enabled() -> bool:
    try:
        return bool(config.get("agent.command_index.enabled", True))
    except Exception:                                        # noqa: BLE001
        return True


def _conn():
    connection = sqlite3.connect(_db_path())
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS command_index (
            command TEXT PRIMARY KEY,
            tools TEXT NOT NULL,
            vector TEXT NOT NULL,
            used_at REAL
        )""")
    return connection


def remember(command, tools) -> bool:
    """Catat satu perintah yang sudah TERBUKTI berhasil."""
    try:
        if not enabled():
            return False
        text = " ".join(str(command or "").split())
        names = [str(name) for name in (tools or []) if str(name or "").strip()]
        if not text or not names:
            return False
        vector = local_embed.embed(text)
        if not any(vector):
            return False
        import time

        with _lock, _conn() as connection:
            connection.execute(
                "INSERT INTO command_index (command, tools, vector, used_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(command) DO UPDATE SET "
                "tools = excluded.tools, vector = excluded.vector, "
                "used_at = excluded.used_at",
                (text, json.dumps(names), json.dumps(vector), time.time()))
            # Batas keras: indeks tidak boleh tumbuh tanpa henti. Yang paling
            # lama tidak dipakai dibuang lebih dulu.
            connection.execute(
                "DELETE FROM command_index WHERE command NOT IN ("
                "  SELECT command FROM command_index "
                "  ORDER BY used_at DESC LIMIT ?)", (MAX_ENTRIES,))
        return True
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("command_index.remember_failed", error=str(exc)[:120])
        return False


def suggest(command) -> list[str] | None:
    """Tool untuk perintah paling mirip, atau ``None`` bila tidak cukup mirip."""
    try:
        if not enabled():
            return None
        text = " ".join(str(command or "").split())
        if not text:
            return None
        query = local_embed.embed(text)
        if not any(query):
            return None

        with _lock, _conn() as connection:
            rows = connection.execute(
                "SELECT command, tools, vector FROM command_index").fetchall()
        best_score, best_tools, best_command = 0.0, None, ""
        for stored_command, tools_json, vector_json in rows:
            try:
                score = local_embed.similarity(query, json.loads(vector_json))
            except Exception:                                # noqa: BLE001
                continue
            if score > best_score:
                best_score = score
                best_tools = json.loads(tools_json)
                best_command = stored_command
        if best_tools is None or best_score < threshold():
            return None
        _logger.info("command_index.hit", score=round(best_score, 3),
                     matched=best_command[:60])
        return list(best_tools)
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("command_index.suggest_failed", error=str(exc)[:120])
        return None


def count() -> int:
    try:
        with _lock, _conn() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM command_index").fetchone()[0])
    except Exception:                                        # noqa: BLE001
        return 0


def reset() -> None:
    try:
        with _lock, _conn() as connection:
            connection.execute("DELETE FROM command_index")
    except Exception:                                        # noqa: BLE001
        pass


__all__ = ["DEFAULT_THRESHOLD", "MAX_ENTRIES", "count", "enabled", "remember", "reset", "suggest",
           "threshold"]
