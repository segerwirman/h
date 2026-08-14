"""RED-first characterization of Gemini Live transport lifecycle edges."""
from __future__ import annotations

import asyncio
import types

import pytest

from jarvis.integrations import voice_live_transport


class _Live:
    async def _send_realtime(self):
        raise AssertionError("transport adapter was not installed")

    async def _receive_audio(self):
        return None


class _RecordingSession:
    def __init__(self, expected: int):
        self.expected = expected
        self.sent: list[dict] = []
        self.complete = asyncio.Event()

    async def send_realtime_input(self, **kwargs):
        self.sent.append(kwargs)
        if len(self.sent) == self.expected:
            self.complete.set()


def _installed_live():
    live_cls = type("CharacterizedLive", (_Live,), {})
    legacy = types.SimpleNamespace(JarvisLive=live_cls)
    assert voice_live_transport.install(legacy) is True
    return live_cls


def test_multiple_outbound_frames_are_normalised_and_routed_independently(
    monkeypatch,
):
    monkeypatch.setattr(
        voice_live_transport,
        "install_turn_role",
        lambda: False,
    )
    live_cls = _installed_live()
    messages = [
        {"data": b"bare", "mime_type": "audio/pcm"},
        {"data": b"rated", "mime_type": "audio/pcm;rate=24000"},
        {"data": b"image", "mime_type": "image/jpeg"},
        {"data": b"other", "mime_type": "application/octet-stream"},
    ]

    async def exercise():
        live = live_cls()
        live.out_queue = asyncio.Queue()
        live.session = _RecordingSession(expected=len(messages))
        for message in messages:
            await live.out_queue.put(message)
        sender = asyncio.create_task(live._send_realtime())
        try:
            await asyncio.wait_for(live.session.complete.wait(), timeout=1)
        finally:
            sender.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sender
        return live

    live = asyncio.run(exercise())

    assert live.session.sent == [
        {"audio": {"data": b"bare", "mime_type": "audio/pcm;rate=16000"}},
        {"audio": messages[1]},
        {"video": messages[2]},
        {"media": messages[3]},
    ]
    assert live.session.sent[1]["audio"] is messages[1]
    assert live.session.sent[2]["video"] is messages[2]
    assert live.session.sent[3]["media"] is messages[3]
    assert live._voice_live_last_input == {
        "message_type": "dict",
        "mime_type": "application/octet-stream",
        "bytes": 5,
    }


def test_cancelling_blocked_send_leaves_later_frame_queued(monkeypatch):
    monkeypatch.setattr(
        voice_live_transport,
        "install_turn_role",
        lambda: False,
    )
    live_cls = _installed_live()

    class BlockingSession:
        def __init__(self):
            self.sent: list[dict] = []
            self.entered = asyncio.Event()
            self.release = asyncio.Event()

        async def send_realtime_input(self, **kwargs):
            self.sent.append(kwargs)
            self.entered.set()
            await self.release.wait()

    async def exercise():
        live = live_cls()
        live.out_queue = asyncio.Queue()
        live.session = BlockingSession()
        await live.out_queue.put({"data": b"first", "mime_type": "audio/pcm"})
        second = {"data": b"second", "mime_type": "audio/pcm"}
        await live.out_queue.put(second)
        sender = asyncio.create_task(live._send_realtime())
        try:
            await asyncio.wait_for(live.session.entered.wait(), timeout=1)
            sender.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sender
            live.session.release.set()
            await asyncio.sleep(0)
        finally:
            if not sender.done():
                sender.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await sender
        return live, second

    live, second = asyncio.run(exercise())

    assert len(live.session.sent) == 1
    assert live.out_queue.qsize() == 1
    assert live.out_queue.get_nowait() is second


def test_receive_wrapper_reraises_the_same_exception_object(monkeypatch):
    sentinel = RuntimeError("receive failed outside transport authority")
    events = []

    class FailingLive(_Live):
        async def _receive_audio(self):
            raise sentinel

    monkeypatch.setattr(
        voice_live_transport,
        "install_turn_role",
        lambda: False,
    )
    monkeypatch.setattr(
        voice_live_transport._logger,
        "error",
        lambda event, **fields: events.append((event, fields)),
    )
    live_cls = type("CharacterizedFailingLive", (FailingLive,), {})
    assert voice_live_transport.install(
        types.SimpleNamespace(JarvisLive=live_cls)
    ) is True

    async def exercise():
        live = live_cls()
        try:
            await live._receive_audio()
        except RuntimeError as caught:
            return caught
        raise AssertionError("receive exception was swallowed")

    caught = asyncio.run(exercise())

    assert caught is sentinel
    assert events == [("voice.live_receive_rejected", {
        "kind": "local",
        "leaf_type": "RuntimeError",
        "last_input": None,
    })]


