"""Deprecated Hermes action kept as an inert compatibility boundary.

Masih dapat diimpor oleh jalur kompatibilitas lama dan tes. Gemini Live tidak
lagi mengekspos tool ``hermes_agent``; UI desktop lama masih memiliki
``Intent.HERMES_TASK`` selama migrasi, tetapi guard default-off di bawah
mencegah entry itu menyentuh CLI.

Saat ``hermes.enabled`` false (default MK50), semua mode berhenti sebelum
resolusi executable, dispatch thread, atau subprocess. Modul tidak dihapus
agar import lama tetap aman selama migrasi ke agent native Jarvis.

Mode legacy (hanya jika feature flag dinyalakan eksplisit):
  send   → Tier 2: hermes send (no-LLM, ~1 s, blocking singkat OK)
  task   → Tier 3: dispatch_async (ACK instan, hasil via callback/BUS)
  status → info ketersediaan bridge

Return string ringkas — kontrak yang sama dengan action module lain
(open_app, weather_action, dst) sehingga Gemini Live bisa mengucapkannya.
"""
from __future__ import annotations

from jarvis.core import log, quiet
from jarvis.integrations.hermes.async_dispatch import dispatch_async
from jarvis.integrations.hermes.bridge import HermesBridge, is_enabled

_logger = log.get("action.hermes")


def _ui_log(player, msg: str) -> None:
    try:
        if player is not None and hasattr(player, "write_log"):
            player.write_log(msg)
    except Exception as exc:                                # noqa: BLE001
        quiet.swallowed("actions.hermes.ui_log_failed", exc)


def hermes_action(parameters: dict | None = None, player=None,
                  speak=None, **_kw) -> str:
    """Entry point. parameters:
      mode:   'send' | 'task' | 'status'   (default 'task')
      task:   teks tugas (mode task)
      target: 'telegram' | 'discord:#ops' | ... (mode send)
      text:   isi pesan (mode send)
    """
    params = parameters or {}
    mode = str(params.get("mode", "task")).lower().strip()

    if not is_enabled():
        msg = ("Integrasi Hermes dinonaktifkan. "
               "Gunakan agent native Jarvis untuk menjalankan tugas ini.")
        _ui_log(player, f"SYS: {msg}")
        return msg

    bridge = HermesBridge.get()

    if mode == "status":
        c = bridge.check()
        state = bridge.circuit.state
        msg = (f"Hermes {'tersedia' if c['ok'] else 'TIDAK tersedia'} — "
               f"{c['detail']} (circuit: {state})")
        _ui_log(player, f"SYS: {msg}")
        return msg

    if mode == "send":
        target = str(params.get("target", "telegram")).strip()
        text = str(params.get("text", "")).strip()
        if not text:
            return "Pesan kosong — tidak ada yang dikirim."
        if not bridge.available():
            return ("Hermes tidak tersedia saat ini. "
                    "Gunakan pengirim bawaan atau coba lagi nanti.")
        _ui_log(player, f"SYS: Hermes send → {target}")
        r = bridge.send_direct(target, text)
        if r["ok"]:
            return f"Pesan terkirim ke {target}."
        return f"Gagal mengirim ke {target}: {r.get('error') or r['stderr'][:120]}"

    # mode == "task" (default) — Tier 3 async
    task = str(params.get("task", "")).strip()
    if not task:
        return "Tidak ada tugas yang diberikan untuk Hermes."

    def _on_done(text: str):
        short = text if len(text) <= 400 else text[:400] + " …"
        _ui_log(player, f"Hermes: {text}")
        if speak:
            try:
                speak(f"Tugas selesai. {short}")
            except Exception as exc:                        # noqa: BLE001
                quiet.swallowed("actions.hermes.speak_done_failed", exc)

    def _on_error(err: str):
        _ui_log(player, f"ERR: hermes task — {err[:160]}")
        if speak:
            try:
                speak("Maaf, tugas Hermes gagal diselesaikan.")
            except Exception as exc:                        # noqa: BLE001
                quiet.swallowed("actions.hermes.speak_error_failed", exc)

    started = dispatch_async(task, on_done=_on_done, on_error=_on_error)
    if not started:
        if not bridge.available():
            return ("Hermes tidak tersedia — CLI tidak ditemukan atau "
                    "sedang bermasalah. Tugas tidak dijalankan.")
        return "Tugas yang sama masih berjalan. Mohon tunggu."
    _ui_log(player, f"SYS: Hermes task dimulai — {task[:80]}")
    # String ini diucapkan Gemini Live sebagai ACK instan; hasil menyusul
    # lewat speak() callback ketika worker selesai.
    return ("Tugas sedang dikerjakan Hermes di latar belakang. "
            "Saya akan melapor begitu selesai.")
