"""Behavior characterization for the optional WhatsApp virtual-audio bridge."""
from __future__ import annotations

import asyncio
import gc
import queue
import types
import weakref

import pytest

from jarvis.integrations import whatsapp_voice


@pytest.fixture(autouse=True)
def _reset_whatsapp_voice_state(monkeypatch):
    """Keep singleton, weakref, and config state isolated between tests."""
    original_ref = whatsapp_voice._live_ref
    original_legacy = whatsapp_voice._legacy
    original_instance = whatsapp_voice.WhatsAppAudioBridge._instance
    monkeypatch.setattr(whatsapp_voice, "_live_ref", None)
    monkeypatch.setattr(whatsapp_voice, "_legacy", None)
    whatsapp_voice.WhatsAppAudioBridge._instance = None
    yield
    current = whatsapp_voice.WhatsAppAudioBridge._instance
    if current is not None:
        current.stop()
    whatsapp_voice.WhatsAppAudioBridge._instance = original_instance
    whatsapp_voice._live_ref = original_ref
    whatsapp_voice._legacy = original_legacy
    gc.collect()


def _set_config(monkeypatch, values: dict[str, object]) -> None:
    def get(key, default=None):
        return values.get(key, default)

    monkeypatch.setattr(whatsapp_voice.config, "get", get)


class _FakeLive:
    def __init__(self, *, loop=None, out_queue=None):
        self._loop = loop
        self.out_queue = out_queue
        self.audio_in_queue = asyncio.Queue()
        self._phone_active = False

    async def _play_audio(self):
        self.queue_seen = self.audio_in_queue
        return await self.audio_in_queue.get()


class _ErrorPlayLive(_FakeLive):
    async def _play_audio(self):
        self.queue_seen = self.audio_in_queue
        raise RuntimeError("playback failed")


class _CancelPlayLive(_FakeLive):
    async def _play_audio(self):
        self.queue_seen = self.audio_in_queue
        raise asyncio.CancelledError


class _FakeStream:
    def __init__(self, *, fail_start=False, fail_write=False):
        self.fail_start = fail_start
        self.fail_write = fail_write
        self.started = 0
        self.stopped = 0
        self.closed = 0
        self.writes = []

    def start(self):
        self.started += 1
        if self.fail_start:
            raise RuntimeError("stream start failed")

    def stop(self):
        self.stopped += 1

    def close(self):
        self.closed += 1

    def write(self, chunk):
        self.writes.append(chunk)
        if self.fail_write:
            raise RuntimeError("speaker disappeared")


class _FakeSoundDevice:
    def __init__(self, *, input_stream=None, output_stream=None,
                 fail_input=False, fail_output=False):
        self.input_stream = input_stream or _FakeStream()
        self.output_stream = output_stream or _FakeStream()
        self.fail_input = fail_input
        self.fail_output = fail_output
        self.input_kwargs = None
        self.output_kwargs = None

    def RawInputStream(self, **kwargs):
        self.input_kwargs = kwargs
        if self.fail_input:
            raise RuntimeError("input unavailable")
        return self.input_stream

    def RawOutputStream(self, **kwargs):
        self.output_kwargs = kwargs
        if self.fail_output:
            raise RuntimeError("output unavailable")
        return self.output_stream


class _RunningLoop:
    def __init__(self, *, running=True):
        self.running = running
        self.calls = []

    def is_running(self):
        return self.running

    def call_soon_threadsafe(self, callback, *args):
        self.calls.append((callback, args))


class _FakeQueue:
    def __init__(self, items=(), *, maxsize=0):
        self._queue = queue.Queue(maxsize=maxsize)
        for item in items:
            self._queue.put_nowait(item)

    def put_nowait(self, item):
        self._queue.put_nowait(item)

    def get_nowait(self):
        return self._queue.get_nowait()

    def qsize(self):
        return self._queue.qsize()

    def empty(self):
        return self._queue.empty()


def _install(monkeypatch, live_cls=_FakeLive):
    legacy = types.SimpleNamespace(JarvisLive=live_cls)
    whatsapp_voice.install(legacy)
    return legacy


def test_install_is_idempotent_and_tracks_latest_live_instance():
    legacy = _install(pytest.MonkeyPatch())
    first_init = legacy.JarvisLive.__init__
    first_play = legacy.JarvisLive._play_audio

    whatsapp_voice.install(legacy)

    assert legacy.JarvisLive.__init__ is first_init
    assert legacy.JarvisLive._play_audio is first_play
    live = legacy.JarvisLive()
    assert whatsapp_voice._live() is live


