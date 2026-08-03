"""Phase WA7 — reservation commitment gate.

Reservasi = komitmen → wajib gate ekstra sebelum "ready":
1) local approval eksplisit,
2) fixed disclosure labels (label asing/kosong ditolak),
3) cancellation window bounded (1..365 hari).

Setiap kegagalan gate = NO-OP dengan reason code FIXED; commitment hanya
dicatat setelah green light, sebagai metadata status "ready" — gate TIDAK
mengeksekusi reservasi apa pun (tanpa auto-commit, tanpa write eksternal).
"""
from __future__ import annotations

_FIXED_REASONS = {
    "reservation_approval_missing",
    "reservation_disclosure_missing",
    "reservation_cancellation_window_missing",
    "reservation_unknown_label",
}

_KNOWN_LABELS = ("commitment", "cancellation_policy", "no_refund",
                 "subject_to_availability")

MIN_CANCEL_DAYS = 1
MAX_CANCEL_DAYS = 365


class ReservationCommitmentGate:
    """Pure gate: evaluate → ok/reason; commitment metadata after green."""

    def __init__(self) -> None:
        self._commitments: list[dict] = []

    def evaluate(self, *, approved: bool, labels: list[str],
                 cancel_within_days: int) -> dict:
        if not approved:
            return {"ok": False, "reason": "reservation_approval_missing"}
        if not isinstance(labels, (list, tuple)) or not labels:
            return {"ok": False, "reason": "reservation_disclosure_missing"}
        for label in labels:
            if label not in _KNOWN_LABELS:
                return {"ok": False, "reason": "reservation_unknown_label"}
        if (isinstance(cancel_within_days, bool)
                or not isinstance(cancel_within_days, int)
                or not MIN_CANCEL_DAYS <= cancel_within_days <= MAX_CANCEL_DAYS):
            return {"ok": False,
                    "reason": "reservation_cancellation_window_missing"}
        self._commitments.append({
            "status": "ready",
            "labels": list(labels),
            "cancel_within_days": cancel_within_days,
        })
        return {"ok": True, "reason": None}

    def ready(self) -> bool:
        return bool(self._commitments)

    def commitments(self) -> list[dict]:
        return [dict(entry) for entry in self._commitments]

    def snapshot(self) -> tuple:
        return (len(self._commitments), tuple(self._commitments))


__all__ = ["ReservationCommitmentGate", "_FIXED_REASONS", "_KNOWN_LABELS",
           "MIN_CANCEL_DAYS", "MAX_CANCEL_DAYS"]
