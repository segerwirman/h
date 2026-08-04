"""WA9-live — call live controls.

Kill switch one-shot: arm(session, proof) → kill() membatalkan session
(cancelled) + menghentikan audio proof + bus `call.killed`; tidak bisa
re-arm. Visible hangup: end session + stop proof, metadata-only. Rollout
rings bertingkat (test → trusted → business → public): ring berikutnya
HANYA aktif dengan bukti accept dari ring sebelumnya; deny-by-default;
ring tak dikenal ditolak. Murni lokal; tanpa SDK/network/file.
"""
from __future__ import annotations

from jarvis.core.bus import BUS

RING_ORDER = ("test", "trusted", "business", "public")


class CallKillSwitch:
    """One-shot kill: batalkan session + hentikan proof + bus signal."""

    def __init__(self) -> None:
        self._state = "idle"
        self._session: object | None = None
        self._proof: object | None = None

    def arm(self, session: object, proof: object) -> bool:
        if self._state != "idle":
            return False
        self._session = session
        self._proof = proof
        self._state = "armed"
        return True

    def kill(self) -> bool:
        if self._state != "armed":
            return False
        session = self._session
        proof = self._proof
        self._state = "killed"              # one-shot, sebelum aksi
        if session is not None and hasattr(session, "cancel"):
            session.cancel()
        if proof is not None and hasattr(proof, "stop"):
            proof.stop()
        session_id = getattr(session, "session_id", lambda: "")() \
            if session is not None else ""
        BUS.publish("call.killed", session_id=session_id)
        return True

    def status(self) -> str:
        return self._state


def visible_hangup(session: object, proof: object) -> dict:
    """Hangup VISIBLE: end session + stop proof; metadata-only; one-shot."""
    session_state = getattr(session, "status", lambda: "idle")()
    if session_state not in ("awaiting", "active", "dialing", "connected",
                             "awaiting_decision"):
        return {"ok": False, "hangup_visible": False}
    if not getattr(session, "end", lambda: False)():
        return {"ok": False, "hangup_visible": False}
    if proof is not None and hasattr(proof, "stop"):
        proof.stop()
    return {
        "ok": True,
        "hangup_visible": True,
        "session_id": getattr(session, "session_id", lambda: "")(),
        "status": getattr(session, "status", lambda: "done")(),
    }


class RolloutRings:
    """Rings bertingkat; ring berikutnya butuh ≥1 accept ring sebelumnya."""

    RING_ORDER = RING_ORDER

    def __init__(self) -> None:
        self._accepts: dict[str, set[str]] = {ring: set() for ring in RING_ORDER}

    def record_accept(self, ring: str, contact: str) -> bool:
        if ring not in RING_ORDER:
            return False
        self._accepts[ring].add(contact)
        return True

    def _ring_ready(self, ring: str) -> bool:
        """Ring pertama bebas; lainnya butuh bukti ring sebelumnya."""
        if ring not in RING_ORDER:
            return False
        index = RING_ORDER.index(ring)
        if index == 0:
            return True
        previous = RING_ORDER[index - 1]
        return len(self._accepts[previous]) >= 1

    def admit_target(self, ring: str) -> bool:
        if ring not in RING_ORDER:
            return False                    # deny-by-default
        return self._ring_ready(ring)


__all__ = ["CallKillSwitch", "visible_hangup", "RolloutRings", "RING_ORDER"]
