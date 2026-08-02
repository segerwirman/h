"""Bounded metadata queue for desktop-local approval of remote requests."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Callable

_ALLOWED_ACTIONS = frozenset({
    "focus_mode_enable", "focus_mode_disable",
    "media_play", "media_pause", "media_mute", "media_unmute",
    "media_volume_up", "media_volume_down",
})


@dataclass(frozen=True)
class RemoteProposal:
    id: str
    action: str
    actor_id: str
    session_id: str
    status: str
    created_at: float

    def safe_dict(self) -> dict:
        return {"id": self.id, "action": self.action, "status": self.status}


class RemoteProposalQueue:
    def __init__(self, *, ttl_s: float = 60.0, now: Callable[[], float] = time.monotonic) -> None:
        self._ttl_s = max(1.0, float(ttl_s))
        self._now = now
        self._items: dict[str, RemoteProposal] = {}

    def _expire(self) -> None:
        current = self._now()
        for rid, item in tuple(self._items.items()):
            if item.status == "pending_local_approval" and current - item.created_at >= self._ttl_s:
                self._items[rid] = RemoteProposal(item.id, item.action, item.actor_id, item.session_id, "expired", item.created_at)

    def request(self, *, actor_id: str, session_id: str, action: str, paired: bool = True) -> dict:
        if not paired:
            return {"accepted": False, "reason": "remote_proposal_actor_unpaired"}
        if action not in _ALLOWED_ACTIONS:
            return {"accepted": False, "reason": "remote_proposal_action_rejected"}
        item = RemoteProposal(uuid.uuid4().hex[:16], action, str(actor_id), str(session_id), "pending_local_approval", self._now())
        self._items[item.id] = item
        return {"accepted": True, "proposal_id": item.id, "action": item.action}

    def get(self, proposal_id: str, *, actor_id: str, session_id: str) -> RemoteProposal | None:
        self._expire()
        item = self._items.get(str(proposal_id))
        if item is None or item.actor_id != str(actor_id) or item.session_id != str(session_id):
            return None
        return item

    def cancel_local(self, proposal_id: str, *, actor_id: str, session_id: str) -> dict:
        self._expire()
        item = self._bound_pending(proposal_id, actor_id, session_id)
        if item is None:
            return {"cancelled": False, "reason": self._reason(proposal_id)}
        self._items[item.id] = RemoteProposal(item.id, item.action, item.actor_id, item.session_id, "cancelled", item.created_at)
        return {"cancelled": True}

    def approve_local(self, proposal_id: str, *, actor_id: str, session_id: str, executor: Callable[[str], bool]) -> dict:
        self._expire()
        item = self._bound_pending(proposal_id, actor_id, session_id)
        if item is None:
            return {"executed": False, "reason": self._reason(proposal_id, actor_id, session_id)}
        self._items[item.id] = RemoteProposal(
            item.id, item.action, item.actor_id, item.session_id, "executing", item.created_at,
        )
        try:
            done = bool(executor(item.action))
        except Exception:
            done = False
        status = "approved" if done else "failed"
        self._items[item.id] = RemoteProposal(item.id, item.action, item.actor_id, item.session_id, status, item.created_at)
        return {"executed": True, "status": "approved"} if done else {"executed": False, "reason": "remote_proposal_execution_failed"}

    def _bound_pending(self, proposal_id: str, actor_id: str, session_id: str) -> RemoteProposal | None:
        item = self._items.get(str(proposal_id))
        if item is None or item.status != "pending_local_approval":
            return None
        if item.actor_id != str(actor_id) or item.session_id != str(session_id):
            return None
        return item

    def _reason(self, proposal_id: str, actor_id: str = "", session_id: str = "") -> str:
        item = self._items.get(str(proposal_id))
        if item is not None and item.status == "expired":
            return "remote_proposal_expired"
        if item is not None and actor_id and (item.actor_id != str(actor_id) or item.session_id != str(session_id)):
            return "remote_proposal_context_stale"
        return "remote_proposal_not_pending"


_QUEUE: RemoteProposalQueue | None = None


def get_queue() -> RemoteProposalQueue:
    """Process-local queue shared by remote ingress and desktop-local approval."""
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = RemoteProposalQueue()
    return _QUEUE


__all__ = ["RemoteProposal", "RemoteProposalQueue", "get_queue"]
