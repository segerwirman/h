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
MAX_DISCLOSURES = 8
MAX_DISCLOSURE_LEN = 40
_KNOWN_CONSTRAINTS = ("max_duration_min", "max_turns")


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


def admit_constraints(value: object) -> dict:
    """Constraints hanya dari known keys, nilai int bounded."""
    if value is None:
        return {"ok": True, "constraints": {}}
    if not isinstance(value, dict):
        return {"ok": False, "reason": "call_constraints_type_rejected"}
    admitted: dict = {}
    for key, item in value.items():
        if key not in _KNOWN_CONSTRAINTS:
            return {"ok": False, "reason": "call_constraints_unknown_key"}
        if isinstance(item, bool) or not isinstance(item, int) \
                or item <= 0 or item > 600:
            return {"ok": False, "reason": "call_constraints_range_rejected"}
        admitted[key] = item
    return {"ok": True, "constraints": admitted}


def admit_disclosures(value: object) -> dict:
    """Allowed disclosures: tuple/list str, bounded count + length."""
    if value is None:
        return {"ok": True, "disclosures": ()}
    if not isinstance(value, (tuple, list)):
        return {"ok": False, "reason": "call_disclosures_type_rejected"}
    if not 0 < len(value) <= MAX_DISCLOSURES:
        return {"ok": False, "reason": "call_disclosures_range_rejected"}
    disclosures: list[str] = []
    for item in value:
        if not isinstance(item, str) \
                or not 1 <= len(item) <= MAX_DISCLOSURE_LEN:
            return {"ok": False, "reason": "call_disclosure_item_rejected"}
        disclosures.append(item)
    return {"ok": True, "disclosures": tuple(disclosures)}


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
        self._constraints: dict = {}
        self._allowed_disclosures: tuple[str, ...] = ()

    # ── lifecycle (lokal) ────────────────────────────────────────────────────
    def start(self, contact: str, objective: str, ttl_s: int,
              constraints: object = None,
              allowed_disclosures: object = None) -> bool:
        if self._state != "idle":
            return False
        admitted_c = admit_contact(contact)
        admitted_o = admit_objective(objective)
        admitted_t = admit_ttl(ttl_s)
        admitted_k = admit_constraints(constraints)
        admitted_d = admit_disclosures(allowed_disclosures)
        if not (admitted_c.get("ok") and admitted_o.get("ok")
                and admitted_t.get("ok") and admitted_k.get("ok")
                and admitted_d.get("ok")):
            return False
        self._state = "awaiting"
        self._contact = admitted_c["contact"]
        self._objective = admitted_o["objective"]
        self._ttl_s = admitted_t["ttl_s"]
        self._deadline = _now() + self._ttl_s
        self._constraints = admitted_k["constraints"]
        self._allowed_disclosures = admitted_d["disclosures"]
        BUS.publish("call.proposed", session_id=self._session_id)
        return True

    def propose(self, proposal: RemoteCallProposal) -> bool:
        """Remote mengusulkan enum — TIDAK mengubah state (bukan approval)."""
        if self._state not in ("awaiting", "active", "dialing", "connected",
                               "awaiting_decision"):
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

    # ── states lanjutan (WA2-lanjutan) ───────────────────────────────────────
    def dial(self) -> bool:
        """Lokal: active → dialing."""
        if self._state != "active":
            return False
        self._state = "dialing"
        BUS.publish("call.dialing", session_id=self._session_id)
        return True

    def connect(self) -> bool:
        """Lokal: dialing → connected."""
        if self._state != "dialing":
            return False
        self._state = "connected"
        BUS.publish("call.connected", session_id=self._session_id)
        return True

    def await_decision(self) -> bool:
        """Lokal: connected → awaiting_decision."""
        if self._state != "connected":
            return False
        self._state = "awaiting_decision"
        BUS.publish("call.awaiting_decision", session_id=self._session_id)
        return True

    def fail(self) -> bool:
        """Lokal: dialing/connected → failed."""
        if self._state not in ("dialing", "connected"):
            return False
        self._state = "failed"
        BUS.publish("call.failed", session_id=self._session_id)
        return True

    def end(self) -> bool:
        """Lokal: awaiting/active/dialing/connected/awaiting_decision → done."""
        if self._state not in ("awaiting", "active", "dialing", "connected",
                               "awaiting_decision"):
            return False
        self._state = "done"
        BUS.publish("call.done", session_id=self._session_id)
        return True

    def cancel(self) -> bool:
        """Lokal: awaiting/active/dialing/connected/awaiting_decision → cancelled."""
        if self._state not in ("awaiting", "active", "dialing", "connected",
                               "awaiting_decision"):
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

    def constraints(self) -> dict:
        return dict(self._constraints)

    def disclosure_allowed(self, field: str) -> bool:
        return field in self._allowed_disclosures

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
            "constraints": dict(self._constraints),
            "allowed_disclosures": list(self._allowed_disclosures),
        }


__all__ = ["CallSession", "RemoteCallProposal",
           "admit_contact", "admit_objective", "admit_ttl",
           "admit_constraints", "admit_disclosures",
           "MIN_TTL_S", "MAX_TTL_S"]
