"""Gerbang ucapan task-result: hasil tugas tidak lagi memotong giliran suara.

Akar N-1 (audit master 2026-08-24): ``JarvisLive.speak`` (main.py, FROZEN)
mengirim hasil tool/agent ke Gemini Live dengan ``turn_complete=True`` SEKET,
tanpa melihat ``_is_speaking`` maupun isi ``audio_in_queue``. Ketika Jarvis
masih membacakan ACK/narasi, konten baru menimpa giliran yang sedang berjalan
dan kalimat terpotong di tengah.

Modul ini memasang ulang ``speak`` versi gerbang lewat seam idempoten — file
FROZEN tidak disentuh, sha tetap. Aturannya sengaja SEMPIT:

- Hanya panggilan TANPA delivery scope yang digerbangkan. Ucapan ber-scope
  (ack/final/konfirmasi via ``window._speak_line``) sudah diserialisasi
  SpeechQueue Fase 28 dan punya kontrak supersede sendiri — jangan dilipat
  dua kali.
- Bila lane sedang bicara, teks ditahan sampai drain terverifikasi
  (``voice_speech.turn_boundary_safe``), lalu dikirim apa adanya. Urutan
  antrean FIFO; tidak ada item yang dibuang — pembuangan adalah ranah
  SpeechQueue, bukan gerbang ini.

Aman & idempoten: gagal apa pun → biarkan perilaku lama, jangan crash.
"""
from __future__ import annotations

import threading

from jarvis.core import config, log
from jarvis.integrations import voice_speech

_logger = log.get("voice.speech_gate")

_MARKER = "_jarvis_speech_gate"


def _lane_busy(live) -> bool:
    """Sedang bicara ATAU masih ada audio lokal yang belum dimainkan."""
    if bool(getattr(live, "_is_speaking", False)):
        return True
    queue = getattr(live, "audio_in_queue", None)
    if queue is not None:
        try:
            return not queue.empty()
        except Exception:                                    # noqa: BLE001
            return False
    return False


class _SpeechGate:
    """Satu penahan per instance Live. Thread-safe dari worker mana pun."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._pending: list[str] = []
        self._draining = False

    def hold_or_send(self, live, original_speak, text: str) -> None:
        text = str(text or "")
        if not _lane_busy(live):
            original_speak(live, text)
            return
        with self._lock:
            self._pending.append(text)
        # Pekerja lain yang sedang menunggu drain membangunkan rantai ini.
        threading.Thread(target=self._drain, args=(live, original_speak),
                         daemon=True, name="jarvis-speech-gate").start()

    def _drain(self, live, original_speak) -> None:
        with self._lock:
            if self._draining:
                return                       # satu drainer cukup untuk semua
            self._draining = True
        try:
            while True:
                if not self._await_boundary(live):
                    # Timeout: jangan tahan ucapan selamanya — kirim apa adanya
                    # supaya hasil tidak hilang; pemotongan buruk lebih baik
                    # daripada hasil yang tak pernah sampai.
                    _logger.warning("voice.speech_gate.boundary_timeout")
                with self._lock:
                    if not self._pending:
                        return
                    text = self._pending.pop(0)
                try:
                    original_speak(live, text)
                except Exception as exc:                     # noqa: BLE001
                    _logger.warning("voice.speech_gate.send_failed",
                                    error=type(exc).__name__)
                    return
        finally:
            with self._lock:
                self._draining = False

    @staticmethod
    def _await_boundary(live) -> bool:
        """Tunggu lane kosong + batas giliran aman. Batas atas dari config."""
        timeout_s = float(config.get("voice.speech_gate.max_hold_s", 20.0))
        poll_s = float(config.get("voice.speech_gate.poll_s", 0.05))
        waited = 0.0
        import time
        while waited < timeout_s:
            if not _lane_busy(live) and voice_speech.turn_boundary_safe(live):
                return True
            time.sleep(poll_s)
            waited += poll_s
        return False


def install(legacy_module) -> bool:
    """Pasang gerbang pada legacy.JarvisLive.speak. True bila terpasang."""
    try:
        cls = legacy_module.JarvisLive
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("voice.speech_gate.no_class", error=str(exc)[:120])
        return False
    if getattr(cls, _MARKER, False):
        return True
    original_speak = getattr(cls, "speak", None)
    if not callable(original_speak):
        _logger.warning("voice.speech_gate.no_speak")
        return False

    gate = _SpeechGate()

    def speak(self, text, *args, **kwargs):
        # Ucapan ber-delivery-scope (ack/final/confirm via SpeechQueue §28)
        # sudah terserialisasi di hulu — gerbang hanya menjaga jalur telanjang
        # (hasil tool/agent langsung dari loop receive).
        from jarvis.integrations.voice_speech import current_delivery_scope
        if current_delivery_scope() is not None:
            return original_speak(self, text, *args, **kwargs)
        return gate.hold_or_send(self, original_speak, text)

    speak.__name__ = getattr(original_speak, "__name__", "speak")
    cls.speak = speak
    cls._jarvis_speech_gate = True
    _logger.info("voice.speech_gate.installed")
    return True


__all__ = ["install"]
