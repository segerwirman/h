"""15B narrow remote proposal ingress."""
from __future__ import annotations


def test_ingress_maps_only_exact_allowlisted_phrase_to_bound_request():
    from jarvis.agent.remote_proposal_ingress import stage_text
    from jarvis.agent.remote_proposals import RemoteProposalQueue

    queue = RemoteProposalQueue(now=lambda: 10.0)
    result = stage_text(queue, actor_id="telegram:42", session_id="chat:42", text="aktifkan mode fokus", paired=True)
    assert result["accepted"] is True and result["action"] == "focus_mode_enable"
    assert stage_text(queue, actor_id="telegram:42", session_id="chat:42", text="klik x=1", paired=True) == {"accepted": False, "reason": "remote_proposal_action_rejected"}


def test_ingress_maps_only_exact_allowlisted_media_phrase_to_proposal():
    from jarvis.agent.remote_proposal_ingress import stage_text
    from jarvis.agent.remote_proposals import RemoteProposalQueue

    queue = RemoteProposalQueue(now=lambda: 10.0)
    result = stage_text(queue, actor_id="telegram:42", session_id="chat:42", text="pause media", paired=True)
    assert result["accepted"] is True
    assert result["action"] == "media_pause"
    assert stage_text(queue, actor_id="telegram:42", session_id="chat:42", text="buka youtube", paired=True) == {"accepted": False, "reason": "remote_proposal_action_rejected"}


def test_ingress_rejects_unpaired_without_staging():
    from jarvis.agent.remote_proposal_ingress import stage_text
    from jarvis.agent.remote_proposals import RemoteProposalQueue

    assert stage_text(RemoteProposalQueue(), actor_id="telegram:9", session_id="chat:9", text="matikan mode fokus", paired=False) == {"accepted": False, "reason": "remote_proposal_actor_unpaired"}


def test_ingress_rejects_non_boolean_pairing_and_empty_binding():
    from jarvis.agent.remote_proposal_ingress import stage_text
    from jarvis.agent.remote_proposals import RemoteProposalQueue

    queue = RemoteProposalQueue()
    for actor_id, session_id, paired in (
        ("telegram:9", "chat:9", "false"),
        ("telegram:9", "chat:9", 1),
        ("", "chat:9", True),
        ("telegram:9", "", True),
    ):
        result = stage_text(
            queue, actor_id=actor_id, session_id=session_id,
            text="aktifkan mode fokus", paired=paired,
        )
        assert result == {"accepted": False, "reason": "remote_proposal_context_rejected"}


def test_ingress_source_has_no_generic_or_sensitive_argument_surface():
    from jarvis.agent import remote_proposal_ingress
    source = open(remote_proposal_ingress.__file__, encoding="utf-8").read().lower()
    for forbidden in ("coordinate", "screenshot", "uia", "secret", "dispatch", "desktop_safe"):
        assert forbidden not in source
