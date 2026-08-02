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


def test_visual_service_blocks_denylisted_window_before_pixel_capture():
    from jarvis.automation.visual_observe import VisualObserveService

    calls = []
    service = VisualObserveService(
        foreground=lambda: ("My Password Vault", "Vault"),
        capture=lambda: calls.append("capture"),
        denylisted=lambda *_: True,
    )

    report = service.observe(session_id="visual-a")

    assert report is None
    assert calls == []


def test_visual_service_never_persists_image_or_exposes_pixels_or_ocr():
    import numpy as np
    from PIL import Image
    from jarvis.automation.visual_observe import VisualObserveService

    service = VisualObserveService(
        foreground=lambda: ("Demo", "Demo"),
        capture=lambda: Image.fromarray(np.full((20, 30, 3), 128, dtype=np.uint8), "RGB"),
        denylisted=lambda *_: False,
    )

    report = service.observe(session_id="visual-a")

    assert set(report) == {"visual_observation_id", "brightness", "complexity", "dominant_tone"}
    assert report["brightness"] in {"dark", "balanced", "bright"}
    assert report["complexity"] in {"low", "medium", "high"}
    assert report["dominant_tone"] in {"warm", "neutral", "cool"}
    assert not hasattr(service, "history")
    assert not hasattr(service, "last_image")


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


def test_visual_correlation_id_cannot_be_used_as_desktop_safe_action_ref():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement

    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-button", ElementScope.PAGE_MAIN, "button", name="Next",
        rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
        states={"_uia_runtime_id": "fixture-next"},
    ))
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)), lambda _rect: None,
    )
    observation = authority.observe_for("visual-a")

    outcome, error = authority.click(
        "visual-correlation-not-observation-id", "uia-button", session_id="visual-a")

    assert outcome is None
    assert "observasi" in error
    assert observation.id != "visual-correlation-not-observation-id"


def test_visual_tool_has_no_desktop_action_or_reference_api():
    from jarvis.agent.tools.desktop_visual_observe import DesktopVisualObserve

    forbidden = {"click", "toggle", "select_option", "set_value", "scroll", "key", "type", "drag",
                 "reference", "element_id", "screenshot", "save", "persist"}
    assert not forbidden & set(dir(DesktopVisualObserve))
