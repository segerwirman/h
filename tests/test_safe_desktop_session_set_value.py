"""Internal SafeDesktopSession set-value contract; no tool exposure yet."""
from __future__ import annotations

from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _tree(value: float, *, runtime_id: str = "fixture-slider") -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        element_id="uia-slider", scope=ElementScope.PAGE_MAIN, role="slider",
        name="JARVIS fixture slider", rect=(10, 20, 100, 20), visible=True, confidence=.95,
        provenance="uia", states={"value": value, "minimum": 0.0, "maximum": 100.0,
                                   "_uia_runtime_id": runtime_id},
    ))
    return tree


def _authority(*, changed=True):
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((CaptureFrame("uia:fixture", _tree(25.0)),
                   CaptureFrame("uia:fixture", _tree(30.0 if changed else 25.0))))
    gate = CuaSafetyGate()
    sets = []
    class Lease:
        def __init__(self): self.calls = []
        def claim(self, owner): self.calls.append(("claim", owner)); return True
        def release(self, owner): self.calls.append(("release", owner))
    lease = Lease()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        desktop=lease, set_value_native=lambda ref, value: sets.append((ref, value)),
    )
    return authority, sets, lease


def test_set_value_same_session_in_range_executes_once_and_verifies_exact_value():
    authority, sets, lease = _authority(changed=True)
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.set_value(
        observation.id, "uia-slider", 30.0, session_id="desktop-a")

    assert error == ""
    assert outcome.ok is True
    assert outcome.executed is True
    assert outcome.verified is True
    assert [(ref.rect, value) for ref, value in sets] == [((10, 20, 100, 20), 30.0)]
    assert lease.calls == [("claim", "desktop-a"), ("release", "desktop-a")]


def test_set_value_rejects_out_of_range_before_executor():
    authority, sets, _ = _authority()
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.set_value(
        observation.id, "uia-slider", 101.0, session_id="desktop-a")

    assert outcome is None
    assert "rentang" in error
    assert sets == []


def test_set_value_rejects_cross_session_before_executor():
    authority, sets, _ = _authority()
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.set_value(
        observation.id, "uia-slider", 30.0, session_id="desktop-b")

    assert outcome is None
    assert "sesi" in error
    assert sets == []


def test_set_value_recapture_same_surface_but_unchanged_value_is_unverified_without_retry():
    authority, sets, _ = _authority(changed=False)
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.set_value(
        observation.id, "uia-slider", 30.0, session_id="desktop-a")

    assert error == ""
    assert outcome.ok is False
    assert outcome.executed is True
    assert outcome.verified is False
    assert [(ref.rect, value) for ref, value in sets] == [((10, 20, 100, 20), 30.0)]


def test_set_value_recapture_rejects_replaced_slider_identity_after_native_set():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(25.0, runtime_id="first-slider")),
        CaptureFrame("uia:fixture", _tree(30.0, runtime_id="replacement-slider")),
    ))
    gate = CuaSafetyGate()
    calls = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        set_value_native=lambda ref, value: calls.append((ref, value)),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.set_value(
        observation.id, "uia-slider", 30.0, session_id="desktop-a")

    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert len(calls) == 1


def test_set_value_rejects_non_slider_before_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    tree.add(UIElement("uia-button", ElementScope.PAGE_MAIN, "button", name="Next",
                       rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia"))
    gate = CuaSafetyGate()
    sets = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None, set_value_native=lambda *args: sets.append(args),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.set_value(
        observation.id, "uia-button", 30.0, session_id="desktop-a")

    assert outcome is None
    assert "slider" in error
    assert sets == []


def test_set_value_invalidates_old_observation_after_attempt():
    authority, _sets, _ = _authority()
    observation = authority.observe_for("desktop-a")

    authority.set_value(observation.id, "uia-slider", 30.0, session_id="desktop-a")
    again, error = authority.set_value(observation.id, "uia-slider", 31.0, session_id="desktop-a")

    assert again is None
    assert "observasi" in error


def test_safe_session_has_no_type_key_drag_or_coordinate_setter_api():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession

    assert hasattr(SafeDesktopSession, "set_value")
    assert not hasattr(SafeDesktopSession, "type")
    assert not hasattr(SafeDesktopSession, "key")
    assert not hasattr(SafeDesktopSession, "drag")
    assert not hasattr(SafeDesktopSession, "set_value_at")
    assert not hasattr(SafeDesktopSession, "vision_analyze")
