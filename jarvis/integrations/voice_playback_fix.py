"""Perbaikan pemutaran audio Gemini Live tanpa menyentuh file FROZEN.

Akar 'kosakata terpotong' saat SUARA JARVIS (audit voice):
- ``JarvisLive._play_audio`` (main.py, FROZEN) hanya menunggu 100 ms; bila chunk
  audio terakhir telat tiba (jitter/GC) sementara ``_turn_done_event`` sudah
  di-set dan antrean sesaat kosong, ia menyatakan giliran selesai lalu balik ke
  LISTENING di TENGAH ucapan — ekor kalimat hilang.
- Stream ditutup di ``finally`` tanpa men-drain buffer internal → blok terakhir
  ikut terpotong.

Modul ini memasang ulang ``_play_audio`` versi drain-aware lewat installer seam
yang idempoten. File FROZEN tidak diubah, sha tetap.
Aman & idempotent: gagal apa pun → biarkan perilaku lama, jangan crash.
"""
from __future__ import annotations

import asyncio

from jarvis.core import config, log

_logger = log.get("voice.playback_fix")


def install(legacy_module) -> bool:
    """Pasang _play_audio drain-aware pada legacy.JarvisLive. True bila sukses."""
    try:
        cls = legacy_module.JarvisLive
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("voice.playback_fix.no_class", error=str(exc)[:120])
        return False
    if getattr(cls, "_jarvis_playback_fix", False):
        return True

    sd = getattr(legacy_module, "sd", None)
    rate = int(getattr(legacy_module, "RECEIVE_SAMPLE_RATE", 24000))
    channels = int(getattr(legacy_module, "CHANNELS", 1))
    block = int(getattr(legacy_module, "CHUNK_SIZE", 1024))
    if sd is None:
        _logger.warning("voice.playback_fix.no_sounddevice")
        return False

    # Grace lebih panjang dari 100 ms agar ekor kalimat tidak dianggap selesai
    # hanya karena jitter jaringan sesaat. Bisa dikonfigurasi.
    grace_s = float(config.get("voice.playback.tail_grace_s", 0.45))
    poll_s = float(config.get("voice.playback.poll_s", 0.05))

    async def _play_audio(self):                             # noqa: ANN001
        print("[JARVIS] 🔊 Play started (drain-aware)")
        stream = sd.RawOutputStream(
            samplerate=rate, channels=channels, dtype="int16", blocksize=block)
        stream.start()
        silent_since = None
        try:
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.audio_in_queue.get(), timeout=poll_s)
                except asyncio.TimeoutError:
                    done = bool(self._turn_done_event
                                and self._turn_done_event.is_set())
                    empty = self.audio_in_queue.empty()
                    if done and empty:
                        # Jangan langsung tutup giliran: beri grace agar chunk
                        # ekor yang telat sempat masuk. Hanya setelah antrean
                        # tetap kosong SEPANJANG grace, giliran benar selesai.
                        loop = asyncio.get_event_loop()
                        now = loop.time()
                        if silent_since is None:
                            silent_since = now
                        elif now - silent_since >= grace_s:
                            # Drain buffer internal stream sebelum flip state,
                            # tulis sedikit keheningan agar blok akhir keluar
                            # penuh (bukan terpotong).
                            try:
                                tail = b"\x00" * (block * channels * 2)
                                await asyncio.to_thread(stream.write, tail)
                            except Exception:                # noqa: BLE001
                                pass
                            self.set_speaking(False)
                            self._turn_done_event.clear()
                            silent_since = None
                    continue
                silent_since = None
                self.set_speaking(True)
                try:
                    await asyncio.to_thread(stream.write, chunk)
                except (RuntimeError, asyncio.CancelledError):
                    break
        except Exception as e:                               # noqa: BLE001
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            # Drain sisa buffer sebelum menutup agar tidak ada blok yang hilang.
            try:
                tail = b"\x00" * (block * channels * 2)
                await asyncio.to_thread(stream.write, tail)
            except Exception:                                # noqa: BLE001
                pass
            try:
                stream.stop()
                stream.close()
            except Exception:                                # noqa: BLE001
                pass

    _play_audio._jarvis_playback_fix = True
    cls._play_audio = _play_audio
    cls._jarvis_playback_fix = True
    _logger.info("voice.playback_fix.installed", grace_s=grace_s)
    return True
