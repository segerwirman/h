"""Phase 18A: voice is ingress only for bounded desktop proposals."""
from __future__ import annotations

import pytest


def test_partial_voice_transcript_cannot_create_proposal():
    from jarvis.integrations.voice_desktop_proposals import VoiceDesktopProposalQueue
    queue = VoiceDesktopProposalQueue()
    assert queue.request_from_voice("aktifkan fokus", final=False) == {"accepted": False, "reason": "voice_transcript_not_final"}


def test_known_final_voice_phrase_creates_metadata_only_proposal():
    from jarvis.integrations.voice_desktop_proposals import VoiceDesktopProposalQueue
    queue = VoiceDesktopProposalQueue(ttl_s=30, now=lambda: 10.0)
    result = queue.request_from_voice("aktifkan mode fokus", final=True)
    assert result["accepted"] is True
    proposal = queue.get(result["proposal_id"])
    assert proposal.action == "focus_mode_enable"
    assert proposal.status == "pending_local_approval"
    assert "aktifkan" not in repr(proposal).lower()
    assert not {"observation_id", "element_id", "coordinate", "label", "text"} & set(proposal.safe_dict())


def test_ambiguous_or_unsupported_voice_is_rejected_without_proposal():
    from jarvis.integrations.voice_desktop_proposals import VoiceDesktopProposalQueue
    queue = VoiceDesktopProposalQueue()
    assert queue.request_from_voice("ubah itu", final=True) == {"accepted": False, "reason": "voice_proposal_ambiguous"}
    assert queue.request_from_voice("klik tombol beli", final=True) == {"accepted": False, "reason": "voice_proposal_unsupported"}


def test_local_approval_requires_fresh_local_executor_and_is_one_shot():
    from jarvis.integrations.voice_desktop_proposals import VoiceDesktopProposalQueue
    queue = VoiceDesktopProposalQueue(now=lambda: 10.0)
    proposal_id = queue.request_from_voice("aktifkan mode fokus", final=True)["proposal_id"]
    calls = []
    assert queue.approve_local(proposal_id, executor=lambda action: calls.append(action) or True) == {"executed": True, "status": "approved"}
    assert calls == ["focus_mode_enable"]
    assert queue.approve_local(proposal_id, executor=lambda _: True) == {"executed": False, "reason": "voice_proposal_not_pending"}


def test_expired_proposal_cannot_be_approved():
    from jarvis.integrations.voice_desktop_proposals import VoiceDesktopProposalQueue
    clock = [10.0]
    queue = VoiceDesktopProposalQueue(ttl_s=5, now=lambda: clock[0])
    proposal_id = queue.request_from_voice("nonaktifkan mode fokus", final=True)["proposal_id"]
    clock[0] = 16.0
    assert queue.approve_local(proposal_id, executor=lambda _: True) == {"executed": False, "reason": "voice_proposal_expired"}


def test_executor_failure_has_safe_reason_and_no_raw_error():
    from jarvis.integrations.voice_desktop_proposals import VoiceDesktopProposalQueue
    queue = VoiceDesktopProposalQueue()
    proposal_id = queue.request_from_voice("aktifkan mode fokus", final=True)["proposal_id"]
    result = queue.approve_local(proposal_id, executor=lambda _: (_ for _ in ()).throw(RuntimeError("coordinates secret")))
    assert result == {"executed": False, "reason": "voice_proposal_execution_failed"}
    assert "coordinates" not in str(result)


def test_queue_source_never_imports_desktop_executor_or_voice_live_control():
    from jarvis.integrations import voice_desktop_proposals
    source = open(voice_desktop_proposals.__file__, encoding="utf-8").read()
    for forbidden in ("desktop_safe_click", "CuaSafetyGate", "uia_capture", "computer_use", "send_from_anywhere"):
        assert forbidden not in source
