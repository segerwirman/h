"""Safety contract for the future native CUA/vision action boundary."""
from __future__ import annotations

import pytest

from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _tree(*, name: str = "Kirim", role: str = "button", confidence: float = 0.95):
    tree = ScreenElementTree()
    tree.add(UIElement(
        element_id="uia-send",
        scope=ElementScope.PAGE_MAIN,
        role=role,
        name=name,
        rect=(100, 100, 80, 30),
        confidence=confidence,
        provenance="uia",
        timestamp=100.0,
    ))
    return tree


def test_observe_issues_stable_semantic_ref_for_actionable_element():
    from jarvis.automation.cua_safety import CuaSafetyGate

    gate = CuaSafetyGate(max_age_s=10)
    observation = gate.observe(surface_id="window:mail", tree=_tree(), now=100.0)

    ref = gate.reference(observation.id, "uia-send", now=101.0)

    assert ref.surface_id == "window:mail"
    assert ref.element_id == "uia-send"
    assert ref.role == "button"
    assert ref.label == "Kirim"


def test_ref_requires_current_observation_and_rejects_stale_capture():
    from jarvis.automation.cua_safety import CuaSafetyGate, StaleObservationError

    gate = CuaSafetyGate(max_age_s=5)
    first = gate.observe(surface_id="window:mail", tree=_tree(), now=100.0)
    ref = gate.reference(first.id, "uia-send", now=101.0)
    gate.observe(surface_id="window:mail", tree=_tree(), now=102.0)

    with pytest.raises(StaleObservationError):
        gate.evaluate(ref, action="click", now=103.0)

    expired = CuaSafetyGate(max_age_s=5).observe(
        surface_id="window:mail", tree=_tree(), now=100.0)
    with pytest.raises(StaleObservationError):
        CuaSafetyGate(max_age_s=5).reference(expired.id, "uia-send", now=106.0)


def test_low_confidence_or_unknown_element_never_receives_ref():
    from jarvis.automation.cua_safety import CuaSafetyGate, UnsafeTargetError

    gate = CuaSafetyGate()
    observation = gate.observe(
        surface_id="window:mail", tree=_tree(role="unknown", confidence=0.2), now=100.0)

    with pytest.raises(UnsafeTargetError):
        gate.reference(observation.id, "uia-send", now=100.0)


def test_sensitive_surfaces_are_blocked_even_with_semantic_ref():
    from jarvis.automation.cua_safety import ConfirmationClass, CuaSafetyGate

    gate = CuaSafetyGate()
    observation = gate.observe(
        surface_id="window:bank", tree=_tree(name="Enter password"), now=100.0)
    ref = gate.reference(observation.id, "uia-send", now=100.0)

    decision = gate.evaluate(ref, action="type", now=100.0)

    assert decision.classification is ConfirmationClass.BLOCK
    assert "sensitif" in decision.reason


def test_destructive_semantic_target_requires_confirmation():
    from jarvis.automation.cua_safety import ConfirmationClass, CuaSafetyGate

    gate = CuaSafetyGate()
    observation = gate.observe(
        surface_id="window:files", tree=_tree(name="Delete all files"), now=100.0)
    ref = gate.reference(observation.id, "uia-send", now=100.0)

    decision = gate.evaluate(ref, action="click", now=100.0)

    assert decision.classification is ConfirmationClass.CONFIRM
    assert decision.requires_confirmation is True


def test_post_action_verification_requires_newer_recapture_same_surface():
    from jarvis.automation.cua_safety import CuaSafetyGate

    gate = CuaSafetyGate()
    before = gate.observe(surface_id="window:mail", tree=_tree(), now=100.0)
    same = gate.observe(surface_id="window:other", tree=_tree(), now=101.0)
    after = gate.observe(surface_id="window:mail", tree=_tree(), now=102.0)

    assert gate.verify_recapture(before, same) is False
    assert gate.verify_recapture(before, after) is True


def test_observation_store_stays_bounded_under_repeated_soak_cycles():
    """A long soak run must not leak observation snapshots without bound."""
    from jarvis.automation.cua_safety import CuaSafetyGate

    gate = CuaSafetyGate(max_retained_observations=8)

    for index in range(200):
        observation = gate.observe(surface_id="window:mail", tree=_tree(), now=100.0 + index)
        gate.invalidate(observation.id)

    assert len(gate._observations) <= 8
    assert len(gate._latest_by_surface) <= 8


def test_bounded_retention_never_evicts_the_current_surface_observation():
    """Eviction must keep whichever snapshot is still the latest per surface."""
    from jarvis.automation.cua_safety import CuaSafetyGate, StaleObservationError

    gate = CuaSafetyGate(max_retained_observations=4)

    latest = gate.observe(surface_id="window:keep", tree=_tree(), now=100.0)
    for index in range(50):
        other = gate.observe(surface_id="window:churn", tree=_tree(), now=101.0 + index)
        gate.invalidate(other.id)

    # The untouched surface's current observation must survive eviction.
    ref = gate.reference(latest.id, "uia-send", now=100.0)
    assert ref.observation_id == latest.id


def test_redacted_surface_cannot_issue_action_ref():
    from jarvis.automation.cua_safety import CuaSafetyGate, UnsafeTargetError

    gate = CuaSafetyGate()
    observation = gate.observe(
        surface_id="window:password-manager", tree=_tree(), privacy="redacted", now=100.0)

    with pytest.raises(UnsafeTargetError):
        gate.reference(observation.id, "uia-send", now=100.0)
