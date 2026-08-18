"""Fase 35 Slice 11 — desktop-safe teardown fallback telemetry."""
from __future__ import annotations


def test_teardown_failure_still_calls_legacy_close_and_reports(monkeypatch):
    from jarvis.integrations import desktop_safe_lifecycle

    events: list[tuple[str, str]] = []

    def record(event, exc=None, **_context):
        events.append((str(event), type(exc).__name__ if exc else ""))

    from jarvis.core import quiet

    monkeypatch.setattr(quiet, "swallowed", record)

    class Session:
        def clear_all(self):
            raise RuntimeError("teardown failed")

    monkeypatch.setattr(desktop_safe_lifecycle, "desktop_safe_session",
                        lambda: Session())

    calls = []

    class Window:
        def closeEvent(self, event):
            calls.append(event)
            return "legacy-result"

    assert desktop_safe_lifecycle.install(Window) is True
    marker = object()

    assert Window().closeEvent(marker) == "legacy-result"
    assert calls == [marker]
    assert events == [(
        "integrations.desktop_safe_lifecycle.teardown_failed", "RuntimeError")]
