"""Phase WA8 — customer-service case manager.

Typed cases (fixed set), field allowlist, disclosure policy per case type,
stop/escalation rules pada secret/payment. TIDAK ada free-form mission:
case_type hanya dari set tetap; reference non-secret; disclose hanya field
dalam policy; escalation dengan reason fixed.
"""
from __future__ import annotations

import re

_CASE_TYPES = ("service_hours", "appointment", "order_status")
_MAX_NOTE_LEN = 300
_MAX_REFERENCE_LEN = 64

_DISCLOSURE_POLICY = {
    "service_hours": ("hours",),
    "appointment": ("appointment_availability",),
    "order_status": ("order_status_update",),
}

_SECRET_MARKERS = (
    "password", "token", "api key", "secret", "kartu", "norek",
    "otp", "pin ", "passphrase", "credential", "payment", "bayar",
    "transfer", "cvv",
)


def admit_reference(value: object) -> dict:
    if value is None:
        return {"ok": True, "reference": None}
    if isinstance(value, bool) or not isinstance(value, str):
        return {"ok": False, "reason": "service_case_reference_type_rejected"}
    text = value.strip()
    if not 1 <= len(text) <= _MAX_REFERENCE_LEN:
        return {"ok": False, "reason": "service_case_reference_range_rejected"}
    lowered = text.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS) \
            or re.search(r"\d{12,19}", text):
        return {"ok": False, "reason": "service_case_reference_secret_rejected"}
    return {"ok": True, "reference": text}


def admit_note(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, str):
        return {"ok": False, "reason": "service_case_note_type_rejected"}
    text = value.strip()
    if not 1 <= len(text) <= _MAX_NOTE_LEN:
        return {"ok": False, "reason": "service_case_note_range_rejected"}
    lowered = text.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return {"ok": False, "reason": "service_case_note_secret_rejected"}
    return {"ok": True, "note": text}


class ServiceCase:
    """One-shot typed case: open → escalated/closed. Tanpa free-form."""

    def __init__(self) -> None:
        self._state = "idle"
        self._case_type: str | None = None
        self._reference: str | None = None
        self._note: str | None = None
        self._reason: str | None = None

    def open(self, case_type: str, reference: object) -> bool:
        if self._state != "idle":
            return False
        if case_type not in _CASE_TYPES:
            return False
        admitted = admit_reference(reference)
        if not admitted.get("ok"):
            return False
        if case_type == "order_status" and admitted["reference"] is None:
            return False                    # order_status wajib reference
        self._state = "open"
        self._case_type = case_type
        self._reference = admitted["reference"]
        return True

    def set_note(self, note: str) -> bool:
        if self._state != "open":
            return False
        admitted = admit_note(note)
        if not admitted.get("ok"):
            return False
        self._note = admitted["note"]
        return True

    def disclose(self, field: str) -> bool:
        """Hanya field dalam disclosure policy type ini — selain itu tidak."""
        if self._state != "open":
            return False
        policy = _DISCLOSURE_POLICY.get(self._case_type or "", ())
        return field in policy

    def escalate_if_needed(self, text: str) -> bool:
        """Sentuhan secret/payment → escalate dengan reason fixed + stop."""
        if self._state != "open":
            return False
        lowered = (text or "").lower()
        if any(marker in lowered for marker in _SECRET_MARKERS) \
                or re.search(r"\d{12,19}", text or ""):
            self._state = "escalated"
            self._reason = "service_case_secret_touch"
            return True
        return False

    def reason(self) -> str | None:
        return self._reason

    def close(self) -> bool:
        if self._state != "open":
            return False
        self._state = "closed"
        return True

    def status(self) -> str:
        return self._state

    def result(self) -> dict:
        """Metadata-only: tanpa konten secret/payment/raw."""
        return {
            "case_type": self._case_type,
            "reference": self._reference,
            "status": self._state,
            "reason": self._reason,
        }


__all__ = ["ServiceCase", "admit_reference", "admit_note", "_CASE_TYPES",
           "_DISCLOSURE_POLICY"]
