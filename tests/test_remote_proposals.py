"""Phase 15B remote metadata-only proposal queue."""
from __future__ import annotations


def test_paired_actor_creates_bound_metadata_only_focus_proposal():
    from jarvis.agent.remote_proposals import RemoteProposalQueue

    queue = RemoteProposalQueue(now=lambda: 10.0)
    result = queue.request(actor_id="telegram:42", session_id="chat:42", action="focus_mode_enable")
    assert result == {"accepted": True, "proposal_id": result["proposal_id"], "action": "focus_mode_enable"}
    proposal = queue.get(result["proposal_id"], actor_id="telegram:42", session_id="chat:42")
    assert proposal.safe_dict() == {"id": result["proposal_id"], "action": "focus_mode_enable", "status": "pending_local_approval"}
    assert not {"actor_id", "session_id", "args", "coordinates", "screenshot", "secret"} & set(proposal.safe_dict())


def test_unpaired_or_unknown_action_never_creates_proposal():
    from jarvis.agent.remote_proposals import RemoteProposalQueue

    queue = RemoteProposalQueue()
    assert queue.request(actor_id="telegram:7", session_id="chat:7", action="focus_mode_enable", paired=False) == {"accepted": False, "reason": "remote_proposal_actor_unpaired"}
    assert queue.request(actor_id="telegram:7", session_id="chat:7", action="desktop_click") == {"accepted": False, "reason": "remote_proposal_action_rejected"}


def test_binding_ttl_one_shot_and_cancel_fail_closed():
    from jarvis.agent.remote_proposals import RemoteProposalQueue

    clock = [10.0]
    queue = RemoteProposalQueue(ttl_s=5, now=lambda: clock[0])
    rid = queue.request(actor_id="telegram:42", session_id="chat:42", action="focus_mode_disable")["proposal_id"]
    assert queue.approve_local(rid, actor_id="telegram:9", session_id="chat:42", executor=lambda _: True) == {"executed": False, "reason": "remote_proposal_context_stale"}
    assert queue.cancel_local(rid, actor_id="telegram:42", session_id="chat:42") == {"cancelled": True}
    assert queue.approve_local(rid, actor_id="telegram:42", session_id="chat:42", executor=lambda _: True) == {"executed": False, "reason": "remote_proposal_not_pending"}
    rid = queue.request(actor_id="telegram:42", session_id="chat:42", action="focus_mode_enable")["proposal_id"]
    clock[0] = 16.0
    assert queue.approve_local(rid, actor_id="telegram:42", session_id="chat:42", executor=lambda _: True) == {"executed": False, "reason": "remote_proposal_expired"}


def test_local_approval_uses_fresh_executor_once_and_never_leaks_error():
    from jarvis.agent.remote_proposals import RemoteProposalQueue

    queue = RemoteProposalQueue()
    rid = queue.request(actor_id="telegram:42", session_id="chat:42", action="focus_mode_enable")["proposal_id"]
    seen = []
    assert queue.approve_local(rid, actor_id="telegram:42", session_id="chat:42", executor=lambda action: seen.append(action) or True) == {"executed": True, "status": "approved"}
    assert seen == ["focus_mode_enable"]
    assert queue.approve_local(rid, actor_id="telegram:42", session_id="chat:42", executor=lambda _: True) == {"executed": False, "reason": "remote_proposal_not_pending"}


def test_reentrant_executor_cannot_consume_same_proposal_twice():
    from jarvis.agent.remote_proposals import RemoteProposalQueue

    queue = RemoteProposalQueue()
    rid = queue.request(
        actor_id="telegram:42", session_id="chat:42", action="focus_mode_enable",
    )["proposal_id"]
    nested = []

    def executor(_action):
        nested.append(queue.approve_local(
            rid, actor_id="telegram:42", session_id="chat:42", executor=lambda _: True,
        ))
        return True

    result = queue.approve_local(
        rid, actor_id="telegram:42", session_id="chat:42", executor=executor,
    )

    assert result == {"executed": True, "status": "approved"}
    assert nested == [{"executed": False, "reason": "remote_proposal_not_pending"}]


def test_queue_has_no_telegram_uia_or_generic_action_authority():
    from jarvis.agent import remote_proposals
    source = open(remote_proposals.__file__, encoding="utf-8").read().lower()
    for forbidden in ("telegram", "uia", "coordinate", "screenshot", "dispatch", "desktop_safe", "send_from_anywhere"):
        assert forbidden not in source
