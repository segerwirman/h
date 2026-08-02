"""Phase 20 RED — desktop_safe reorder execution with same-surface RuntimeId proof."""

import pytest


def _make_gate_tree():
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.core.element_model import ScreenElementTree, UIElement, ElementScope

    gate = CuaSafetyGate(max_age_s=60)
    tree = ScreenElementTree()
    # simulate Content Studio scene list cards with runtime ids
    for i in range(3):
        tree.add(UIElement(
            element_id=f"uia-{i+1}",
            scope=ElementScope.PAGE_MAIN,
            role="card",
            name=f"Scene {i}",
            label=f"Scene {i}",
            rect=(10, 50 + i*60, 300, 50),
            visible=True,
            confidence=0.95,
            provenance="uia",
            states={"_uia_runtime_id": f"rt-{i}", "_uia_parent_runtime_id": "rt-parent"},
        ))
    obs = gate.observe(surface_id="uia:content-studio", tree=tree, privacy="normal", now=0)
    return gate, obs


def test_reorder_requires_same_surface_runtime_ids():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession, CaptureAdapter
    from unittest.mock import MagicMock

    gate, obs = _make_gate_tree()

    # capture adapter returns same surface but different capture for recapture step
    class FakeBackend:
        def __init__(self):
            self.calls = 0
        def capture(self):
            from jarvis.automation.cua_safe_click import CaptureFrame
            from jarvis.core.element_model import ScreenElementTree, UIElement, ElementScope
            tree = ScreenElementTree()
            for i in range(3):
                tree.add(UIElement(
                    element_id=f"uia-{i+1}",
                    scope=ElementScope.PAGE_MAIN,
                    role="card",
                    name=f"Scene {i}",
                    label=f"Scene {i}",
                    rect=(10, 50 + i*60, 300, 50),
                    visible=True,
                    confidence=0.95,
                    provenance="uia",
                    states={"_uia_runtime_id": f"rt-{i}", "_uia_parent_runtime_id": "rt-parent"},
                ))
            surf = "uia:content-studio"
            return CaptureFrame(surf, tree, "normal")

    backend = FakeBackend()
    adapter = CaptureAdapter(gate, backend.capture)
    # need to re-observe via adapter to own gate
    obs2 = adapter.capture()
    # ownership
    desktop = MagicMock()
    desktop.claim.return_value = True
    desktop.release.return_value = True

    def drag_native(src_ref, dst_ref):
        # check same surface parent identity proof expected in real impl
        assert src_ref.surface_id == dst_ref.surface_id
        assert src_ref.native_identity and dst_ref.native_identity
        assert src_ref.native_identity != dst_ref.native_identity

    session = SafeDesktopSession(
        gate=gate, capture=adapter, click_rect=lambda r: None,
        desktop=desktop,
        click_native=None, scroll_native=None,
        set_value_native=None, set_text_native=None,
        select_option_native=None, toggle_native=None,
    )
    # inject reorder_native via attribute (future field)
    session.reorder_native = drag_native
    session._owners[obs2.id] = "test-session"

    # Should have method reorder_scene after GREEN
    assert hasattr(session, "reorder_scene"), "SafeDesktopSession.reorder_scene must exist"
    outcome, err = session.reorder_scene(obs2.id, "uia-1", "uia-2", session_id="test-session")
    assert outcome is not None or err == ""


def test_reorder_tool_wiring_uses_session():
    # tool must be capability desktop_safe and use registry confirmation
    from jarvis.agent.tools.desktop_safe_reorder_scene import DesktopSafeReorderScene
    assert hasattr(DesktopSafeReorderScene, "confirmation_text")
