"""Focused observability contract for the text-only observer UI fallback."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from jarvis.integrations import voice_text_only_observer


def test_ui_log_failure_is_observable_and_remains_fail_open(monkeypatch):
    events = []
    monkeypatch.setattr(
        voice_text_only_observer.config,
        "get",
        lambda _key, default=None: True,
    )
    monkeypatch.setattr(
        voice_text_only_observer._logger,
        "warning",
        lambda event, **fields: events.append((event, fields)),
    )

    def fail_write(_text):
        raise RuntimeError("private UI detail")

    live = SimpleNamespace(
        _turn_id="turn-ui-failure",
        ui=SimpleNamespace(write_log=fail_write),
    )

    result = asyncio.run(
        voice_text_only_observer.observe(
            live, "Jawaban teks tanpa audio.", had_audio=False
        )
    )

    assert result is None
    assert events[0] == (
        "voice.text_only_output",
        {"request_id": "turn-ui-failure", "text_chars": 25},
    )
    assert events[1] == (
        "voice.text_only.write_failed",
        {"error": "RuntimeError"},
    )
    assert all("private UI detail" not in repr(event) for event in events)
