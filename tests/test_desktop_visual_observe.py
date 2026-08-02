"""Fase 14: observasi visual desktop hanya lokal, sanitized, non-authoritative."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext


def _context(*, surface: str = "desktop", source: str = "agent") -> ExecutionContext:
    return ExecutionContext.create(
        source=source, actor_id="local", session_id="visual-a", surface=surface,
        toolsets=["desktop_safe"],
    )


def test_visual_schema_has_no_input_and_is_read_only():
    from jarvis.agent.tools.desktop_visual_observe import DesktopVisualObserve

    tool = DesktopVisualObserve()

    assert tool.json_schema()["properties"] == {}
    assert tool.read_only is True
    assert tool.requires_confirmation is False
    assert not {"x", "y", "image", "path", "url", "prompt", "text", "selector", "action"} & set(
        tool.json_schema()["properties"])


def test_visual_observe_requires_desktop_local_context_before_capture():
    from jarvis.agent.tools.desktop_visual_observe import DesktopVisualObserve

    calls = []
    tool = DesktopVisualObserve(service=type("Service", (), {
        "observe": lambda *_: calls.append("capture"),
    })())

    for context in (
        None,
        _context(surface="remote", source="telegram"),
        _context(surface="voice", source="gemini_live"),
        _context(surface="desktop", source="cron"),
        _context(surface="desktop", source="delegation"),
    ):
        result = asyncio.run(tool.run(_session=type("S", (), {"id": "visual-a"})(), _context=context))
        assert result.ok is False

    assert calls == []


def test_visual_observe_returns_only_bounded_non_actionable_categories():
    from jarvis.agent.tools.desktop_visual_observe import DesktopVisualObserve

    report = {
        "visual_observation_id": "opaque-visual-id",
        "brightness": "balanced",
        "complexity": "medium",
        "dominant_tone": "neutral",
    }
    tool = DesktopVisualObserve(service=type("Service", (), {"observe": lambda *_, **__: report})())
    result = asyncio.run(tool.run(
        _session=type("S", (), {"id": "visual-a"})(), _context=_context(),
    ))

    assert result.ok is True
    assert result.content == report
    forbidden = {"image", "pixels", "ocr", "text", "label", "x", "y", "rect", "element_id",
                 "observation_id", "actions", "selector", "runtime_id", "screenshot"}
    assert not forbidden & set(result.content)


def test_visual_observe_rejects_malformed_or_actionable_service_output():
    from jarvis.agent.tools.desktop_visual_observe import DesktopVisualObserve

    unsafe = {
        "visual_observation_id": "opaque-id", "brightness": "balanced",
        "complexity": "medium", "dominant_tone": "neutral",
        "x": 300, "ocr": "secret password",
    }
    tool = DesktopVisualObserve(service=type("Service", (), {"observe": lambda *_, **__: unsafe})())

    result = asyncio.run(tool.run(
        _session=type("S", (), {"id": "visual-a"})(), _context=_context(),
    ))

    assert result.ok is False
    assert result.error == "desktop_visual_failed"
    assert "secret" not in str(result.content).lower()


def test_visual_tool_has_no_desktop_action_or_reference_api():
    from jarvis.agent.tools.desktop_visual_observe import DesktopVisualObserve

    forbidden = {"click", "toggle", "select_option", "set_value", "scroll", "key", "type", "drag",
                 "reference", "element_id", "screenshot", "save", "persist"}
    assert not forbidden & set(dir(DesktopVisualObserve))
