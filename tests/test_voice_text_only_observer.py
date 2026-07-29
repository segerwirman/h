"""Observability for text-only Gemini Live output."""
from __future__ import annotations

from types import SimpleNamespace

from jarvis.integrations import voice_text_only_observer


def test_disabled_preserves_legacy_hook(monkeypatch):
    legacy = SimpleNamespace(VOICE_TEXT_ONLY_HOOK=None)
    monkeypatch.setattr(voice_text_only_observer.config, "get",
                        lambda _key, default=None: default)

    assert voice_text_only_observer.install(legacy) is False
    assert legacy.VOICE_TEXT_ONLY_HOOK is None


def test_text_only_turn_is_logged_once_and_never_spoken(monkeypatch):
    events = []
    logs = []
    legacy = SimpleNamespace(VOICE_TEXT_ONLY_HOOK=None)
    monkeypatch.setattr(voice_text_only_observer.config, "get",
                        lambda _key, default=None: True)
    monkeypatch.setattr(voice_text_only_observer._logger, "warning",
                        lambda event, **fields: events.append((event, fields)))
    monkeypatch.setattr(voice_text_only_observer._logger, "info",
                        lambda *_args, **_kwargs: None)

    assert voice_text_only_observer.install(legacy) is True
    live = SimpleNamespace(
        _turn_id="turn-1",
        ui=SimpleNamespace(write_log=logs.append),
    )

    import asyncio
    asyncio.run(legacy.VOICE_TEXT_ONLY_HOOK(
        live, "Jawaban  teks   tanpa audio.", had_audio=False))
    asyncio.run(legacy.VOICE_TEXT_ONLY_HOOK(
        live, "Audio normal.", had_audio=True))

    assert events == [("voice.text_only_output", {
        "request_id": "turn-1", "text_chars": 25,
    })]
    assert logs == [
        "SYS: Respons Gemini diterima tanpa audio; teks tetap ditampilkan."
    ]
