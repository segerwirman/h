"""Pengaman lane suara: shutdown berkonfirmasi + close_app bernama.

DIAGNOSIS_2 MASALAH 3 menemukan dua cacat di sesi Gemini Live:

* ``shutdown_jarvis`` (``main.py:436-448``) dideskripsikan sebagai *"close the
  assistant … ANY language"*, sehingga kata Indonesia "tutup" jadi kandidat
  langsung. Handler-nya (``main.py:966-973``) langsung ``os._exit(0)`` tanpa
  konfirmasi dan tanpa cleanup (temuan L-2).
* Tidak ada tool untuk menutup aplikasi **bernama**, sehingga model terpaksa
  menebak ke ``computer_settings`` → Alt+F4 buta.

Keduanya diperbaiki lewat seam yang sudah terbukti (Fase 3 / voice_clarify):
deklarasi disuntik in-place dan ``_execute_tool`` dibungkus dari luar.
``main.py`` TIDAK DISENTUH — verify_frozen tetap hijau.

Konfirmasi shutdown memakai dua langkah: panggilan pertama hanya MEMINTA
konfirmasi, panggilan kedua dalam jendela waktu pendek baru mengeksekusi.
Model tidak bisa melewatinya dengan parameter apa pun.
"""
from __future__ import annotations

import threading
import time

from jarvis.core import log, process_guard

_logger = log.get("voice.safety")

SAFETY_TOOL_NAMES = frozenset({"shutdown_jarvis", "close_app"})

CONFIRM_WINDOW_S = 120.0

_lock = threading.RLock()
_pending_since: float | None = None

_SHUTDOWN_DECLARATION = {
    "name": "shutdown_jarvis",
    "description": (
        "HANYA untuk mematikan Jarvis sendiri, atas permintaan langsung user "
        "('matikan dirimu', 'tutup jarvis'). JANGAN PERNAH pakai ini untuk "
        "menutup aplikasi lain — pakai close_app. JANGAN pakai kalau user "
        "menyebut nama aplikasi apa pun. Panggilan pertama hanya meminta "
        "konfirmasi; user harus menyetujui sebelum Jarvis benar-benar berhenti."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "confirmed": {
                "type": "STRING",
                "description": (
                    "Isi 'yes' HANYA setelah user menyetujui secara eksplisit "
                    "pada giliran sebelumnya"
                ),
            }
        },
    },
}

_CLOSE_APP_DECLARATION = {
    "name": "close_app",
    "description": (
        "Tutup aplikasi LAIN yang sedang berjalan, berdasarkan namanya "
        "(mis. 'instagram', 'chrome'). Selalu menutup dengan anggun dulu "
        "sehingga aplikasi masih bisa menawarkan simpan. Pakai ini untuk "
        "SEMUA permintaan 'tutup <nama aplikasi>' — jangan pernah memakai "
        "computer_settings atau shutdown_jarvis untuk itu."
    ),
    "parameters": {
        "type": "OBJECT",
        "properties": {
            "name": {"type": "STRING",
                     "description": "Nama aplikasinya, mis. 'Instagram'"},
            "force": {"type": "STRING",
                      "description": "'yes' hanya bila user bilang 'paksa'"},
            "all_windows": {"type": "STRING",
                            "description": "'yes' bila user bilang 'semua'"},
        },
        "required": ["name"],
    },
}

_SAFETY_RULES = """

[MENUTUP SESUATU]
- "tutup <nama aplikasi>" -> close_app. SELALU. Jangan pernah memakai
  computer_settings atau shutdown_jarvis untuk menutup aplikasi lain.
- "tutup aplikasi" / "tutup jendela ini" tanpa menyebut nama -> clarify dulu.
  JANGAN menganggap jendela yang sedang aktif sebagai target: jendela aktif
  sering kali saya sendiri.
- shutdown_jarvis HANYA kalau user jelas meminta SAYA berhenti
  ("matikan dirimu", "tutup jarvis"). Itu pun saya minta konfirmasi dulu.
- Kalau permintaan menutup ditolak karena targetnya saya sendiri, jelaskan
  apa adanya dan tawarkan alternatif — jangan mencoba jalur lain.
"""


# ── konfirmasi shutdown ──────────────────────────────────────────────────

