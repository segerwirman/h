"""Direct bounded dropdown-selection session authority regressions."""

from __future__ import annotations

from jarvis.agent.execution_context import ExecutionContext

from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement

def _context(session_id: str = "desktop-a") -> ExecutionContext:
    return ExecutionContext.create(
        source="agent", actor_id="local", session_id=session_id, surface="desktop",
        toolsets=["desktop_safe"],
    )

def _tree(*, selected: bool = False, option_name: str = "Safe mode") -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-option", ElementScope.PAGE_MAIN, "dropdown_option", name=option_name,
        rect=(10, 40, 120, 24), visible=True, confidence=.95, provenance="uia",
        states={"selected": selected, "_uia_runtime_id": "fixture-option",
                "_uia_parent_runtime_id": "fixture-dropdown"},
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

def test_select_option_only_runs_already_visible_safe_option_once_and_recaptures():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession

    authority, calls = _authority()
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.select_option(
        observation.id, "uia-option", session_id="desktop-a")

    assert error == ""
    assert outcome.ok is True
    assert outcome.executed is True
    assert outcome.verified is True
    assert len(calls) == 1
    assert calls[0].element_id == "uia-option"

def test_select_option_does_not_verify_when_parent_value_did_not_change():
    authority, calls = _authority(native_committed=False)
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.select_option(
        observation.id, "uia-option", session_id="desktop-a")

    assert error == ""
    assert outcome.ok is False
    assert outcome.executed is True
    assert outcome.verified is False
    assert len(calls) == 1


def test_select_option_rejects_destructive_option_before_lease_or_executor():
    authority, calls = _authority(option_name="Delete all")
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.select_option(
        observation.id, "uia-option", session_id="desktop-a")

    assert outcome is None
    assert "konfirmasi" in error
    assert calls == []

def test_select_option_rejects_non_option_and_unknown_id_before_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-button", ElementScope.PAGE_MAIN, "button", name="Next",
        rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
        states={"_uia_runtime_id": "button"},
    ))
    gate, calls = CuaSafetyGate(), []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None, select_option_native=lambda ref: calls.append(ref),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.select_option(
        observation.id, "uia-button", session_id="desktop-a")

    assert outcome is None
    assert "option" in error
    assert calls == []
