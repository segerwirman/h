"""Perbaikan playback voice: drain-aware, dipasang tanpa menyentuh FROZEN."""
from __future__ import annotations

import asyncio
import types

from jarvis.integrations import voice_playback_fix


class _FakeStream:
    def __init__(self, **kw):
        self.writes = []
        self.stopped = False
        self.closed = False

    def start(self):
        pass

    def write(self, data):
        self.writes.append(bytes(data))

    def stop(self):
        self.stopped = True

    def close(self):
        self.closed = True


class _FakeSD:
    def __init__(self):
        self.last = None

    def RawOutputStream(self, **kw):
        self.last = _FakeStream(**kw)
        return self.last


class _FakeLive:
    def __init__(self):
        self.audio_in_queue = asyncio.Queue()
        self._turn_done_event = asyncio.Event()
        self.speaking = []

    def set_speaking(self, v):
        self.speaking.append(bool(v))


def _make_legacy():
    mod = types.ModuleType("fake_legacy_main")
    mod.sd = _FakeSD()
    mod.RECEIVE_SAMPLE_RATE = 24000
    mod.CHANNELS = 1
    mod.CHUNK_SIZE = 8

    # Subclass segar tiap panggilan agar flag _jarvis_playback_fix dan closure
    # _play_audio tidak bocor antar-test (class object tidak dibagi).
    class _Live(_FakeLive):
        pass

    mod.JarvisLive = _Live
    return mod


def test_install_memonkeypatch_play_audio_idempotent():
    legacy = _make_legacy()
    assert voice_playback_fix.install(legacy) is True
    assert getattr(legacy.JarvisLive, "_jarvis_playback_fix", False) is True
    # idempotent: panggilan kedua tidak menggandakan / tidak error
    assert voice_playback_fix.install(legacy) is True


def test_install_gagal_aman_tanpa_sounddevice():
    mod = types.ModuleType("no_sd")

    class _Live(_FakeLive):
        pass

    mod.JarvisLive = _Live
    # sd tidak ada → tidak crash, kembalikan False, perilaku lama dibiarkan
    assert voice_playback_fix.install(mod) is False


def test_play_audio_mengeluarkan_semua_chunk_dan_drain(monkeypatch):
    # grace kecil + poll kecil agar test cepat & deterministik
    monkeypatch.setattr(voice_playback_fix.config, "get",
                        lambda k, d=None: {"voice.playback.tail_grace_s": 0.02,
                                           "voice.playback.poll_s": 0.01}.get(k, d))
    legacy = _make_legacy()
    voice_playback_fix.install(legacy)
    live = legacy.JarvisLive()

    async def scenario():
        # Dua chunk audio, lalu turn selesai — ekor tidak boleh hilang.
        await live.audio_in_queue.put(b"AB" * 4)
        await live.audio_in_queue.put(b"CD" * 4)
        live._turn_done_event.set()
        task = asyncio.create_task(live._play_audio())
        await asyncio.sleep(0.15)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    asyncio.run(scenario())
    stream = legacy.sd.last
    # Kedua chunk audio benar-benar ditulis (tidak terpotong di tengah).
    joined = b"".join(stream.writes)
    assert b"AB" * 4 in joined and b"CD" * 4 in joined
    # Ada penulisan keheningan (drain) setelah audio → blok akhir keluar penuh.
    assert any(set(w) == {0} for w in stream.writes)
    # State speaking sempat True lalu kembali False (giliran ditutup rapi).
    assert True in live.speaking and live.speaking[-1] is False
