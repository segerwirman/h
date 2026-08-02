"""A48: title verification must prove committed UIA value change.

Regression: set_content_title verified on recapture+RuntimeId only, so a native
no-op (SetValue ignored by the app) was reported verified. Contract: the native
setter returns a bool proving the committed ValuePattern value changed; verified
requires that bool AND recapture identity proof. Raw values never leave the
session boundary.
"""
from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
from jarvis.automation.cua_safety import CuaSafetyGate
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


class _Desktop:
    def claim(self, _owner):
        return True

    def release(self, _owner):
        pass


def _tree(runtime_id="rt-title"):
    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-title", ElementScope.PAGE_MAIN, "text_field", name="Judul Project",
        rect=(1, 2, 100, 20), visible=True, confidence=.95, provenance="uia",
        states={"_uia_runtime_id": runtime_id, "disabled": False},
    ))
    return tree


def _frames():
    return iter([
        CaptureFrame("uia:studio", _tree()),
        CaptureFrame("uia:studio", _tree()),
    ])


def _authority(native):
    frames = _frames()
    gate = CuaSafetyGate()
    session = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        desktop=_Desktop(), set_text_native=native,
    )
    return session


def test_title_not_verified_when_committed_value_did_not_change():
    calls = []

    def native(ref, title):
        calls.append(title)
        return False  # committed value did not change

    session = _authority(native)
    observation = session.observe_for("desktop-a")
    outcome, error = session.set_content_title(
        observation.id, "uia-title", title="Peluncuran Lokal", session_id="desktop-a")
    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert outcome.ok is False
    assert calls and calls[0] == "Peluncuran Lokal"


def test_title_verified_when_committed_value_changed():
    calls = []

    def native(ref, title):
        calls.append(title)
        return True  # committed value changed

    session = _authority(native)
    observation = session.observe_for("desktop-a")
    outcome, error = session.set_content_title(
        observation.id, "uia-title", title="Peluncuran Lokal", session_id="desktop-a")
    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is True
    assert outcome.ok is True


def test_title_setter_raising_returns_executed_unverified():
    def native(ref, title):
        raise RuntimeError("executor gagal")

    session = _authority(native)
    observation = session.observe_for("desktop-a")
    outcome, error = session.set_content_title(
        observation.id, "uia-title", title="Peluncuran Lokal", session_id="desktop-a")
    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert outcome.ok is False


def test_title_verified_requires_recapture_identity_even_when_committed():
    def native(ref, title):
        return True  # committed, but identity must still be proven

    frames = iter([
        CaptureFrame("uia:studio", _tree()),
        CaptureFrame("uia:studio", _tree(runtime_id="rt-CHANGED")),
    ])
    gate = CuaSafetyGate()
    session = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        desktop=_Desktop(), set_text_native=native,
    )
    observation = session.observe_for("desktop-a")
    outcome, error = session.set_content_title(
        observation.id, "uia-title", title="Peluncuran Lokal", session_id="desktop-a")
    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert outcome.ok is False
