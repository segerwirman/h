from __future__ import annotations

from actions import hermes_action
from jarvis.core import quiet


def _spy_swallowed(monkeypatch):
    events = []

    def record(event, exc=None, **context):
        events.append((event, exc, context))

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


def test_ui_log_failure_is_recorded_without_raising(monkeypatch):
    events = _spy_swallowed(monkeypatch)

    class Player:
        def write_log(self, _message):
            raise RuntimeError("ui unavailable")

    hermes_action._ui_log(Player(), "SYS: test")

    assert [event[0] for event in events] == ["actions.hermes.ui_log_failed"]
    assert isinstance(events[0][1], RuntimeError)


def test_done_speak_failure_is_recorded_and_ack_is_preserved(monkeypatch):
    events = _spy_swallowed(monkeypatch)
    monkeypatch.setattr(hermes_action, "is_enabled", lambda: True)
    monkeypatch.setattr(hermes_action.HermesBridge, "get", lambda: object())

    def dispatch(_task, *, on_done, on_error):
        on_done("selesai")
        return True

    monkeypatch.setattr(hermes_action, "dispatch_async", dispatch)

    def speak(_message):
        raise RuntimeError("speaker unavailable")

    result = hermes_action.hermes_action(
        {"mode": "task", "task": "uji callback"}, speak=speak
    )

    assert result == (
        "Tugas sedang dikerjakan Hermes di latar belakang. "
        "Saya akan melapor begitu selesai."
    )
    assert [event[0] for event in events] == ["actions.hermes.speak_done_failed"]
    assert isinstance(events[0][1], RuntimeError)


def test_error_speak_failure_is_recorded_without_rethrowing(monkeypatch):
    events = _spy_swallowed(monkeypatch)
    monkeypatch.setattr(hermes_action, "is_enabled", lambda: True)
    monkeypatch.setattr(hermes_action.HermesBridge, "get", lambda: object())

    def dispatch(_task, *, on_done, on_error):
        on_error("gagal")
        return True

    monkeypatch.setattr(hermes_action, "dispatch_async", dispatch)

    def speak(_message):
        raise RuntimeError("speaker unavailable")

    result = hermes_action.hermes_action(
        {"mode": "task", "task": "uji error callback"}, speak=speak
    )

    assert result == (
        "Tugas sedang dikerjakan Hermes di latar belakang. "
        "Saya akan melapor begitu selesai."
    )
    assert [event[0] for event in events] == ["actions.hermes.speak_error_failed"]
    assert isinstance(events[0][1], RuntimeError)
