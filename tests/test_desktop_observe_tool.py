"""desktop_observe issues bounded semantic refs for one desktop-local session."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _tree() -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        element_id="uia-next", scope=ElementScope.PAGE_MAIN, role="button",
        name="Next", rect=(10, 20, 100, 40), visible=True,
        confidence=0.95, provenance="uia", states={"_uia_runtime_id": "fixture-next"},
    ))
    tree.add(UIElement(
        element_id="uia-secret", scope=ElementScope.PAGE_MAIN, role="button",
        name="Enter password", rect=(10, 70, 100, 40), visible=True,
        confidence=0.95, provenance="uia",
    ))
    return tree


def _context(session_id: str = "desktop-a") -> ExecutionContext:
    return ExecutionContext.create(
        source="agent", actor_id="local", session_id=session_id, surface="desktop",
        toolsets=["desktop_safe"],
    )


def _local_session():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((CaptureFrame("uia:fixture", _tree()), CaptureFrame("uia:fixture", _tree())))
    gate = CuaSafetyGate()
    return SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda _rect: None,
    )


def test_desktop_observe_is_read_only_and_schema_has_no_screenshot_ocr_or_target_query():
    from jarvis.agent.tools.desktop_observe import DesktopObserve

    tool = DesktopObserve()
    assert tool.read_only is True
    assert tool.json_schema()["properties"] == {}
    assert "screenshot" not in tool.description.lower()
    assert "ocr" not in tool.description.lower()


def test_desktop_observe_returns_bounded_safe_semantic_refs_only():
    from jarvis.agent.tools.desktop_observe import DesktopObserve

    result = asyncio.run(DesktopObserve(session=_local_session()).run(
        _session=type("Session", (), {"id": "desktop-a"})(), _context=_context()))

    assert result.ok is True
    refs = result.content["elements"]
    assert result.content["observation_id"]
    assert len(refs) == 1
    assert refs[0] == {"element_id": "uia-next", "role": "button", "scope": "page_main"}
    assert "Next" not in str(result.content)
    assert "password" not in str(result.content).lower()


def test_safe_click_only_accepts_observation_issued_by_same_desktop_session():
    from jarvis.agent.tools.desktop_observe import DesktopObserve
    from jarvis.agent.tools.desktop_safe_click import DesktopSafeClick

    shared = _local_session()
    observe = DesktopObserve(session=shared)
    observed = asyncio.run(observe.run(_session=type("Session", (), {"id": "desktop-a"})(), _context=_context()))
    observation_id = observed.content["observation_id"]

    same = asyncio.run(DesktopSafeClick(session=shared).run(
        observation_id=observation_id, element_id="uia-next",
        _session=type("Session", (), {"id": "desktop-a"})(), _context=_context()))
    other = asyncio.run(DesktopSafeClick(session=shared).run(
        observation_id=observation_id, element_id="uia-next",
        _session=type("Session", (), {"id": "desktop-b"})(), _context=_context("desktop-b")))

    assert same.ok is True
    assert other.ok is False
    assert "sesi" in (other.error or "")


def test_desktop_observe_and_safe_click_stay_out_of_voice_schema():
    from jarvis.agent.tools.desktop_observe import DesktopObserve
    from jarvis.agent.tools.desktop_safe_click import DesktopSafeClick
    from jarvis.integrations import voice_native_tools

    names = {item["name"] for item in voice_native_tools.declarations()}
    assert DesktopObserve.name not in names
    assert DesktopSafeClick.name not in names


def test_desktop_observe_has_no_capture_image_vision_or_coordinate_api():
    from jarvis.agent.tools.desktop_observe import DesktopObserve

    assert not hasattr(DesktopObserve, "screenshot")
    assert not hasattr(DesktopObserve, "vision_analyze")
    assert not hasattr(DesktopObserve, "click_at")
    assert not hasattr(DesktopObserve, "coordinate")
    assert not hasattr(DesktopObserve, "ocr")


def test_desktop_observe_emits_set_value_descriptor_only_for_complete_slider():
    from jarvis.agent.tools.desktop_observe import DesktopObserve
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-slider", ElementScope.PAGE_MAIN, "slider", name="JARVIS fixture slider",
        rect=(1, 2, 100, 20), visible=True, confidence=.95, provenance="uia",
        states={"value": 25.0, "minimum": 0.0, "maximum": 100.0,
                "_uia_runtime_id": "fixture-slider"},
    ))
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None,
    )

    result = asyncio.run(DesktopObserve(session=authority).run(
        _session=type("Session", (), {"id": "desktop-a"})(), _context=_context()))

    assert result.ok is True
    assert result.content["elements"] == [{
        "element_id": "uia-slider", "role": "slider", "scope": "page_main",
        "actions": ["set_value"],
        "value_domain": {"minimum": 0.0, "maximum": 100.0},
    }]


def test_desktop_observe_does_not_emit_set_value_for_unnamed_slider():
    from jarvis.agent.tools.desktop_observe import _safe_descriptor
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-slider", ElementScope.PAGE_MAIN, "slider", name="",
        rect=(1, 2, 100, 20), visible=True, confidence=.95, provenance="uia",
        states={"value": 25.0, "minimum": 0.0, "maximum": 100.0,
                "_uia_runtime_id": "fixture-slider"},
    ))
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None,
    )
    observation = authority.observe_for("desktop-a")

    assert _safe_descriptor(authority, observation.id, tree._by_id["uia-slider"], "page_main") is None


def test_desktop_observe_does_not_emit_set_value_for_text_or_incomplete_slider():
    from jarvis.agent.tools.desktop_observe import DesktopObserve
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    tree.add(UIElement("uia-text", ElementScope.PAGE_COMPOSER, "text_field", name="",
                       rect=(1, 2, 100, 20), visible=True, confidence=.95, provenance="uia"))
    tree.add(UIElement("uia-slider", ElementScope.PAGE_MAIN, "slider", name="",
                       rect=(1, 30, 100, 20), visible=True, confidence=.95, provenance="uia",
                       states={"value": 25.0}))
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None,
    )

    result = asyncio.run(DesktopObserve(session=authority).run(
        _session=type("Session", (), {"id": "desktop-a"})(), _context=_context()))

    assert result.ok is True
    assert result.content["elements"] == []
