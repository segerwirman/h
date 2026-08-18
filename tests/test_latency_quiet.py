from __future__ import annotations

import pytest

from jarvis.core import latency, quiet


@pytest.fixture(autouse=True)
def _reset_latency():
    latency.reset()
    yield
    latency.reset()


def _spy_swallowed(monkeypatch):
    events = []

    def record(event, exc=None, **context):
        events.append((event, exc, context))

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


def test_start_failure_records_event_and_keeps_fail_open(monkeypatch):
    events = _spy_swallowed(monkeypatch)
    monkeypatch.setattr(latency, "enabled", lambda: True)

    def boom():
        raise OSError("clock unavailable")

    monkeypatch.setattr(latency.time, "monotonic", boom)

    latency.start("turn-start", task="synthetic")

    assert [event[0] for event in events] == ["core.latency.start_failed"]
    assert isinstance(events[0][1], OSError)
    assert latency.active_count() == 0


def test_mark_failure_records_event_and_keeps_turn_open(monkeypatch):
    events = _spy_swallowed(monkeypatch)
    monkeypatch.setattr(latency, "enabled", lambda: True)
    latency.start("turn-mark", now=100.0)

    def boom():
        raise RuntimeError("clock unavailable")

    monkeypatch.setattr(latency.time, "monotonic", boom)

    latency.mark("turn-mark", "prepared")

    assert [event[0] for event in events] == ["core.latency.mark_failed"]
    assert isinstance(events[0][1], RuntimeError)
    assert latency.active_count() == 1
