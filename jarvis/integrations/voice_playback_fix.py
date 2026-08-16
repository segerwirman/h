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
from jarvis.integrations import voice_playback_level, voice_speech

_logger = log.get("voice.playback_fix")


def install(legacy_module) -> bool:
    """Pasang _play_audio drain-aware pada legacy.JarvisLive. True bila sukses."""
    try:
        cls = legacy_module.JarvisLive
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("voice.playback_fix.no_class", error=str(exc)[:120])
        return False
    if getattr(cls, "_jarvis_playback_fix", False):
        voice_playback_level.mark_installed()
        return True

    voice_playback_level.mark_uninstalled()

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
        stream = None
        silent_since = None
        playback_epoch = None
        try:
            stream = sd.RawOutputStream(
                samplerate=rate, channels=channels,
                dtype="int16", blocksize=block)
            stream.start()
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
                            # Drain buffer internal stream sebelum flip state.
                            # Kegagalan tail berarti audible completion belum
                            # terverifikasi dan harus melalui jalur abort.
                            tail = b"\x00" * (block * channels * 2)
                            await asyncio.to_thread(stream.write, tail)
                            self.set_speaking(False)
                            # Record the authoritative local drain before the
                            # frozen compatibility event is cleared.  Notice
                            # arbiters retain this boundary durably and can flush
                            # after playback instead of racing the transient event.
                            drained_epoch = playback_epoch
                            voice_speech.playback_drained(
                                self, epoch=drained_epoch)
                            voice_playback_level.mark_drained(
                                epoch=drained_epoch)
                            self._turn_done_event.clear()
                            playback_epoch = None
                            silent_since = None
                    continue
                silent_since = None
                current_epoch = voice_speech.active_playback_epoch(self)
                if current_epoch is not None and current_epoch != playback_epoch:
                    playback_epoch = current_epoch
                await asyncio.to_thread(stream.write, chunk)
                voice_playback_level.mark_started(epoch=playback_epoch)
                # Hanya PCM yang benar-benar berhasil ditulis yang dapat
                # membuktikan bahwa ticket menghasilkan audio lokal.
                voice_speech.mark_audio(self, epoch=playback_epoch)
                self.set_speaking(True)
        except asyncio.CancelledError:
            raise
        except Exception as e:                               # noqa: BLE001
            print(f"[JARVIS] ❌ Play: {e}")
            raise
        finally:
            self.set_speaking(False)
            voice_speech.abort(self, epoch=playback_epoch)
            voice_playback_level.mark_aborted(epoch=playback_epoch)
            if stream is not None:
                try:
                    stream.stop()
                    stream.close()
                except Exception as exc:                     # noqa: BLE001
                    _logger.warning(
                        "voice.playback_fix.close_failed",
                        error=type(exc).__name__,
                    )

    wrapped_play = voice_playback_level.compose(_play_audio)
    wrapped_play._jarvis_playback_fix = True
    cls._play_audio = wrapped_play
    cls._jarvis_playback_fix = True
    voice_playback_level.mark_installed()
    _logger.info("voice.playback_fix.installed", grace_s=grace_s)
    return True
