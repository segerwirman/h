"""A51a: RemoteProposalQueue thread-safe single execution + hard capacity.

Regression: approve_local checked pending and claimed executing without a lock,
so two threads could both run the executor. Also the queue had no hard capacity.
"""
import threading

from jarvis.agent.remote_proposals import RemoteProposalQueue


def test_concurrent_approve_executes_executor_exactly_once():
    queue = RemoteProposalQueue()
    rid = queue.request(
        actor_id="telegram:42", session_id="chat:42", action="media_play",
    )["proposal_id"]
    calls = []
    gate = threading.Barrier(2)
    original = queue._bound_pending

    def blocked(*args):
        item = original(*args)
        try:
            gate.wait(timeout=2)
        except threading.BrokenBarrierError:
            pass
        return item

    queue._bound_pending = blocked

    def worker():
        return queue.approve_local(
            rid, actor_id="telegram:42", session_id="chat:42",
            executor=lambda _action: calls.append(_action) or True,
        )

    results = [None] * 2
    threads = [
        threading.Thread(target=lambda i=i: results.__setitem__(i, worker()))
        for i in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert len(calls) == 1, f"executor dipanggil {len(calls)}x, harus 1x"
    assert sum(1 for result in results if result.get("executed")) == 1
    assert sum(1 for result in results if not result.get("executed")) == 1


def test_queue_rejects_when_capacity_full():
    queue = RemoteProposalQueue(capacity=2)
    first = queue.request(
        actor_id="telegram:42", session_id="chat:42", action="media_play")
    second = queue.request(
        actor_id="telegram:42", session_id="chat:42", action="media_pause")
    third = queue.request(
        actor_id="telegram:42", session_id="chat:42", action="media_play")
    assert first["accepted"] is True
    assert second["accepted"] is True
    assert third == {"accepted": False, "reason": "remote_proposal_queue_full"}


def test_capacity_counts_live_entries_only():
    queue = RemoteProposalQueue(capacity=2)
    rid = queue.request(
        actor_id="telegram:42", session_id="chat:42", action="media_play",
    )["proposal_id"]
    queue.cancel_local(rid, actor_id="telegram:42", session_id="chat:42")
    again = queue.request(
        actor_id="telegram:42", session_id="chat:42", action="media_play")
    assert again["accepted"] is True
