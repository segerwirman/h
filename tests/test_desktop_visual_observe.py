"""Fase 14: observasi visual desktop hanya lokal, sanitized, non-authoritative."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext


def _context(*, surface: str = "desktop", source: str = "agent") -> ExecutionContext:
    return ExecutionContext.create(
        source=source, actor_id="local", session_id="visual-a", surface=surface,
        toolsets=["desktop_safe"],
    )


def test_visual_observe_runs_through_registry_only_for_local_desktop_context(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.tools.desktop_visual_observe import DesktopVisualObserve

    report = {
        "visual_observation_id": "opaque-visual-id",
        "brightness": "balanced", "complexity": "low", "dominant_tone": "neutral",
    }
    tool = DesktopVisualObserve(service=type("Service", (), {"observe": lambda *_, **__: report})())
    original = registry.get
    monkeypatch.setattr(registry, "get", lambda name: tool if name == tool.name else original(name))

    result = asyncio.run(registry.execute(
        tool.name, {}, session=type("S", (), {"id": "visual-a", "record_tool": lambda *_: None})(),
        context=_context(),
    ))

    assert result.ok is True
    assert result.content == report


def test_visual_observe_is_not_exposed_to_voice_remote_cron_or_delegation_schema():
    from jarvis.agent import registry
    from jarvis.agent.tools.desktop_visual_observe import DesktopVisualObserve
    from jarvis.integrations import voice_native_tools

    assert DesktopVisualObserve.name not in {item["name"] for item in voice_native_tools.declarations()}
    for surface, source, allowed in (
        ("desktop", "agent", True), ("remote", "telegram", False),
        ("voice", "gemini_live", False), ("desktop", "cron", False),
        ("desktop", "delegation", False),
    ):
        context = _context(surface=surface, source=source)
        names = {item["function"]["name"] for item in registry.schemas(context=context)}
        assert (DesktopVisualObserve.name in names) is allowed
