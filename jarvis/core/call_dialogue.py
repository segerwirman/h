"""Phase WA4 — bounded autonomous call dialogue.

Turn-based dialogue terikat session call yang sudah di-approve (WA2).
Alternasi ketat local ↔ remote; stop word / user interrupt mengakhiri
dialogue; turn yang mengandung secret/PII ditolak dan TIDAK disimpan;
jumlah turn bounded; summary metadata-only tanpa transcript. Bus events
ringan (session_id + index + source, tanpa teks).
"""
from __future__ import annotations

from jarvis.core.bus import BUS

MAX_TURNS = 20
MAX_TURN_LEN = 500

LOCAL = "local"
REMOTE = "remote"

_STOP_WORDS = (
    "stop", "berhenti", "cukup", "tutup", "selesai", "jangan lanjut",
    "tidak usah", "sudah cukup",
)

_SECRET_MARKERS = (
    "password", "token", "api key", "secret", "kartu", "norek",
    "otp", "pin ", "passphrase", "credential",
)


def admit_turn_text(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, str):
        return {"ok": False, "reason": "dialogue_turn_type_rejected"}
    text = value.strip()
    if not 1 <= len(text) <= MAX_TURN_LEN:
        return {"ok": False, "reason": "dialogue_turn_range_rejected"}
    if any(ord(ch) < 32 for ch in text):
        return {"ok": False, "reason": "dialogue_turn_control_rejected"}
    return {"ok": True, "text": text}


def is_stop_word(text: str) -> bool:
    lowered = text.lower()
    return any(word in lowered for word in _STOP_WORDS)


def _looks_like_secret(text: str) -> bool:
    lowered = text.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return True
    # Kartu/NIK: deret 12-19 digit berturut-turut
    import re
    if re.search(r"\d{12,19}", text):
        return True
    return False


class CallDialogue:
    """One-shot turn dialogue: running → completed/interrupted/ended."""

    def __init__(self) -> None:
        self._state = "idle"
        self._session = None
        self._turns: list[str] = []
        self._ended_announced = False

    # ── kontrol ──────────────────────────────────────────────────────────────
    def start(self, session: object) -> bool:
        if self._state != "idle":
            return False
        if session is None or getattr(session, "status", lambda: "idle")() \
                != "active":
            return False
        self._state = "running"
        self._session = session
        return True

    def submit_turn(self, text: str, source: str) -> bool:
        """Satu turn dari local/remote; tolak turn di luar giliran, teks
        invalid, secret/PII, atau setelah dialogue berakhir."""
        if self.status() != "running":
            return False
        if source not in (LOCAL, REMOTE):
            return False
        admitted = admit_turn_text(text)
        if not admitted.get("ok"):
            return False
        clean = admitted["text"]
        if is_stop_word(clean):
            self._finish("interrupted")
            return True
        if _looks_like_secret(clean):
            return False                       # ditolak, tidak disimpan
        expected = LOCAL if len(self._turns) % 2 == 0 else REMOTE
        if source != expected:
            return False
        if len(self._turns) >= MAX_TURNS:
            return False
        self._turns.append(source)
        BUS.publish("call.dialogue.turn",
                    session_id=getattr(self._session, "session_id", lambda: "")(),
                    turn_index=len(self._turns), source=source)
        if len(self._turns) >= MAX_TURNS:
            self._finish("completed")
        return True

    # ── observasi ────────────────────────────────────────────────────────────
    def status(self) -> str:
        if self._state == "running":
            session_state = getattr(self._session, "status", lambda: "active")()
            if session_state in ("done", "expired"):
                self._finish("ended")
            elif session_state == "cancelled":
                self._finish("interrupted")
        return self._state

    def _finish(self, state: str) -> None:
        if self._state == "running":
            self._state = state
        if not self._ended_announced:
            self._ended_announced = True
            BUS.publish("call.dialogue.ended",
                        session_id=getattr(self._session, "session_id", lambda: "")(),
                        status=state)

    def turn_count(self) -> int:
        return len(self._turns)

    def summary(self) -> dict:
        """Metadata-only: tanpa konten turn/transcript."""
        return {
            "session_id": getattr(self._session, "session_id", lambda: "")(),
            "status": self.status(),
            "turn_count": len(self._turns),
            "sources": list(self._turns),
        }


__all__ = ["CallDialogue", "admit_turn_text", "is_stop_word", "MAX_TURNS",
           "LOCAL", "REMOTE"]