def _confirm_pending() -> bool:
    with _lock:
        if _pending_since is None:
            return False
        if (time.monotonic() - _pending_since) > CONFIRM_WINDOW_S:
            return False
        return True


def _arm_confirmation() -> None:
    global _pending_since
    with _lock:
        _pending_since = time.monotonic()


def reset_confirmation() -> None:
    global _pending_since
    with _lock:
        _pending_since = None


def graceful_shutdown(live=None) -> None:
    """Ganti ``os._exit(0)`` (temuan L-2) dengan penutupan tertib.

    Urutannya penting: lepas perangkat dulu (kamera bisa menggantung di
    driver), baru flush basis data, baru keluar.
    """
    _logger.info("safety.shutdown.begin")

    try:
        from jarvis.agent import dispatch
        cancelled = dispatch.cancel_all()
        if cancelled:
            _logger.info("safety.shutdown.tasks_cancelled", count=cancelled)
    except Exception:                                        # noqa: BLE001
        pass

    for step, fn in (
        ("communication", _stop_communication_mode),
        ("vision", _stop_vision),
        ("live", lambda: _stop_live(live)),
        ("sqlite", _flush_sqlite),
    ):
        try:
            fn()
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("safety.shutdown.step_failed", step=step,
                            error=str(exc)[:120])

    _logger.info("safety.shutdown.done")

    def _exit() -> None:
        time.sleep(1.0)
        import os
        os._exit(0)

    threading.Thread(target=_exit, daemon=True, name="jarvis-exit").start()


def _stop_communication_mode() -> None:
    from jarvis.integrations.whatsapp_voice import _shutdown_existing

    _shutdown_existing()
    from jarvis.agent.communication_mode import exit
    exit()


def _stop_vision() -> None:
    from jarvis.vision import process as vision_process

    stop = getattr(vision_process, "stop", None) or getattr(
        vision_process, "shutdown", None)
    if callable(stop):
        stop()


def _stop_live(live) -> None:
    if live is None:
        return
    request_stop = getattr(live, "request_stop", None)
    if callable(request_stop):
        request_stop()


def _flush_sqlite() -> None:
    """WAL checkpoint agar tulisan terakhir benar-benar mendarat di disk."""
    import sqlite3

    from jarvis.agent.paths import db_path

    conn = sqlite3.connect(db_path())
    try:
        conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        conn.commit()
    finally:
        conn.close()


# ── penanganan tool ──────────────────────────────────────────────────────

def handle_shutdown(args: dict, live=None) -> tuple[str, bool]:
    """``(pesan, ok)``. Konfirmasi tidak bisa dilewati parameter apa pun."""
    approved = str(args.get("confirmed", "")).strip().lower() in (
        "yes", "true", "1", "ya", "confirm", "konfirmasi")
    if approved and _confirm_pending():
        reset_confirmation()
        graceful_shutdown(live)
        return ("Baik. Saya menutup semuanya dengan rapi sekarang.", True)

    _arm_confirmation()
    return ("Konfirmasi dulu ke user: apakah benar ingin saya berhenti "
            "sepenuhnya? Tanyakan dalam satu kalimat. Setelah user menyetujui, "
            "panggil shutdown_jarvis lagi dengan confirmed='yes'.", True)


def handle_close_app(args: dict) -> tuple[str, bool]:
    from actions.close_app import STATUS_CLOSED, close_app

    def _flag(key: str) -> bool:
        return str(args.get(key, "")).strip().lower() in (
            "yes", "true", "1", "ya", "paksa", "semua")

    outcome = close_app(str(args.get("name") or ""), force=_flag("force"),
                        all_windows=_flag("all_windows"))
    return (outcome.message, outcome.status == STATUS_CLOSED)


def declarations() -> list[dict]:
    return [dict(_SHUTDOWN_DECLARATION), dict(_CLOSE_APP_DECLARATION)]


def apply_to_prompt(base: str) -> str:
    """Tambahkan aturan safety tepat sekali tanpa mengubah persona dasar."""
    return base if "[MENUTUP SESUATU]" in base else base + _SAFETY_RULES


__all__ = ["apply_to_prompt", "declarations", "handle_shutdown",
           "handle_close_app", "graceful_shutdown", "reset_confirmation",
           "SAFETY_TOOL_NAMES", "CONFIRM_WINDOW_S", "process_guard"]
