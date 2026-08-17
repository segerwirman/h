"""Fase 46B contracts for callback/queue/send input heartbeat."""
from __future__ import annotations

import asyncio
from contextlib import suppress
from dataclasses import FrozenInstanceError
import threading
from types import SimpleNamespace

import pytest

from jarvis.integrations import voice_input_owner, voice_live_transport


@pytest.fixture(autouse=True)
def _default_fake_device(monkeypatch):
    from jarvis.core import config

    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: None
        if key == "voice.audio.input_device" else default,
    )


class _Clock:
    def __init__(self, now: float = 10.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


class _Input:
    def __init__(self, pcm: bytes):
        self._pcm = pcm

    def tobytes(self) -> bytes:
        return self._pcm


class _Stream:
    def __init__(self, sd, **kwargs):
        self._sd = sd
        self._callback = kwargs["callback"]

    def __enter__(self):
        self._sd.callback = self._callback
        return self

    def __exit__(self, *_args):
        return False


class _SoundDevice:
    def __init__(self):
        self.callback = None

    def query_devices(self, device=None, kind=None):
        info = {
            "name": "fake mic",
            "max_input_channels": 1,
            "max_output_channels": 0,
            "hostapi": 0,
        }
        if device is not None or kind == "input":
            return info
        return [info]

    def check_input_settings(self, **_kwargs):
        return None

    def InputStream(self, **kwargs):
        return _Stream(self, **kwargs)


def _legacy(sd):
    class Live:
        def __init__(self, *, muted: bool = False):
            self.ui = SimpleNamespace(
                _win=SimpleNamespace(_voice_capture_generation=0),
                muted=muted,
            )
            self.out_queue = asyncio.Queue(maxsize=1)
            self._speaking_lock = threading.Lock()
            self._is_speaking = False
            self._phone_active = False

        async def _listen_audio(self):
            raise AssertionError("input owner was not installed")

        async def _send_realtime(self):
            raise AssertionError("transport was not installed")

        async def _receive_audio(self):
            return None

    return SimpleNamespace(
        JarvisLive=Live,
        sd=sd,
        SEND_SAMPLE_RATE=16000,
        CHANNELS=1,
        CHUNK_SIZE=1024,
    )


async def _start_listener(live, sd):
    task = asyncio.create_task(live._listen_audio())
    for _ in range(10):
        await asyncio.sleep(0)
        if sd.callback is not None:
            return task
    task.cancel()
    with suppress(asyncio.CancelledError):
        await task
    raise AssertionError("fake stream did not open")


def test_snapshot_is_immutable_metadata_without_pcm():
    clock = _Clock()
    heartbeat = voice_input_owner.InputHeartbeat(clock=clock)
    heartbeat.begin_generation(7)
    heartbeat.mark_callback(7, frame_bytes=4)

    snapshot = heartbeat.snapshot()

    assert snapshot.generation == 7
    assert snapshot.stream_opened_at == 10.0
    assert snapshot.callback_at == 10.0
    assert snapshot.callback_count == 1
    assert snapshot.callback_bytes == 4
    assert "pcm" not in repr(snapshot).lower()
    with pytest.raises(FrozenInstanceError):
        snapshot.callback_count = 99


def test_callback_and_delayed_queue_stages_are_independent(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(voice_input_owner.time, "monotonic", clock)
    sd = _SoundDevice()
    legacy = _legacy(sd)
    assert voice_input_owner.install(legacy) is True
    live = legacy.JarvisLive()

    async def exercise():
        task = await _start_listener(live, sd)
        clock.now = 11.0
        sd.callback(_Input(b"1234"), 2, None, None)
        before_delivery = voice_input_owner.heartbeat_snapshot(live)
        await asyncio.sleep(0)
        after_delivery = voice_input_owner.heartbeat_snapshot(live)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return before_delivery, after_delivery

    before, after = asyncio.run(exercise())

    assert before.callback_count == 1
    assert before.callback_at == 11.0
    assert before.queued_count == 0
    assert after.queued_count == 1
    assert after.queued_at == 11.0
    assert after.queued_bytes == 4
    assert after.sent_count == 0


def test_muted_callback_does_not_mark_queued(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(voice_input_owner.time, "monotonic", clock)
    sd = _SoundDevice()
    legacy = _legacy(sd)
    voice_input_owner.install(legacy)
    live = legacy.JarvisLive(muted=True)

    async def exercise():
        task = await _start_listener(live, sd)
        sd.callback(_Input(b"muted"), 3, None, None)
        await asyncio.sleep(0)
        snapshot = voice_input_owner.heartbeat_snapshot(live)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return snapshot

    snapshot = asyncio.run(exercise())

    assert snapshot.callback_count == 1
    assert snapshot.queued_count == 0


def test_successful_send_marks_sent_but_failed_send_does_not(monkeypatch):
    clock = _Clock()
    monkeypatch.setattr(voice_input_owner.time, "monotonic", clock)
    monkeypatch.setattr(voice_live_transport, "install_turn_role", lambda: False)
    legacy = _legacy(_SoundDevice())
    voice_input_owner.install(legacy)
    voice_live_transport.install(legacy)

    class Session:
        def __init__(self):
            self.calls = 0

        async def send_realtime_input(self, **_kwargs):
            self.calls += 1
            if self.calls == 2:
                raise RuntimeError("send failed")

    async def exercise():
        live = legacy.JarvisLive()
        heartbeat = voice_input_owner.input_heartbeat(live)
        heartbeat.begin_generation(3)
        live.session = Session()
        await live.out_queue.put(
            voice_input_owner.VoiceInputMessage(3, b"ok")
        )
        sender = asyncio.create_task(live._send_realtime())
        while live.session.calls < 1:
            await asyncio.sleep(0)
        first = voice_input_owner.heartbeat_snapshot(live)
        clock.now = 12.0
        await live.out_queue.put(
            voice_input_owner.VoiceInputMessage(3, b"bad")
        )
        with pytest.raises(RuntimeError, match="send failed"):
            await sender
        return first, voice_input_owner.heartbeat_snapshot(live)

    first, failed = asyncio.run(exercise())

    assert first.sent_count == 1
    assert first.sent_bytes == 2
    assert failed.sent_count == 1
    assert failed.sent_at == first.sent_at


def test_reopen_resets_snapshot_and_stale_generation_cannot_update():
    clock = _Clock()
    heartbeat = voice_input_owner.InputHeartbeat(clock=clock)
    heartbeat.begin_generation(1)
    heartbeat.mark_callback(1, frame_bytes=3)
    heartbeat.mark_queued(1, frame_bytes=3, at=clock())
    heartbeat.mark_sent(1, frame_bytes=3)

    clock.now = 20.0
    heartbeat.begin_generation(2)
    assert heartbeat.mark_callback(1, frame_bytes=99) is False
    assert heartbeat.mark_queued(1, frame_bytes=99, at=21.0) is False
    assert heartbeat.mark_sent(1, frame_bytes=99) is False

    snapshot = heartbeat.snapshot()
    assert snapshot.generation == 2
    assert snapshot.stream_opened_at == 20.0
    assert snapshot.callback_count == 0
    assert snapshot.queued_count == 0
    assert snapshot.sent_count == 0
    assert 99 not in (
        snapshot.callback_bytes,
        snapshot.queued_bytes,
        snapshot.sent_bytes,
    )
