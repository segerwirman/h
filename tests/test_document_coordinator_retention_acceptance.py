"""P2-E offline acceptance for bounded document coordinator retention."""
from __future__ import annotations

from jarvis.nlp.document_lifecycle import (
    DocumentCoordinator,
    DocumentExplanation,
)


_TEXT = "\n\n".join(
    f"Bagian {index}: dokumen sintetis untuk retention P2-E."
    for index in range(40)
)


def test_same_fingerprint_reuses_one_lifecycle_within_bound():
    coordinator = DocumentCoordinator(max_lifecycles=2)
    first = coordinator.open_text("p2-e-same", _TEXT, source="first")
    second = coordinator.open_text("p2-e-same", _TEXT, source="second")

    assert first is second
    assert coordinator.get("p2-e-same") is first


def test_coordinator_never_exceeds_max_lifecycles_and_evicts_oldest():
    coordinator = DocumentCoordinator(max_lifecycles=2)
    first = coordinator.open_text("p2-e-first", _TEXT, source="test")
    second = coordinator.open_text("p2-e-second", _TEXT, source="test")
    third = coordinator.open_text("p2-e-third", _TEXT, source="test")

    assert len(coordinator._lifecycles) == 2
    assert coordinator.get("p2-e-first") is None
    assert coordinator.get("p2-e-second") is second
    assert coordinator.get("p2-e-third") is third
    assert first is not second and first is not third


def test_active_explanation_remains_local_after_owner_eviction():
    coordinator = DocumentCoordinator(max_lifecycles=1)
    retained = coordinator.open_text("p2-e-active", _TEXT, source="test")
    token = retained.begin_request()
    explanation = DocumentExplanation(retained, token)
    first_submission = explanation.next_submission()
    assert first_submission is not None
    assert retained.is_active(token) is True

    coordinator.open_text("p2-e-new", _TEXT, source="test")
    assert coordinator.get("p2-e-active") is None
    assert coordinator.get("p2-e-new") is not None
    assert retained.is_active(token) is True
    assert retained.first_unverified() == 0
    assert explanation.pending_segments() == retained.plan_explanation()


def test_reopen_evicted_fingerprint_creates_fresh_owner_without_stale_cursor():
    coordinator = DocumentCoordinator(max_lifecycles=1)
    old = coordinator.open_text("p2-e-reopen", _TEXT, source="old")
    old_token = old.begin_request()
    old.mark_segment_done(0, old_token)
    assert old.first_unverified() == 1

    coordinator.open_text("p2-e-evictor", _TEXT, source="test")
    assert coordinator.get("p2-e-reopen") is None

    fresh = coordinator.open_text("p2-e-reopen", _TEXT, source="fresh")
    assert fresh is not old
    assert fresh.generation_token == ""
    assert fresh.first_unverified() == 0
    assert fresh.verified_count() == 0
    fresh_token = fresh.begin_request()
    assert fresh.is_active(fresh_token) is True
    assert old.is_active(old_token) is True
    assert old.first_unverified() == 1
