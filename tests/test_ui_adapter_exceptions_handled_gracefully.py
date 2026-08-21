"""Fase 35 — test focused untuk UIAdapter exception handling.

Verifies that UIAdapter's two blanket-exception handlers properly delegate
to the swallowed() telemetry helper instead of silently swallowing errors.

Uses fake window stubs, no real MainWindow/Qt required. Offline/fake contract.
Control flow, callback order, retry, and return values are unchanged by the
migration; this test asserts only that swallowed failures stay observable.
"""
from __future__ import annotations

import asyncio

from jarvis.agent.adapters import ui as ui_adapter
from jarvis.core import quiet


class FakeConfig:
    """Deterministic config stub: short confirm timeout keeps tests fast."""

    @staticmethod
    def get(key, default=None):
        if key == "agent.confirm_timeout_s":
            return 0.1
        return default


def test_confirm_speech_failure_records_event_and_keeps_flow(monkeypatch):
    """ask(): speech announcement failure → swallowed event recorded, flow intact."""

    events = []

    class Window:
        def __init__(self):
            self.logs = []

        def write_log(self, message):
            self.logs.append(message)

        def _speak_line(self, *args, **kwargs):
            raise RuntimeError("speech unavailable")

    window = Window()
    adapter = ui_adapter.UIAdapter.__new__(ui_adapter.UIAdapter)
    adapter.task_id = "T-confirm-test"
    monkeypatch.setattr(adapter, "_win", lambda: window)
    monkeypatch.setattr(ui_adapter, "config", FakeConfig)
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )

    result = asyncio.run(adapter.ask("Test question"))

    # control flow unchanged: timeout path returns None, question still logged
    assert result is None
    assert len(window.logs) == 2
    assert window.logs[0].startswith("AGENT ? Test question")
    assert "konfirmasi agent kedaluwarsa" in window.logs[1]
    # speech failure is observable
    assert len(events) == 1
    assert events[0][0] == "agent.adapter.ui.confirm_speech_failed"
    assert isinstance(events[0][1], RuntimeError)


def test_artifact_remember_failure_records_event_and_continues(monkeypatch):
    """send_image(): artifact memory failure → swallowed event, image still shown/logged."""

    events = []

    class Window:
        def __init__(self):
            self.logs = []

        def write_log(self, message):
            self.logs.append(message)

    window = Window()
    adapter = ui_adapter.UIAdapter.__new__(ui_adapter.UIAdapter)
    adapter.task_id = "T-image-test"
    monkeypatch.setattr(adapter, "_win", lambda: window)
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )

    class BrokenStore:
        def remember_artifact(self, *_args, **_kwargs):
            raise OSError("store backend unavailable")

    monkeypatch.setattr(
        "jarvis.agent.conversation_context.STORE", BrokenStore()
    )

    asyncio.run(adapter.send_image("/path/to/image.png", "caption here"))

    # remember failure is observable, not silent
    assert len(events) == 1
    assert events[0][0] == "agent.adapter.ui.artifact_remember_failed"
    assert isinstance(events[0][1], OSError)
    # control flow unchanged: image is still announced to the user
    assert any("/path/to/image.png" in log for log in window.logs)
