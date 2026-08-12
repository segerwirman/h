"""Ukur level audio yang sedang Jarvis putar (Fase 19, S-4).

Barge-in menaikkan ambang sebanding dengan seberapa keras Jarvis berbunyi.
Tanpa angka nyata, satu-satunya default yang aman adalah menganggap volume
PENUH — dan itu membuat ambangnya begitu tinggi sehingga tidak ada yang bisa
memotong. Barge-in "menyala" tetapi mati dalam praktik: kegagalan yang sama,
hanya berganti wajah.

Jadi levelnya diukur, bukan diasumsikan. Seam-nya sudah terbukti dipakai
``whatsapp_voice._TapQueue``: bungkus ``JarvisLive._play_audio`` dari luar dan
intip potongan audio yang lewat. ``main.py`` FROZEN tidak disentuh.

Level meluruh terhadap waktu, sehingga ekor ucapan yang sudah senyap tidak
terus menahan ambang tetap tinggi.
"""
from __future__ import annotations

import math
import threading
import time

from jarvis.core import log

_logger = log.get("voice.playback_level")

_lock = threading.Lock()
_level = 0.0
_updated_at = 0.0
_installed = False

# Setelah sekian detik tanpa potongan audio baru, anggap Jarvis sudah diam.
DECAY_S = 0.45


def note_chunk(chunk: bytes) -> None:
    """Catat satu potongan PCM16 yang sedang diputar. Tidak pernah melempar."""
    global _level, _updated_at
    try:
        if not chunk:
            return
        import numpy as np

        samples = np.frombuffer(chunk, dtype=np.int16)
        if samples.size == 0:
            return
        rms = float(np.sqrt(np.mean(np.square(
            samples.astype(np.float32) / 32768.0))))
        with _lock:
            # Naik cepat, turun lewat decay: echo menyusul audio, bukan
            # mendahuluinya.
            _level = max(rms, _level * 0.6)
            _updated_at = time.monotonic()
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("playback_level.failed", error=str(exc)[:100])


def is_installed() -> bool:
    """Apakah tap sudah terpasang pada pipeline?

    "Belum dipasang" dan "Jarvis sedang diam" DUA HAL BERBEDA. Menyamakannya
    membuat echo guard mati diam-diam — arah gagal yang persis membuat
    barge-in dimatikan sejak awal.
    """
    return _installed


def current_level() -> float:
    """Level playback 0..1 saat ini; 0.0 bila Jarvis sudah diam."""
    with _lock:
        level, at = _level, _updated_at
    if not at:
        return 0.0
    idle = time.monotonic() - at
    if idle >= DECAY_S:
        return 0.0
    # Peluruhan halus sepanjang jendela decay.
    return max(0.0, min(1.0, level * (1.0 - idle / DECAY_S)))


def reset() -> None:
    global _level, _updated_at
    with _lock:
        _level = 0.0
        _updated_at = 0.0


def compose(original):
    """Wrap playback with a level tap without owning the playback method."""
    if not callable(original):
        raise TypeError("playback owner must be callable")
    if getattr(original, "_jarvis_playback_level", False):
        return original

    class _LevelTap:
        """Delegasikan antrean audio sambil mengukur potongan yang lewat."""

        def __init__(self, inner):
            self._inner = inner

        async def get(self):
            chunk = await self._inner.get()
            note_chunk(chunk)
            return chunk

        def __getattr__(self, name):
            return getattr(self._inner, name)

    async def wrapped(self):
        inner = self.audio_in_queue
        proxy = _LevelTap(inner)
        self.audio_in_queue = proxy
        try:
            return await original(self)
        finally:
            if self.audio_in_queue is proxy:
                self.audio_in_queue = inner
            reset()

    wrapped._jarvis_playback_level = True
    return wrapped


def mark_installed() -> None:
    """Mark the level tap active after its playback owner is installed."""
    global _installed
    _installed = True


def mark_uninstalled() -> None:
    """Mark the level tap inactive when its playback owner is unavailable."""
    global _installed
    _installed = False


def install(legacy_module) -> None:
    """Compatibility shim; playback_fix owns the actual installation."""
    from jarvis.integrations import voice_playback_fix

    voice_playback_fix.install(legacy_module)


__all__ = ["DECAY_S", "compose", "current_level", "install", "is_installed",
           "mark_installed", "mark_uninstalled", "note_chunk", "reset"]
