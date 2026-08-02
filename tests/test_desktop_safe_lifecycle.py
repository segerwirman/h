"""Fase 7: lease, revoke, dan fault containment desktop-safe."""
from __future__ import annotations

import threading


def test_desktop_service_run_releases_lease_when_operation_raises():
    import pytest

    from jarvis.automation.desktop_service import DesktopService

    desktop = DesktopService()

    with pytest.raises(RuntimeError, match="boom"):
        desktop.run("session-a", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert desktop.claim("session-b") is True


def test_desktop_service_exclusive_claim_allows_only_one_parallel_owner():
    from jarvis.automation.desktop_service import DesktopService

    desktop = DesktopService()
    start = threading.Barrier(3)
    results = []
    guard = threading.Lock()

    def claim(owner: str) -> None:
        start.wait()
        accepted = desktop.claim(owner)
        with guard:
            results.append((owner, accepted))

    first = threading.Thread(target=claim, args=("session-a",))
    second = threading.Thread(target=claim, args=("session-b",))
    first.start()
    second.start()
    start.wait()
    first.join(timeout=2)
    second.join(timeout=2)

    assert sorted(accepted for _, accepted in results) == [False, True]

def test_owner_registry_does_not_leak_across_repeated_soak_action_cycles():
    """Fase 10.5: successful actions must retire their observation ownership."""
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement

    def frame():
        tree = ScreenElementTree()
        tree.add(UIElement(
            "uia-next", ElementScope.PAGE_MAIN, "button", name="Next",
            rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
            states={"_uia_runtime_id": "fixture-next"},
        ))
        return CaptureFrame("uia:fixture", tree)

    gate = CuaSafetyGate()
    authority = SafeDesktopSession(gate, CaptureAdapter(gate, frame), lambda _rect: None)

    for _ in range(100):
        observation = authority.observe_for("session-a")
        outcome, error = authority.click(observation.id, "uia-next", session_id="session-a")
        assert outcome is not None and error == ""

    assert len(authority._owners) <= 4
    assert len(gate._observations) <= 64

def test_clear_all_revokes_every_observation_even_if_same_owner_has_multiple_refs():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement

    def frame():
        tree = ScreenElementTree()
        tree.add(UIElement(
            "uia-next", ElementScope.PAGE_MAIN, "button", name="Next",
            rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
            states={"_uia_runtime_id": "fixture-next"},
        ))
        return CaptureFrame("uia:fixture", tree)

    gate = CuaSafetyGate()
    authority = SafeDesktopSession(gate, CaptureAdapter(gate, frame), lambda _rect: None)
    first = authority.observe_for("session-a")
    second = authority.observe_for("session-a")

    assert authority.clear_all() == 2
    assert authority._owners == {}
    for observation in (first, second):
        outcome, error = authority.click(
            observation.id, "uia-next", session_id="session-a")
        assert outcome is None
        assert "observasi" in error

def test_click_recapture_failure_releases_lease_and_never_retries_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement

    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-next", ElementScope.PAGE_MAIN, "button", name="Next",
        rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
        states={"_uia_runtime_id": "fixture-next"},
    ))

    class Lease:
        def __init__(self): self.calls = []
        def claim(self, owner): self.calls.append(("claim", owner)); return True
        def release(self, owner): self.calls.append(("release", owner))

    calls = []
    lease = Lease()
    gate = CuaSafetyGate()
    captures = iter((CaptureFrame("uia:fixture", tree), RuntimeError("capture failed")))

    def capture():
        item = next(captures)
        if isinstance(item, Exception):
            raise item
        return item

    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, capture), lambda _rect: None, desktop=lease,
        click_native=lambda ref: calls.append(ref),
    )
    observation = authority.observe_for("session-a")

    outcome, error = authority.click(
        observation.id, "uia-next", session_id="session-a")

    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert "recapture" in outcome.reason
    assert len(calls) == 1
    assert lease.calls == [("claim", "session-a"), ("release", "session-a")]
    again, again_error = authority.click(observation.id, "uia-next", session_id="session-a")
    assert again is None
    assert "observasi" in again_error
    assert len(calls) == 1

def test_click_native_exception_is_executed_unverified_and_never_retries():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement

    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-next", ElementScope.PAGE_MAIN, "button", name="Next",
        rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
        states={"_uia_runtime_id": "fixture-next"},
    ))
    gate = CuaSafetyGate()
    attempts = []

    def native_click(ref):
        attempts.append(ref)
        raise RuntimeError("late failure")

    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None, click_native=native_click,
    )
    observation = authority.observe_for("session-a")

    outcome, error = authority.click(
        observation.id, "uia-next", session_id="session-a")

    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert len(attempts) == 1
    again, again_error = authority.click(observation.id, "uia-next", session_id="session-a")
    assert again is None
    assert "observasi" in again_error

def test_clear_all_waits_for_inflight_action_then_revokes_remaining_refs():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement

    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-next", ElementScope.PAGE_MAIN, "button", name="Next",
        rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
        states={"_uia_runtime_id": "fixture-next"},
    ))
    gate = CuaSafetyGate()
    entered = threading.Event()
    release = threading.Event()
    cleared = threading.Event()

    def native_click(_ref):
        entered.set()
        assert release.wait(timeout=2)

    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None, click_native=native_click,
    )
    observation = authority.observe_for("session-a")
    action = threading.Thread(
        target=lambda: authority.click(observation.id, "uia-next", session_id="session-a"),
    )
    action.start()
    assert entered.wait(timeout=2)
    teardown = threading.Thread(target=lambda: (authority.clear_all(), cleared.set()))
    teardown.start()

    assert not cleared.wait(timeout=.1)
    release.set()
    action.join(timeout=2)
    teardown.join(timeout=2)
    assert cleared.is_set()
    again, error = authority.click(observation.id, "uia-next", session_id="session-a")
    assert again is None
    assert "observasi" in error
