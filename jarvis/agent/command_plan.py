"""Rencana yang sudah TERBUKTI, dijalankan ulang tanpa model (Fase 25).

Fase 26 membuat Jarvis menebak *tool mana* untuk perintah yang mirip. Fase ini
menghapus tebakannya sama sekali untuk perintah yang **persis sama**: urutan
tool + argumen yang kemarin terbukti berhasil dijalankan langsung, tanpa satu
pun panggilan model.

**Kuncinya aliran token, bukan kemiripan.** ``local_embed.tokens`` membuang
kata sopan dan mengupas imbuhan, jadi "tolong bukakan kameranya" dan "buka
kamera" adalah perintah yang sama — tetapi setiap kata isi harus tetap sama.
Itu batas keras yang diminta rencananya: *"telepon Honbrew" boleh; "telepon
Honbru" yang mirip tidak boleh langsung jalan dari cache.* Satu huruf
memisahkan menelepon orang yang benar dari menelepon orang yang salah, dan
kemiripan tidak boleh menjembataninya.

Tiga hal yang sengaja TIDAK disimpan:

* **Argumen yang teraudit.** ``record_tool`` dan ``record_evidence`` keduanya
  menerima argumen yang sudah diredaksi; menyimpan itu berarti menjalankan
  ulang nilai bertopeng. Rencana yang argumennya berubah saat diaudit ditolak
  seluruhnya, bukan disimpan sebagian.
* **Rencana panjang.** Lebih dari beberapa langkah berarti modelnya sedang
  memutuskan sesuatu di tengah jalan, dan keputusan itu tidak ada di sini.
* **Kalimat hasilnya.** Kalimat kemarin bisa memuat fakta kemarin. Yang
  diucapkan harus hasil run hari ini.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

from jarvis.core import config, local_embed, log

from jarvis.core import quiet
_logger = log.get("agent.command_plan")
_lock = threading.Lock()

MAX_ENTRIES = 200
MAX_STEPS = 3
#: Hasil yang lebih panjang dari ini berarti modelnya sedang MERANGKAI jawaban,
#: bukan sekadar bertindak. Merangkai tidak bisa diulang dari cache.
MAX_DISPLAY_CHARS = 200
MAX_ARGS_CHARS = 2000


def _db_path():
    from jarvis.agent.paths import db_path

    return db_path()


def enabled() -> bool:
    try:
        return bool(config.get("agent.command_plan.enabled", True))
    except Exception:                                        # noqa: BLE001
        return True


def key(command) -> str:
    """Kunci pencocokan: aliran token ternormalisasi, bukan teks mentah."""
    return " ".join(local_embed.tokens(command))


def _conn():
    connection = sqlite3.connect(_db_path())
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("""
        CREATE TABLE IF NOT EXISTS command_plan (
            key TEXT PRIMARY KEY,
            command TEXT NOT NULL,
            steps TEXT NOT NULL,
            used_at REAL
        )""")
    return connection


def _audited_unchanged(tool: str, args: dict) -> bool:
    """Argumen ini selamat melewati audit tanpa berubah?

    Bila tidak, yang tersimpan adalah nilai bertopeng — dan menjalankannya
    besok lebih buruk daripada tidak menyimpan apa pun.
    """
    try:
        from jarvis.agent.registry import _audit_args

        return _audit_args(tool, dict(args)) == dict(args)
    except Exception:                                        # noqa: BLE001
        return False


def _clean_steps(steps) -> list[dict] | None:
    if not isinstance(steps, (list, tuple)) or not steps:
        return None
    if len(steps) > MAX_STEPS:
        return None
    cleaned: list[dict] = []
    for raw in steps:
        if not isinstance(raw, dict):
            return None
        tool = str(raw.get("tool", "") or "").strip()
        args = raw.get("args")
        if not tool or not isinstance(args, dict):
            return None
        if not _audited_unchanged(tool, args):
            return None
        display = str(raw.get("display", "") or "").strip()
        if not display or len(display) > MAX_DISPLAY_CHARS:
            return None
        try:
            encoded = json.dumps(args, ensure_ascii=False)
        except (TypeError, ValueError):
            return None
        if len(encoded) > MAX_ARGS_CHARS:
            return None
        cleaned.append({"tool": tool, "args": json.loads(encoded),
                        "display": display})
    return cleaned


def remember(command, steps) -> bool:
    """Simpan satu rencana yang sudah terbukti. ``False`` bila tidak layak."""
    try:
        if not enabled():
            return False
        identifier = key(command)
        cleaned = _clean_steps(steps)
        if not identifier or cleaned is None:
            return False
        with _lock, _conn() as connection:
            connection.execute(
                "INSERT INTO command_plan (key, command, steps, used_at) "
                "VALUES (?, ?, ?, ?) ON CONFLICT(key) DO UPDATE SET "
                "command = excluded.command, steps = excluded.steps, "
                "used_at = excluded.used_at",
                (identifier, " ".join(str(command or "").split())[:400],
                 json.dumps(cleaned, ensure_ascii=False), time.time()))
            connection.execute(
                "DELETE FROM command_plan WHERE key NOT IN ("
                "  SELECT key FROM command_plan "
                "  ORDER BY used_at DESC LIMIT ?)", (MAX_ENTRIES,))
        _logger.info("command_plan.learned", key=identifier[:60],
                     steps=[step["tool"] for step in cleaned])
        return True
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("command_plan.remember_failed", error=str(exc)[:120])
        return False


def recall(command) -> list[dict] | None:
    """Rencana untuk perintah yang PERSIS sama, atau ``None``."""
    try:
        if not enabled():
            return None
        identifier = key(command)
        if not identifier:
            return None
        with _lock, _conn() as connection:
            row = connection.execute(
                "SELECT steps FROM command_plan WHERE key = ?",
                (identifier,)).fetchone()
        if row is None:
            return None
        steps = _clean_steps(json.loads(row[0]))
        if steps is None:
            return None
        return steps
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("command_plan.recall_failed", error=str(exc)[:120])
        return None


def touch(command) -> None:
    """Tandai rencana baru dipakai supaya bukan dia yang dibuang duluan."""
    try:
        with _lock, _conn() as connection:
            connection.execute(
                "UPDATE command_plan SET used_at = ? WHERE key = ?",
                (time.time(), key(command)))
    except Exception as exc:                                        # noqa: BLE001
        quiet.swallowed("agent.command_plan.touch_failed", exc)


def forget(command) -> None:
    """Buang rencana yang ternyata sudah basi."""
    try:
        with _lock, _conn() as connection:
            connection.execute("DELETE FROM command_plan WHERE key = ?",
                               (key(command),))
    except Exception as exc:                                        # noqa: BLE001
        quiet.swallowed("agent.command_plan.forget_failed", exc)


def count() -> int:
    try:
        with _lock, _conn() as connection:
            return int(connection.execute(
                "SELECT COUNT(*) FROM command_plan").fetchone()[0])
    except Exception:                                        # noqa: BLE001
        return 0


def reset() -> None:
    try:
        with _lock, _conn() as connection:
            connection.execute("DELETE FROM command_plan")
    except Exception as exc:                                        # noqa: BLE001
        quiet.swallowed("agent.command_plan.reset_failed", exc)


__all__ = ["MAX_ARGS_CHARS", "MAX_DISPLAY_CHARS", "MAX_ENTRIES", "MAX_STEPS",
           "count", "enabled", "forget", "key", "recall", "remember", "reset",
           "touch"]
