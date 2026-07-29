"""Regression coverage for Gemini Live transport compatibility."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.integrations import voice_live_transport


def test_normalise_adds_rate_only_to_bare_pcm():
    original = {"data": b"pcm", "mime_type": "audio/pcm"}

    normalised = voice_live_transport._normalise(original)

    assert normalised == {"data": b"pcm", "mime_type": "audio/pcm;rate=16000"}
    assert normalised is not original
    assert voice_live_transport._normalise({"mime_type": "audio/wav"}) == {
        "mime_type": "audio/wav"
    }


def test_input_kwargs_avoids_the_rejected_media_chunks_field():
    pcm = {"data": b"pcm", "mime_type": "audio/pcm;rate=16000"}
    frame = {"data": b"jpg", "mime_type": "image/jpeg"}
    other = {"data": b"???", "mime_type": "application/octet-stream"}

    assert voice_live_transport._input_kwargs(pcm) == {"audio": pcm}
    assert voice_live_transport._input_kwargs(frame) == {"video": frame}
    assert voice_live_transport._input_kwargs(other) == {"media": other}
    assert voice_live_transport._input_kwargs("raw") == {"media": "raw"}


def test_with_role_completes_only_role_less_turns():
    assert voice_live_transport._with_role({"parts": [{"text": "hi"}]}) == {
        "parts": [{"text": "hi"}],
        "role": "user",
    }
    assert voice_live_transport._with_role({"role": "model", "parts": []}) == {
        "role": "model",
        "parts": [],
    }
    assert voice_live_transport._with_role([{"parts": []}]) == [
        {"parts": [], "role": "user"}
    ]
    assert voice_live_transport._with_role(None) is None


def test_install_turn_role_wraps_the_sdk_session_once(monkeypatch):
    genai_live = pytest.importorskip("google.genai.live")
    sent = []

    class _AsyncSession:
        async def send_client_content(self, *, turns=None, turn_complete=True):
            sent.append((turns, turn_complete))

    monkeypatch.setattr(genai_live, "AsyncSession", _AsyncSession)

    assert voice_live_transport.install_turn_role() is True
    assert voice_live_transport.install_turn_role() is False

    asyncio.run(_AsyncSession().send_client_content(
        turns={"parts": [{"text": "hi"}]}, turn_complete=False))

    assert sent == [({"parts": [{"text": "hi"}], "role": "user"}, False)]


def test_shape_never_includes_audio_data():
    shape = voice_live_transport._shape({
        "data": b"never log this audio",
        "mime_type": "audio/pcm;rate=16000",
    })

    assert shape == {
        "message_type": "dict",
        "mime_type": "audio/pcm;rate=16000",
        "bytes": 20,
    }
    assert "data" not in shape


def test_install_normalises_outbound_pcm_and_logs_receive_context(monkeypatch):
    events = []

    class _Live:
        async def _send_realtime(self):
            raise AssertionError("replaced by adapter")

        async def _receive_audio(self):
            raise RuntimeError("server rejected request")

    legacy = SimpleNamespace(JarvisLive=_Live)
    monkeypatch.setattr(voice_live_transport._logger, "info", lambda *_a, **_k: None)
    monkeypatch.setattr(
        voice_live_transport._logger,
        "error",
        lambda event, **fields: events.append((event, fields)),
    )
    assert voice_live_transport.install(legacy) is True
    assert voice_live_transport.install(legacy) is False

    class _Session:
        def __init__(self):
            self.sent = []

        async def send_realtime_input(self, **kwargs):
            self.sent.append(kwargs)

    async def exercise():
        live = _Live()
        live.out_queue = asyncio.Queue()
        live.session = _Session()
        await live.out_queue.put({"data": b"pcm", "mime_type": "audio/pcm"})
        sender = asyncio.create_task(live._send_realtime())
        await asyncio.sleep(0)
        sender.cancel()
        with pytest.raises(asyncio.CancelledError):
            await sender
        with pytest.raises(RuntimeError, match="server rejected"):
            await live._receive_audio()
        return live

    live = asyncio.run(exercise())
    assert live.session.sent == [
        {"audio": {"data": b"pcm", "mime_type": "audio/pcm;rate=16000"}}
    ]
    assert events == [("voice.live_receive_rejected", {
        "exc_type": "RuntimeError",
        "last_input": {
            "message_type": "dict",
            "mime_type": "audio/pcm;rate=16000",
            "bytes": 3,
        },
    })]