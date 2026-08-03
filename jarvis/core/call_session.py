"""Phase WA2 — bounded call session state machine + local approval.

Remote hanya dapat mengirim proposal enum (bukan eksekusi); semua transisi
state hanya via local approval. Session one-shot dengan TTL deadline
monotonic; result metadata-only (tanpa transcript/audio/path/raw). Murni
lokal; sinyal bus ringan (session_id + status saja).
"""
from __future__ import annotations

import time
import uuid
from enum import Enum

from jarvis.core.bus import BUS

MIN_TTL_S = 30
MAX_TTL_S = 3600
MAX_CONTACT_LEN = 120
MAX_OBJECTIVE_LEN = 500


class RemoteCallProposal(str, Enum):
    """Proposal dari remote — enum saja; tidak pernah mengeksekusi apa pun."""

    ACCEPT = "ACCEPT"
    DECLINE = "DECLINE"
    END = "END"
    EXTEND = "EXTEND"


def admit_contact(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, str):
        return {"ok": False, "reason": "call_contact_type_rejected"}
    text = value.strip()
    if not 1 <= len(text) <= MAX_CONTACT_LEN:
        return {"ok": False, "reason": "call_contact_range_rejected"}
    if any(ord(ch) < 32 for ch in text):
        return {"ok": False, "reason": "call_contact_control_rejected"}
    return {"ok": True, "contact": text}


def admit_objective(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, str):
        return {"ok": False, "reason": "call_objective_type_rejected"}
    text = value.strip()
    if not 1 <= len(text) <= MAX_OBJECTIVE_LEN:
        return {"ok": False, "reason": "call_objective_range_rejected"}
    return {"ok": True, "objective": text}


def admit_ttl(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, int):
        return {"ok": False, "reason": "call_ttl_type_rejected"}
    if not MIN_TTL_S <= value <= MAX_TTL_S:
        return {"ok": False, "reason": "call_ttl_range_rejected"}
    return {"ok": True, "ttl_s": value}


def _now() -> float:
    return time.monotonic()


class CallSession:
    """Bounded, one-shot call session: idle → awaiting → active → done,
    atau awaiting → cancelled/expired. Propose (enum remote) tidak
    mengubah state; approve/end/cancel hanya lokal."""

    def __init__(self) -> None:
        self._state = "idle"
        self._session_id = uuid.uuid4().hex
        self._contact: str | None = None
        self._objective: str | None = None
        self._ttl_s: int | None = None
        self._deadline: float | None = None
        self._announced = False
        self._proposals: list[str] = []

    # ── lifecycle (lokal) ────────────────────────────────────────────────────
    def start(self, contact: str, objective: str, ttl_s: int) -> bool:
        if self._state != "idle":
            return False
        admitted_c = admit_contact(contact)
        admitted_o = admit_objective(objective)
        admitted_t = admit_ttl(ttl_s)
        if not (admitted_c.get("ok") and admitted_o.get("ok")
                and admitted_t.get("ok")):
            return False
        self._state = "awaiting"
        self._contact = admitted_c["contact"]
        self._objective = admitted_o["objective"]
        self._ttl_s = admitted_t["ttl_s"]
        self._deadline = _now() + self._ttl_s
        BUS.publish("call.proposed", session_id=self._session_id)
        return True

    def propose(self, proposal: RemoteCallProposal) -> bool:
        """Remote mengusulkan enum — TIDAK mengubah state (bukan approval)."""
        if self._state not in ("awaiting", "active"):
            return False
        if not isinstance(proposal, RemoteCallProposal):
            return False
        self._proposals.append(proposal.value)
        return True

    def approve(self) -> bool:
        """Approval LOKAL: awaiting → active (sekali; one-shot)."""
        if self._state != "awaiting":
            return False
        self._state = "active"
        BUS.publish("call.approved", session_id=self._session_id)
        return True

    def end(self) -> bool:
        """Lokal: active (atau awaiting) → done (sekali)."""
        if self._state not in ("awaiting", "active"):
            return False
        self._state = "done"
        BUS.publish("call.done", session_id=self._session_id)
        return True

    def cancel(self) -> bool:
        """Lokal: awaiting/active → cancelled (idempotent)."""
        if self._state not in ("awaiting", "active"):
            return False
        self._state = "cancelled"
        BUS.publish("call.cancelled", session_id=self._session_id)
        return True

    # ── observasi (lazy TTL) ─────────────────────────────────────────────────
    def status(self) -> str:
        if self._state == "awaiting" and self._deadline is not None \
                and _now() >= self._deadline:
            self._state = "expired"
            if not self._announced:
                self._announced = True
                BUS.publish("call.expired", session_id=self._session_id)
        return self._state

    def session_id(self) -> str:
        return self._session_id

    def ttl_s(self) -> int | None:
        return self._ttl_s

    def proposals(self) -> list[str]:
        return list(self._proposals)

    def result(self) -> dict:
        """Metadata-only: tanpa transcript/audio/path/raw."""
        return {
            "session_id": self._session_id,
            "contact": self._contact,
            "objective": self._objective,
            "ttl_s": self._ttl_s,
            "status": self.status(),
        }


__all__ = ["CallSession", "RemoteCallProposal",
           "admit_contact", "admit_objective", "admit_ttl",
           "MIN_TTL_S", "MAX_TTL_S"]