def test_receive_telemetry_excludes_audio_secrets_and_exception_text(
    monkeypatch,
):
    audio_secret = b"pcm-secret-sentinel-never-log"
    field_secret = "api-key-secret-sentinel-never-log"
    error_secret = "exception-secret-sentinel-never-log"
    events = []

    class FailingLive(_Live):
        async def _receive_audio(self):
            raise RuntimeError(error_secret)

    monkeypatch.setattr(
        voice_live_transport,
        "install_turn_role",
        lambda: False,
    )
    monkeypatch.setattr(
        voice_live_transport._logger,
        "error",
        lambda event, **fields: events.append((event, fields)),
    )
    live_cls = type("CharacterizedRedactionLive", (FailingLive,), {})
    assert voice_live_transport.install(
        types.SimpleNamespace(JarvisLive=live_cls)
    ) is True

    async def exercise():
        live = live_cls()
        live.out_queue = asyncio.Queue()
        live.session = _RecordingSession(expected=1)
        await live.out_queue.put({
            "data": audio_secret,
            "mime_type": "audio/pcm",
            "api_key": field_secret,
        })
        sender = asyncio.create_task(live._send_realtime())
        try:
            await asyncio.wait_for(live.session.complete.wait(), timeout=1)
        finally:
            sender.cancel()
            with pytest.raises(asyncio.CancelledError):
                await sender
        with pytest.raises(RuntimeError):
            await live._receive_audio()

    asyncio.run(exercise())

    assert len(events) == 1
    event, fields = events[0]
    assert event == "voice.live_receive_rejected"
    assert fields == {
        "kind": "local",
        "leaf_type": "RuntimeError",
        "last_input": {
            "message_type": "dict",
            "mime_type": "audio/pcm;rate=16000",
            "bytes": len(audio_secret),
        },
    }
    rendered = repr(events)
    assert repr(audio_secret) not in rendered
    assert field_secret not in rendered
    assert error_secret not in rendered


def test_fresh_sdk_session_class_is_role_wrapped_exactly_once(monkeypatch):
    genai_live = pytest.importorskip("google.genai.live")
    sent = []

    class FreshSession:
        async def send_client_content(self, *, turns=None, turn_complete=True):
            sent.append((turns, turn_complete))

    monkeypatch.setattr(genai_live, "AsyncSession", FreshSession)

    assert voice_live_transport.install_turn_role() is True
    wrapped = FreshSession.send_client_content
    assert voice_live_transport.install_turn_role() is False
    assert FreshSession.send_client_content is wrapped

    async def exercise():
        session = FreshSession()
        await session.send_client_content(
            turns={"parts": [{"text": "role-less"}]},
            turn_complete=False,
        )
        await session.send_client_content(
            turns={"role": "model", "parts": []},
            turn_complete=True,
        )

    asyncio.run(exercise())

    assert sent == [
        ({"parts": [{"text": "role-less"}], "role": "user"}, False),
        ({"role": "model", "parts": []}, True),
    ]


def test_marked_transport_self_heals_role_on_fresh_sdk_session(monkeypatch):
    genai_live = pytest.importorskip("google.genai.live")
    sent = []

    class FreshSession:
        async def send_client_content(self, *, turns=None, turn_complete=True):
            sent.append((turns, turn_complete))

    class MarkedLive(_Live):
        _jarvis_live_transport_installed = True

    monkeypatch.setattr(genai_live, "AsyncSession", FreshSession)
    original_send = MarkedLive._send_realtime
    original_receive = MarkedLive._receive_audio

    assert voice_live_transport.install(
        types.SimpleNamespace(JarvisLive=MarkedLive)
    ) is False
    assert MarkedLive._send_realtime is original_send
    assert MarkedLive._receive_audio is original_receive

    asyncio.run(FreshSession().send_client_content(
        turns={"parts": [{"text": "role-less after reconnect"}]},
        turn_complete=False,
    ))

    assert sent == [({
        "parts": [{"text": "role-less after reconnect"}],
        "role": "user",
    }, False)]