def test_live_weakref_does_not_keep_instance_alive():
    legacy = _install(pytest.MonkeyPatch())
    live = legacy.JarvisLive()
    reference = weakref.ref(live)
    assert whatsapp_voice._live() is live

    del live
    gc.collect()

    assert reference() is None
    assert whatsapp_voice._live() is None


def test_tap_queue_inactive_passes_bytes_and_delegates_attributes():
    inner = asyncio.Queue()
    inner.marker = "delegated"
    bridge = types.SimpleNamespace(active=False, tap_output=lambda _chunk: None)
    tap = whatsapp_voice._TapQueue(inner, bridge)
    asyncio.run(inner.put(b"pcm"))

    assert asyncio.run(tap.get()) == b"pcm"
    assert tap.marker == "delegated"


def test_tap_queue_active_mirrors_and_can_replace_local_monitoring_with_silence(
    monkeypatch,
):
    inner = asyncio.Queue()
    captured = []
    bridge = types.SimpleNamespace(active=True, tap_output=captured.append)
    tap = whatsapp_voice._TapQueue(inner, bridge)
    _set_config(monkeypatch, {
        "whatsapp_web.audio_bridge.monitor_local_output": False,
    })
    asyncio.run(inner.put(b"remote-speaker"))

    assert asyncio.run(tap.get()) == b"\0" * len(b"remote-speaker")
    assert captured == [b"remote-speaker"]


def test_playback_queue_restores_after_exception_and_cancellation():
    for live_cls, expected in (
        (_ErrorPlayLive, RuntimeError),
        (_CancelPlayLive, asyncio.CancelledError),
    ):
        live = live_cls()
        original = live.audio_in_queue
        wrapped = whatsapp_voice._TapQueue(original, types.SimpleNamespace(
            active=False, tap_output=lambda _chunk: None,
        ))
        live.audio_in_queue = wrapped
        with pytest.raises(expected):
            asyncio.run(live._play_audio())
        live.audio_in_queue = original
        assert live.audio_in_queue is original


def test_install_wrapper_restores_queue_after_exception_and_cancellation():
    for live_cls, expected in (
        (_ErrorPlayLive, RuntimeError),
        (_CancelPlayLive, asyncio.CancelledError),
    ):
        bridge = types.SimpleNamespace(active=False, tap_output=lambda _chunk: None)
        monkeypatch = pytest.MonkeyPatch()
        monkeypatch.setattr(
            whatsapp_voice.WhatsAppAudioBridge,
            "get",
            classmethod(lambda _cls, bridge=bridge: bridge),
        )
        legacy = _install(monkeypatch, live_cls)
        live = legacy.JarvisLive()
        original = live.audio_in_queue
        with pytest.raises(expected):
            asyncio.run(live._play_audio())
        assert live.audio_in_queue is original
        monkeypatch.undo()


def test_put_live_audio_uses_gemini_pcm_mime_and_drops_oldest_when_full():
    out_queue = _FakeQueue([{"data": b"old", "mime_type": "old"}], maxsize=1)
    instance = types.SimpleNamespace(out_queue=out_queue)

    whatsapp_voice.WhatsAppAudioBridge._put_live_audio(instance, b"new")

    assert out_queue.get_nowait() == {
        "data": b"new",
        "mime_type": "audio/pcm;rate=16000",
    }


def test_capture_callback_only_schedules_when_bridge_and_loop_are_ready():
    loop = _RunningLoop()
    live = _FakeLive(loop=loop, out_queue=_FakeQueue())
    whatsapp_voice._live_ref = weakref.ref(live)
    bridge = whatsapp_voice.WhatsAppAudioBridge()
    bridge._active = True

    bridge._capture_callback(b"input", 1, None, None)

    assert len(loop.calls) == 1
    callback, args = loop.calls[0]
    assert callback is bridge._put_live_audio
    assert args == (live, b"input")


def test_tap_output_ignores_inactive_and_empty_and_drops_oldest():
    bridge = whatsapp_voice.WhatsAppAudioBridge()
    bridge._active = True
    bridge._output_queue = queue.Queue(maxsize=1)
    bridge._output_queue.put_nowait(b"old")

    bridge.tap_output(b"")
    bridge.tap_output(b"new")

    assert bridge._output_queue.get_nowait() == b"new"
    bridge._active = False
    bridge.tap_output(b"ignored")
    assert bridge._output_queue.empty()


