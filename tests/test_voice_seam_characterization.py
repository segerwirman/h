"""Characterization tests for the frozen voice seam composition."""
from __future__ import annotations

import asyncio
import types


def test_install_voice_seams_preserves_runtime_order(monkeypatch):
    from jarvis import main as jmain
    from jarvis.core import llm
    from jarvis.integrations import (
        google_voice,
        voice_clarify,
        voice_l1,
        voice_live_transport,
        voice_native_tools,
        voice_playback_fix,
        voice_playback_level,
        voice_safety,
        voice_tasks,
        whatsapp_voice,
    )

    modules = [
        google_voice,
        voice_playback_fix,
        voice_tasks,
        voice_l1,
        voice_live_transport,
        voice_playback_level,
        whatsapp_voice,
        voice_native_tools,
        voice_clarify,
        voice_safety,
    ]
    calls = []
    for module in modules:
        monkeypatch.setattr(
            module,
            "install",
            lambda _legacy, _name=module.__name__: calls.append(_name),
        )

    monkeypatch.setattr(llm, "api_key", lambda: "test-key")
    monkeypatch.setattr(jmain.config, "get", lambda _key, default=None: default)

    legacy = types.SimpleNamespace(LIVE_MODEL="fallback-live-model")
    logger = types.SimpleNamespace(warning=lambda *_a, **_k: None)

    jmain._install_voice_seams(legacy, logger)

    assert calls == [module.__name__ for module in modules]
    assert legacy._get_api_key() == "test-key"
    assert legacy.LIVE_MODEL == "fallback-live-model"


def test_whatsapp_tap_queue_mirrors_consumed_audio_and_delegates_attributes(
    monkeypatch,
):
    from jarvis.integrations import whatsapp_voice

    class _Bridge:
        active = False

        def __init__(self):
            self.tapped = []

        def tap_output(self, chunk):
            self.tapped.append(chunk)

    inner = asyncio.Queue()
    bridge = _Bridge()
    queue = whatsapp_voice._TapQueue(inner, bridge)
    chunk = b"pcm-output"

    asyncio.run(inner.put(chunk))

    assert asyncio.run(queue.get()) == chunk
    assert bridge.tapped == [chunk]
    assert queue.empty() is True


def test_whatsapp_install_wraps_playback_and_restores_original_queue(monkeypatch):
    from jarvis.integrations import whatsapp_voice

    bridge = types.SimpleNamespace(active=False, tapped=[])
    bridge.tap_output = bridge.tapped.append
    monkeypatch.setattr(
        whatsapp_voice.WhatsAppAudioBridge,
        "get",
        classmethod(lambda _cls: bridge),
    )

    class _Live:
        def __init__(self):
            self.audio_in_queue = asyncio.Queue()

        async def _play_audio(self):
            self.queue_seen_by_legacy = self.audio_in_queue
            return await self.audio_in_queue.get()

    legacy = types.SimpleNamespace(JarvisLive=_Live)
    whatsapp_voice.install(legacy)

    assert getattr(_Live.__init__, "_jarvis_whatsapp_voice", False) is True
    assert getattr(_Live._play_audio, "_jarvis_whatsapp_voice", False) is True

    live = _Live()
    original_queue = live.audio_in_queue
    asyncio.run(original_queue.put(b"pcm-output"))

    assert asyncio.run(live._play_audio()) == b"pcm-output"
    assert live.queue_seen_by_legacy is not original_queue
    assert bridge.tapped == [b"pcm-output"]
    assert live.audio_in_queue is original_queue
