"""Fase 35 Slice 11 — command-palette memory fallback telemetry."""
from __future__ import annotations

from types import SimpleNamespace


def _spy(monkeypatch, module):
    events: list[tuple[str, str]] = []

    def record(event, exc=None, **_context):
        events.append((str(event), type(exc).__name__ if exc else ""))

    from jarvis.core import quiet

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


def _owner(memory):
    return SimpleNamespace(
        router=SimpleNamespace(_known_sites={"Jarvis": "https://example.invalid"}),
        memory=memory,
    )


def test_palette_keeps_macros_when_recent_memory_fails(monkeypatch):
    from jarvis.ui import window_panels

    events = _spy(monkeypatch, window_panels)

    class Memory:
        def get_recent_episodes(self, *, limit):
            raise OSError(f"recent lookup failed: {limit}")

        def list_macros(self, *, approved_only):
            assert approved_only is True
            return [{"name": "safe-macro", "steps": []}]

    model = window_panels.WindowPanelsMixin._build_palette_model(_owner(Memory()))

    assert model._macros == [{"name": "safe-macro", "steps": []}]
    assert model._recent == []
    assert events == [("ui.window_panels.palette_recent_failed", "OSError")]


def test_palette_keeps_recent_memory_when_macros_fail(monkeypatch):
    from jarvis.ui import window_panels

    events = _spy(monkeypatch, window_panels)
    recent = [{"target": "local note", "content": "remembered"}]

    class Memory:
        def get_recent_episodes(self, *, limit):
            assert limit == 15
            return recent

        def list_macros(self, *, approved_only):
            raise RuntimeError(f"macro lookup failed: {approved_only}")

    model = window_panels.WindowPanelsMixin._build_palette_model(_owner(Memory()))

    assert model._recent == recent
    assert model._macros == []
    assert events == [("ui.window_panels.palette_macros_failed", "RuntimeError")]
