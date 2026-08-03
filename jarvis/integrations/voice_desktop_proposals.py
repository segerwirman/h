"""Phase 18A: voice ingress creates narrow, local-approval proposals only."""
from __future__ import annotations

import re
import time
import uuid
from dataclasses import dataclass
from typing import Callable

_DEFAULT_TTL_S = 60.0
_ACTIONS = {
    "aktifkan mode fokus": "focus_mode_enable",
    "nyalakan mode fokus": "focus_mode_enable",
    "nonaktifkan mode fokus": "focus_mode_disable",
    "matikan mode fokus": "focus_mode_disable",
}


@dataclass(frozen=True)
class VoiceDesktopProposal:
    id: str
    action: str
    status: str
    created_at: float

    def safe_dict(self) -> dict:
        return {"id": self.id, "action": self.action, "status": self.status}


class VoiceDesktopProposalQueue:
    """Short-lived metadata queue; voice cannot execute or approve itself."""

    def __init__(self, *, ttl_s: float = _DEFAULT_TTL_S, now: Callable[[], float] = time.monotonic):
        self._ttl_s = max(1.0, float(ttl_s))
        self._now = now
        self._items: dict[str, VoiceDesktopProposal] = {}

    def _expire(self) -> None:
        current = self._now()
        for proposal_id, proposal in tuple(self._items.items()):
            if proposal.status == "pending_local_approval" and current - proposal.created_at >= self._ttl_s:
                self._items[proposal_id] = VoiceDesktopProposal(
                    proposal.id, proposal.action, "expired", proposal.created_at)

    def request_from_voice(self, transcript: str, *, final: bool) -> dict:
        if not final:
            return {"accepted": False, "reason": "voice_transcript_not_final"}
        text = " ".join(str(transcript or "").casefold().split())
        if not text:
            return {"accepted": False, "reason": "voice_proposal_ambiguous"}
        action = _ACTIONS.get(text)
        if action is None:
            if re.search(r"\b(itu|ini|ubah)\b", text):
                return {"accepted": False, "reason": "voice_proposal_ambiguous"}
            return {"accepted": False, "reason": "voice_proposal_unsupported"}
        proposal = VoiceDesktopProposal(uuid.uuid4().hex[:16], action, "pending_local_approval", self._now())
        self._items[proposal.id] = proposal
        return {"accepted": True, "proposal_id": proposal.id, "action": action}

    def get(self, proposal_id: str) -> VoiceDesktopProposal | None:
        self._expire()
        return self._items.get(str(proposal_id))

    def approve_local(self, proposal_id: str, *, executor: Callable[[str], bool]) -> dict:
        self._expire()
        proposal = self._items.get(str(proposal_id))
        if proposal is None or proposal.status != "pending_local_approval":
            reason = "voice_proposal_expired" if proposal is not None and proposal.status == "expired" else "voice_proposal_not_pending"
            return {"executed": False, "reason": reason}
        try:
            executed = bool(executor(proposal.action))
        except Exception:
            executed = False
        self._items[proposal.id] = VoiceDesktopProposal(proposal.id, proposal.action, "approved" if executed else "failed", proposal.created_at)
        return ({"executed": True, "status": "approved"} if executed
                else {"executed": False, "reason": "voice_proposal_execution_failed"})


_QUEUE: VoiceDesktopProposalQueue | None = None


def get_queue() -> VoiceDesktopProposalQueue:
    """Process-local queue shared by voice ingress and desktop-local approval."""
    global _QUEUE
    if _QUEUE is None:
        _QUEUE = VoiceDesktopProposalQueue()
    return _QUEUE


__all__ = ["VoiceDesktopProposal", "VoiceDesktopProposalQueue", "get_queue"]
