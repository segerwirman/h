"""UI adapter: progress narration failures stay observable and fail-open."""
from __future__ import annotations

import asyncio

from jarvis.agent.adapters import ui as ui_adapter
from jarvis.core import quiet


def test_progress_narration_failure_records_event_and_keeps_log(monkeypatch):
    events = []

    class Window:
        def __init__(self):
            self.logs = []

        def write_log(self, message):
            self.logs.append(message)

        def _speak_line(self, *_args, **_kwargs):
            raise OSError("speech queue unavailable")

    class Narrator:
        def should_speak(self, _phrase):
            return True

    window = Window()
    adapter = ui_adapter.UIAdapter.__new__(ui_adapter.UIAdapter)
    adapter._narrator = Narrator()
    adapter.task_id = "T-test"
    monkeypatch.setattr(adapter, "_win", lambda: window)
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )
    monkeypatch.setattr(
        "jarvis.agent.progress_narrator.phrase_for",
        lambda _text: "progress phrase",
    )

    asyncio.run(adapter.progress("still working"))

    assert window.logs == ["SYS: still working"]
    assert len(events) == 1
    assert events[0][0] == "agent.adapter.ui.progress_narration_failed"
    assert isinstance(events[0][1], OSError)
