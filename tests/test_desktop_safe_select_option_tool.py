"""Fase 10: pilihan dropdown UIA hanya dari option yang sudah terlihat."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _context(session_id: str = "desktop-a") -> ExecutionContext:
    return ExecutionContext.create(
        source="agent", actor_id="local", session_id=session_id, surface="desktop",
        toolsets=["desktop_safe"],
    )


def _tree(*, selected: bool = False, option_name: str = "Safe mode",
          parent_identity: str | None = "fixture-dropdown") -> ScreenElementTree:
    tree = ScreenElementTree()
    states = {"selected": selected, "_uia_runtime_id": "fixture-option"}
    if parent_identity is not None:
        states["_uia_parent_runtime_id"] = parent_identity
    tree.add(UIElement(
        "uia-option", ElementScope.PAGE_MAIN, "dropdown_option", name=option_name,
        rect=(10, 40, 120, 24), visible=True, confidence=.95, provenance="uia",
        states=states,
    ))
    return tree


def _authority(*, option_name: str = "Safe mode", native_committed: bool = True):
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(selected=False, option_name=option_name)),
        CaptureFrame("uia:fixture", _tree(selected=True, option_name=option_name)),
    ))
    gate = CuaSafetyGate()
    calls = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        select_option_native=lambda ref: (calls.append(ref), native_committed)[1],
    )
    return authority, calls


def test_desktop_observe_exposes_visible_dropdown_option_as_opaque_select_ref():
    from jarvis.agent.tools.desktop_observe import DesktopObserve

    authority, _ = _authority()
    result = asyncio.run(DesktopObserve(session=authority).run(
        _session=type("Session", (), {"id": "desktop-a"})(), _context=_context()))

    assert result.ok is True
    assert result.content["elements"] == [{
        "element_id": "uia-option", "role": "dropdown_option", "scope": "page_main",
        "actions": ["select_option"],
    }]
    assert "Safe mode" not in str(result.content)


def test_desktop_observe_hides_dropdown_option_without_stable_parent_identity():
    from jarvis.agent.tools.desktop_observe import DesktopObserve
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = _tree(parent_identity=None)
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None,
    )
    result = asyncio.run(DesktopObserve(session=authority).run(
        _session=type("Session", (), {"id": "desktop-a"})(), _context=_context()))

    assert result.ok is True
    assert result.content["elements"] == []
