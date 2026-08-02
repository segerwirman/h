"""Semantic bounded scroll is session-bound and requires visible-state proof."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _tree(state: str, *, runtime_id: str = "fixture-scrollbar") -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        element_id="uia-scroll", scope=ElementScope.PAGE_MAIN, role="scrollbar",
        name="", rect=(10, 20, 20, 200), visible=True, confidence=.95,
        provenance="uia", states={"position": state, "_uia_runtime_id": runtime_id},
    ))
    return tree


def test_safe_scroll_recapture_rejects_replaced_scrollbar_identity_after_attempt():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree("before", runtime_id="original")),
        CaptureFrame("uia:fixture", _tree("after", runtime_id="replacement")),
    ))
    gate = CuaSafetyGate()
    calls = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        scroll_rect=lambda rect, delta: calls.append((rect, delta)),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.scroll(
        observation.id, "uia-scroll", direction="down", session_id="desktop-a")

    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert calls == [((10, 20, 20, 200), -3)]


def _context() -> ExecutionContext:
    return ExecutionContext.create(
        source="agent", actor_id="local", session_id="desktop-a", surface="desktop",
        toolsets=["desktop_safe"],
    )


def _authority(*, changed=True):
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    trees = iter((_tree("before"), _tree("after" if changed else "before")))
    gate = CuaSafetyGate()
    scrolls = []
    return SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", next(trees))),
        lambda _rect: None, scroll_rect=lambda rect, dy: scrolls.append((rect, dy)),
    ), scrolls


def test_desktop_safe_scroll_schema_only_accepts_semantic_ids_and_bounded_direction():
    from jarvis.agent.tools.desktop_safe_scroll import DesktopSafeScroll

    props = DesktopSafeScroll().json_schema()["properties"]

    assert set(props) == {"observation_id", "element_id", "direction"}
    assert "x" not in props and "y" not in props and "dy" not in props
    assert props["direction"]["enum"] == ["down", "up"]


def test_safe_scroll_requires_scrollbar_ref_and_proves_recaptured_state_changed():
    from jarvis.agent.tools.desktop_safe_scroll import DesktopSafeScroll

    authority, scrolls = _authority(changed=True)
    observation = authority.observe_for("desktop-a")
    result = asyncio.run(DesktopSafeScroll(session=authority).run(
        observation_id=observation.id, element_id="uia-scroll", direction="down",
        _session=type("S", (), {"id": "desktop-a"})(), _context=_context()))

    assert result.ok is True
    assert result.meta["verified"] is True
    assert scrolls == [((10, 20, 20, 200), -3)]


def test_safe_scroll_fails_closed_when_recapture_state_does_not_change():
    from jarvis.agent.tools.desktop_safe_scroll import DesktopSafeScroll

    authority, scrolls = _authority(changed=False)
    observation = authority.observe_for("desktop-a")
    result = asyncio.run(DesktopSafeScroll(session=authority).run(
        observation_id=observation.id, element_id="uia-scroll", direction="down",
        _session=type("S", (), {"id": "desktop-a"})(), _context=_context()))

    assert result.ok is False
    assert result.meta["executed"] is True
    assert result.meta["verified"] is False
    assert scrolls == [((10, 20, 20, 200), -3)]


def test_safe_scroll_rejects_non_scrollbar_before_executor():
    from jarvis.agent.tools.desktop_safe_scroll import DesktopSafeScroll
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    tree.add(UIElement("uia-button", ElementScope.PAGE_MAIN, "button", name="Next",
                       rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia"))
    gate = CuaSafetyGate()
    scrolls = []
    authority = SafeDesktopSession(gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
                                   lambda _r: None, scroll_rect=lambda *args: scrolls.append(args))
    observation = authority.observe_for("desktop-a")
    result = asyncio.run(DesktopSafeScroll(session=authority).run(
        observation_id=observation.id, element_id="uia-button", direction="down",
        _session=type("S", (), {"id": "desktop-a"})(), _context=_context()))

    assert result.ok is False
    assert scrolls == []
