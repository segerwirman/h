"""Direct injected SafeDesktopSession click regressions."""
from __future__ import annotations

from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _tree(name: str = "Next", *, runtime_id: str = "fixture-button") -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        element_id="uia-next", scope=ElementScope.PAGE_MAIN, role="button",
        name=name, rect=(10, 20, 100, 40), visible=True,
        confidence=0.95, provenance="uia",
        states={"_uia_runtime_id": runtime_id},
    ))
    return tree

def test_safe_click_rejects_replaced_target_before_executor_even_when_id_rect_surface_match():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(runtime_id="original")),
        CaptureFrame("uia:fixture", _tree(runtime_id="replacement")),
    ))
    clicks = []
    gate = CuaSafetyGate()

    def native_click(ref):
        if ref.native_identity != "replacement":
            raise RuntimeError("identitas UIA button berubah sebelum click")
        clicks.append(ref)

    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda rect: clicks.append(rect), click_native=native_click,
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.click(
        observation.id, "uia-next", session_id="desktop-a")

    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert "executor gagal" in outcome.reason
    assert clicks == []

def test_safe_click_recapture_rejects_replaced_target_identity_after_attempt():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(name="Before", runtime_id="original")),
        CaptureFrame("uia:fixture", _tree(name="After", runtime_id="replacement")),
    ))
    clicks = []
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda rect: clicks.append(rect),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.click(
        observation.id, "uia-next", session_id="desktop-a")

    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert len(clicks) == 1

def test_safe_click_rejects_guessed_confirm_target_before_native_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    gate = CuaSafetyGate()
    clicks = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", _tree("Delete all"))),
        click_rect=lambda _rect: clicks.append("legacy"),
        click_native=lambda ref: clicks.append(ref),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.click(
        observation.id, "uia-next", session_id="desktop-a")

    assert outcome is None
    assert "konfirmasi" in error
    assert clicks == []

def test_safe_click_rejects_target_without_runtime_identity_before_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = _tree()
    tree._by_id["uia-next"].states.clear()
    gate = CuaSafetyGate()
    clicks = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        click_rect=lambda rect: clicks.append(rect),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.click(observation.id, "uia-next", session_id="desktop-a")

    assert outcome is None
    assert "identitas" in error
    assert clicks == []
