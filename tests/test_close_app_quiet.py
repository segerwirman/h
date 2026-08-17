from __future__ import annotations

import json
import sys
import types

from actions import close_app as ca
from jarvis.core import quiet


def _events(caplog):
    events = []
    for record in caplog.records:
        try:
            events.append(json.loads(record.getMessage()))
        except (TypeError, ValueError):
            continue
    return events


def _install_process_fallback(monkeypatch):
    terminated = []

    class Process:
        def __init__(self, pid):
            self.pid = pid

        def terminate(self):
            terminated.append(self.pid)

    monkeypatch.setitem(sys.modules, "psutil", types.SimpleNamespace(Process=Process))
    return terminated


def test_window_probe_failure_is_recorded_and_falls_through(
    monkeypatch, caplog
):
    quiet.reset()
    app = types.SimpleNamespace(pid=501)
    window = types.SimpleNamespace(title="Editor", _hWnd=10)
    monkeypatch.setitem(
        sys.modules,
        "pygetwindow",
        types.SimpleNamespace(getAllWindows=lambda: [window]),
    )

    def fail_window_probe(_handle):
        raise RuntimeError("window probe failed")

    monkeypatch.setitem(
        sys.modules,
        "win32process",
        types.SimpleNamespace(GetWindowThreadProcessId=fail_window_probe),
    )
    terminated = _install_process_fallback(monkeypatch)

    with caplog.at_level("INFO"):
        assert ca._graceful(app) is True

    assert terminated == [501]
    entries = [
        event
        for event in _events(caplog)
        if event.get("event") == "close_app.window_probe_failed"
    ]
    assert entries
    assert entries[0]["pid"] == 501


def test_wm_enum_failure_is_recorded_and_falls_through(monkeypatch, caplog):
    quiet.reset()
    app = types.SimpleNamespace(pid=502)

    def fail_enumeration():
        raise RuntimeError("window enumeration failed")

    monkeypatch.setitem(
        sys.modules,
        "pygetwindow",
        types.SimpleNamespace(getAllWindows=fail_enumeration),
    )
    monkeypatch.setitem(sys.modules, "win32process", types.SimpleNamespace())
    terminated = _install_process_fallback(monkeypatch)

    with caplog.at_level("INFO"):
        assert ca._graceful(app) is True

    assert terminated == [502]
    entries = [
        event
        for event in _events(caplog)
        if event.get("event") == "close_app.wm_enum_failed"
    ]
    assert entries
    assert entries[0]["pid"] == 502


def test_player_log_failure_is_recorded_and_returns_message(monkeypatch, caplog):
    quiet.reset()
    outcome = ca.CloseOutcome(True, ca.STATUS_CLOSED, "Editor ditutup.")
    monkeypatch.setattr(ca, "close_app", lambda *_args, **_kwargs: outcome)

    class Player:
        def write_log(self, _message):
            raise RuntimeError("player log failed")

    with caplog.at_level("INFO"):
        result = ca.close_app_action({"name": "editor"}, player=Player())

    assert result == outcome.message
    entries = [
        event
        for event in _events(caplog)
        if event.get("event") == "close_app.player_log_failed"
    ]
    assert entries
    assert entries[0]["status"] == ca.STATUS_CLOSED
