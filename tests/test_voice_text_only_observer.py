"""Observability for text-only Gemini Live output."""
from __future__ import annotations

from types import SimpleNamespace

import asyncio

from jarvis.integrations import voice_text_only_observer


def test_disabled_observer_is_true_noop(monkeypatch):
    events = []
    logs = []
    monkeypatch.setattr(voice_text_only_observer.config, "get",
                        lambda _key, default=None: default)
    monkeypatch.setattr(voice_text_only_observer._logger, "warning",
                        lambda event, **fields: events.append((event, fields)))
    live = SimpleNamespace(
        _turn_id="turn-disabled",
        ui=SimpleNamespace(write_log=logs.append),
    )

    asyncio.run(voice_text_only_observer.observe(
        live, "Jawaban teks tanpa audio.", had_audio=False))

    assert events == []
    assert logs == []
    assert not hasattr(voice_text_only_observer, "install")


def test_text_only_turn_is_logged_once_and_never_spoken(monkeypatch):
    events = []
    logs = []
    monkeypatch.setattr(voice_text_only_observer.config, "get",
                        lambda _key, default=None: True)
    monkeypatch.setattr(voice_text_only_observer._logger, "warning",
                        lambda event, **fields: events.append((event, fields)))
    live = SimpleNamespace(
        _turn_id="turn-1",
        ui=SimpleNamespace(write_log=logs.append),
    )

    asyncio.run(voice_text_only_observer.observe(
        live, "Jawaban  teks   tanpa audio.", had_audio=False))
    asyncio.run(voice_text_only_observer.observe(
        live, "Audio normal.", had_audio=True))

    assert events == [("voice.text_only_output", {
        "request_id": "turn-1", "text_chars": 25,
    })]
    assert logs == [
        "SYS: Respons Gemini diterima tanpa audio; teks tetap ditampilkan."
    ]