def test_start_rejects_disabled_missing_live_and_invalid_devices(monkeypatch):
    bridge = whatsapp_voice.WhatsAppAudioBridge()
    _set_config(monkeypatch, {})
    assert bridge.start()["active"] is False
    assert "nonaktif" in bridge.start()["error"]

    _set_config(monkeypatch, {"whatsapp_web.audio_bridge.enabled": True})
    assert "Gemini Live" in bridge.start()["error"]

    live = _FakeLive(loop=object(), out_queue=object())
    whatsapp_voice._live_ref = weakref.ref(live)
    assert "wajib" in bridge.start()["error"]

    _set_config(monkeypatch, {
        "whatsapp_web.audio_bridge.enabled": True,
        "whatsapp_web.audio_bridge.remote_input_device": "same",
        "whatsapp_web.audio_bridge.remote_output_device": "SAME",
    })
    assert "berbeda" in bridge.start()["error"]


def test_start_stop_are_idempotent_and_configure_distinct_streams(monkeypatch):
    loop = _RunningLoop()
    live = _FakeLive(loop=loop, out_queue=_FakeQueue())
    whatsapp_voice._live_ref = weakref.ref(live)
    input_stream = _FakeStream()
    output_stream = _FakeStream()
    sounddevice = _FakeSoundDevice(
        input_stream=input_stream,
        output_stream=output_stream,
    )
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", sounddevice)
    _set_config(monkeypatch, {
        "whatsapp_web.audio_bridge.enabled": True,
        "whatsapp_web.audio_bridge.remote_input_device": "virtual-in",
        "whatsapp_web.audio_bridge.remote_output_device": "virtual-out",
    })
    bridge = whatsapp_voice.WhatsAppAudioBridge()
    bridge._output_queue.put_nowait(b"stale")

    first = bridge.start()
    second = bridge.start()

    assert first["active"] is True
    assert second["active"] is True
    assert input_stream.started == 1
    assert output_stream.started == 1
    assert sounddevice.input_kwargs["samplerate"] == 16000
    assert sounddevice.output_kwargs["samplerate"] == 24000
    assert live._phone_active is True
    assert bridge._output_queue.empty()

    stopped = bridge.stop()
    stopped_again = bridge.stop()
    assert stopped["active"] is False
    assert stopped_again["active"] is False
    assert live._phone_active is False
    assert input_stream.closed == 1
    assert output_stream.closed == 1


def test_start_partial_failure_closes_created_streams_and_stays_inactive(
    monkeypatch,
):
    live = _FakeLive(loop=_RunningLoop(), out_queue=_FakeQueue())
    whatsapp_voice._live_ref = weakref.ref(live)
    input_stream = _FakeStream()
    sounddevice = _FakeSoundDevice(
        input_stream=input_stream,
        fail_output=True,
    )
    monkeypatch.setitem(__import__("sys").modules, "sounddevice", sounddevice)
    _set_config(monkeypatch, {
        "whatsapp_web.audio_bridge.enabled": True,
        "whatsapp_web.audio_bridge.remote_input_device": "in",
        "whatsapp_web.audio_bridge.remote_output_device": "out",
    })

    bridge = whatsapp_voice.WhatsAppAudioBridge()
    result = bridge.start()

    assert result["active"] is False
    assert bridge._output_thread is None
    assert input_stream.closed == 1
    assert live._phone_active is False


def test_shutdown_existing_does_not_create_singleton(monkeypatch):
    called = []
    monkeypatch.setattr(
        whatsapp_voice.WhatsAppAudioBridge,
        "get",
        classmethod(lambda _cls: called.append(True)),
    )

    whatsapp_voice._shutdown_existing()

    assert called == []


def test_output_worker_failure_runs_full_bridge_cleanup():
    live = _FakeLive(loop=_RunningLoop(), out_queue=_FakeQueue())
    whatsapp_voice._live_ref = weakref.ref(live)
    input_stream = _FakeStream()
    output_stream = _FakeStream(fail_write=True)
    bridge = whatsapp_voice.WhatsAppAudioBridge()
    bridge._active = True
    bridge._input_stream = input_stream
    bridge._output_stream = output_stream
    bridge._output_thread = None
    live._phone_active = True
    bridge._output_queue.put_nowait(b"audio")

    bridge._output_worker()

    assert "speaker disappeared" in bridge.status()["error"]
    assert bridge.status()["active"] is False
    assert live._phone_active is False
    assert input_stream.stopped == 1
    assert input_stream.closed == 1
    assert output_stream.stopped == 1
    assert output_stream.closed == 1
    assert bridge._input_stream is None
    assert bridge._output_stream is None
    assert bridge._output_thread is None
    assert bridge._output_queue.empty()
