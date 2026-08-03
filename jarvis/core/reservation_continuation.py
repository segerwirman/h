"""WA7-lanjutan — decision continuation & hard block.

Exact-option permit: readback exact option → local approval → permit
SHORT-LIVED (TTL); setiap perubahan term (price/fees/date/cancellation)
MENGINVALIDASI permit selamanya. Hard block payment boundary:
payment/deposit/transfer/card/CVV/OTP/PIN/password → no-payment, reason
fixed. Simulator membuktikan changed-price invalidation & no-payment
boundary. Offline; tanpa provider/network/file.
"""
from __future__ import annotations

import time

PERMIT_TTL_S = 120
_TERM_FIELDS = ("price", "fees", "date", "cancellation")

_PAYMENT_MARKERS = (
    "transfer", "bayar", "pembayaran", "payment", "deposit", "kartu",
    "cvv", "otp", "pin ", "password", "passphrase", "rekening", "bank",
)


def _now() -> float:
    return time.monotonic()


class ExactOptionPermit:
    """One-shot permit; changed term → invalidated selamanya."""

    def __init__(self, ttl_s: int = PERMIT_TTL_S) -> None:
        self._ttl_s = int(ttl_s)
        self._state = "idle"
        self._option: dict | None = None
        self._approved_at: float | None = None

    def create(self, option: dict) -> bool:
        if self._state != "idle" or not isinstance(option, dict):
            return False
        self._state = "awaiting_approval"
        self._option = {field: option.get(field) for field in _TERM_FIELDS}
        return True

    def approve(self) -> bool:
        if self._state != "awaiting_approval":
            return False
        self._state = "active"
        self._approved_at = _now()
        return True

    def status(self) -> str:
        if self._state == "active" and _now() - (self._approved_at or 0) \
                > self._ttl_s:
            self._state = "expired"
        return self._state

    def matches(self, candidate: dict) -> bool:
        """Exact match semua term; changed term → invalidated selamanya."""
        if self.status() != "active":
            return False
        candidate_terms = {field: candidate.get(field)
                           for field in _TERM_FIELDS}
        if candidate_terms == self._option:
            return True
        self._state = "invalidated"
        return False


class HardBlockGuard:
    """No-payment boundary: teks menyentuh payment/secret → block fixed."""

    def is_blocked(self, text: str) -> bool:
        lowered = (text or "").lower()
        return any(marker in lowered for marker in _PAYMENT_MARKERS)

    def reason(self, text: str) -> str | None:
        if self.is_blocked(text):
            return "reservation_payment_hard_block"
        return None


def simulate_decision_flow(*, option: dict, candidate: dict,
                           customer_turn: str = "") -> dict:
    """Simulator: readback → approval → permit; changed term invalidates;
    customer turn menyentuh payment → hard block (commit dilarang)."""
    permit = ExactOptionPermit()
    permit.create(option)
    permit.approve()

    hard_blocked = bool(customer_turn) and HardBlockGuard().is_blocked(
        customer_turn)
    matches = permit.matches(candidate)
    commit_allowed = (permit.status() == "active" and matches
                      and not hard_blocked)
    return {
        "permit_status": permit.status(),
        "hard_blocked": hard_blocked,
        "commit_allowed": commit_allowed,
    }


__all__ = ["ExactOptionPermit", "HardBlockGuard", "simulate_decision_flow",
           "PERMIT_TTL_S", "_TERM_FIELDS"]
