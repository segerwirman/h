"""Fase 35 Slice 10 — app registry fallback observability."""
from __future__ import annotations

import sys
import types

from jarvis.core import app_registry, quiet


def _spy(monkeypatch):
    events = []

    def record(event, exc=None, **_context):
        events.append((event, type(exc).__name__ if exc is not None else None))

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


def test_start_apps_probe_failure_keeps_local_scan_and_records(monkeypatch):
    events = _spy(monkeypatch)
    monkeypatch.setenv("ProgramData", "Z:/missing-program-data")
    monkeypatch.setenv("APPDATA", "Z:/missing-app-data")

    def fail_run(*_args, **_kwargs):
        raise OSError("powershell unavailable")

    monkeypatch.setattr(app_registry.subprocess, "run", fail_run)
    monkeypatch.setitem(
        sys.modules,
        "winreg",
        types.SimpleNamespace(
            HKEY_LOCAL_MACHINE=object(),
            HKEY_CURRENT_USER=object(),
            OpenKey=lambda *_args, **_kwargs: (_ for _ in ()).throw(
                OSError("registry unavailable")),
        ),
    )

    result = app_registry._scan_windows()

    assert isinstance(result, dict)
    assert events == [("core.app_registry.start_apps_probe_failed", "OSError")]


def test_window_enumeration_failure_keeps_process_scan_fail_open(monkeypatch):
    events = _spy(monkeypatch)

    monkeypatch.setitem(
        sys.modules,
        "pygetwindow",
        types.SimpleNamespace(
            getAllWindows=lambda: (_ for _ in ()).throw(
                RuntimeError("window enumeration unavailable")),
        ),
    )
    monkeypatch.setitem(
        sys.modules,
        "psutil",
        types.SimpleNamespace(process_iter=lambda _fields: []),
    )

    result = app_registry.list_running()

    assert result == []
    assert events == [("core.app_registry.window_enum_failed", "RuntimeError")]
