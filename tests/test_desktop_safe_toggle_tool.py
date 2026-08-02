"""Direct injected SafeDesktopSession checkbox regressions."""
from __future__ import annotations

from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _tree(*, checked: bool = False, name: str = "Enable safe mode") -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-checkbox", ElementScope.PAGE_MAIN, "checkbox", name=name,
        rect=(10, 40, 180, 24), visible=True, confidence=.95, provenance="uia",
        states={"checked": checked, "_uia_runtime_id": "fixture-checkbox"},
    ))
    return tree

def _authority(*, name: str = "Enable safe mode"):
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(checked=False, name=name)),
        CaptureFrame("uia:fixture", _tree(checked=True, name=name)),
    ))
    gate = CuaSafetyGate()
    calls = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        toggle_native=lambda ref: calls.append(ref),
    )
    return authority, calls

def test_toggle_runs_once_on_safe_checkbox_and_recaptures_changed_state():
    authority, calls = _authority()
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.toggle(observation.id, "uia-checkbox", session_id="desktop-a")

    assert error == ""
    assert outcome.ok is True
    assert outcome.executed is True
    assert outcome.verified is True
    assert len(calls) == 1
    assert calls[0].element_id == "uia-checkbox"

def test_toggle_rejects_destructive_checkbox_before_lease_or_executor():
    authority, calls = _authority(name="Delete all local data")
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.toggle(observation.id, "uia-checkbox", session_id="desktop-a")

    assert outcome is None
    assert "konfirmasi" in error
    assert calls == []

def test_toggle_rejects_disabled_or_missing_binary_state_before_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    for states in (
        {"checked": False, "disabled": True, "_uia_runtime_id": "disabled"},
        {"disabled": False, "_uia_runtime_id": "missing-state"},
    ):
        tree = ScreenElementTree()
        tree.add(UIElement(
            "uia-checkbox", ElementScope.PAGE_MAIN, "checkbox", name="Safe mode",
            rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia", states=states,
        ))
        gate, calls = CuaSafetyGate(), []
        authority = SafeDesktopSession(
            gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
            lambda _rect: None, toggle_native=lambda ref: calls.append(ref),
        )
        observation = authority.observe_for("desktop-a")
        outcome, error = authority.toggle(observation.id, "uia-checkbox", session_id="desktop-a")

        assert outcome is None
        assert calls == []
        assert "checkbox" in error

def test_toggle_rejects_non_checkbox_and_unknown_ids_before_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-radio", ElementScope.PAGE_MAIN, "radio", name="Option A",
        rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
        states={"_uia_runtime_id": "radio"},
    ))
    gate, calls = CuaSafetyGate(), []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None, toggle_native=lambda ref: calls.append(ref),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.toggle(observation.id, "uia-radio", session_id="desktop-a")

    assert outcome is None
    assert "checkbox" in error
    assert calls == []
