from __future__ import annotations

from actions import computer_control
from jarvis.core import quiet


def _spy_swallowed(monkeypatch):
    events = []

    def record(event, exc=None, **context):
        events.append((event, exc, context))

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


def test_screenshot_path_failure_keeps_home_fallback(monkeypatch, tmp_path):
    events = _spy_swallowed(monkeypatch)
    requested = tmp_path / "capture.png"
    class BrokenRoot:
        def resolve(self):
            raise OSError("path root resolution failed")

    monkeypatch.setattr(computer_control, "_SAFE_SCREENSHOT_ROOTS", (BrokenRoot(),))

    result = computer_control._safe_screenshot_path(str(requested))

    assert result == computer_control.Path.home() / "Desktop" / "jarvis_screenshot.png"
    assert [event[0] for event in events] == [
        "actions.computer_control.screenshot_path_failed"
    ]
    assert isinstance(events[0][1], OSError)


def test_user_profile_failure_keeps_empty_profile_fallback(monkeypatch, tmp_path):
    events = _spy_swallowed(monkeypatch)
    memory_path = tmp_path / "long_term.json"
    memory_path.write_text("{not valid json", encoding="utf-8")
    monkeypatch.setattr(computer_control, "_MEMORY_PATH", memory_path)

    assert computer_control._user_profile() == {}
    assert [event[0] for event in events] == [
        "actions.computer_control.user_profile_failed"
    ]
    assert isinstance(events[0][1], ValueError)
