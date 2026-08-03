"""WA6-lanjutan — calendar review lanjutan.

Typed outcome mappings (hotel stay, flight departure/arrival, service
appointment, callback); timezone known-set; status pending →
tentative/awaiting_second → approved/rejected; terms/price/reference/
reminder bounded; SECOND local approval (first → awaiting_second →
second → approved). Write path ke provider TETAP fase live — modul ini
TIDAK pernah membuat event (kontrak statis: tanpa provider/network).
Murni lokal.
"""
from __future__ import annotations

import time
import uuid
from enum import Enum

MAX_TITLE_LEN = 120
MAX_TERMS_LEN = 200
MAX_REFERENCE_LEN = 40
MAX_REMINDER_MIN = 7 * 24 * 60          # 7 hari
MIN_START_TS = 1_800_000_000            # masa depan relatif nyata (2027+)

_KNOWN_TIMEZONES = (
    "Asia/Jakarta", "Asia/Makassar", "Asia/Jayapura", "Asia/Singapore",
    "Asia/Tokyo", "UTC",
)

_SECRET_MARKERS = (
    "password", "token", "otp", "pin", "cvv", "transfer", "rekening",
    "kartu kredit", "passphrase",
)

_OUTCOME_KEYWORDS = {
    "hotel": "HOTEL_STAY",
    "penginapan": "HOTEL_STAY",
    "keberangkatan": "FLIGHT_DEPARTURE",
    "berangkat": "FLIGHT_DEPARTURE",
    "departure": "FLIGHT_DEPARTURE",
    "kedatangan": "FLIGHT_ARRIVAL",
    "arrival": "FLIGHT_ARRIVAL",
    "janji temu": "SERVICE_APPOINTMENT",
    "appointment": "SERVICE_APPOINTMENT",
    "telepon balik": "CALLBACK",
    "callback": "CALLBACK",
}


class OutcomeType(str, Enum):
    """Jenis outcome kalender yang dikenali (fixed set)."""

    HOTEL_STAY = "HOTEL_STAY"
    FLIGHT_DEPARTURE = "FLIGHT_DEPARTURE"
    FLIGHT_ARRIVAL = "FLIGHT_ARRIVAL"
    SERVICE_APPOINTMENT = "SERVICE_APPOINTMENT"
    CALLBACK = "CALLBACK"


def map_outcome(text: str) -> OutcomeType | None:
    """Deteksi outcome dari teks call — tanpa keyword → None."""
    lowered = (text or "").lower()
    for keyword, outcome in _OUTCOME_KEYWORDS.items():
        if keyword in lowered:
            return OutcomeType(outcome)
    return None


def admit_timezone(tz: str) -> dict:
    if not isinstance(tz, str) or tz not in _KNOWN_TIMEZONES:
        return {"ok": False, "reason": "calendar_timezone_unknown"}
    return {"ok": True, "timezone": tz}


def _admit_price(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, int) \
            or not 0 <= value <= 1_000_000_000:
        return {"ok": False, "reason": "calendar_price_rejected"}
    return {"ok": True, "price": value}


def _admit_string(value: object, max_len: int) -> dict:
    if not isinstance(value, str) or not 1 <= len(value) <= max_len:
        return {"ok": False, "reason": "calendar_field_rejected"}
    lowered = value.lower()
    if any(marker in lowered for marker in _SECRET_MARKERS):
        return {"ok": False, "reason": "calendar_secret_rejected"}
    return {"ok": True, "value": value}


def _admit_reminder(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, int) \
            or not 1 <= value <= MAX_REMINDER_MIN:
        return {"ok": False, "reason": "calendar_reminder_rejected"}
    return {"ok": True, "reminder_min": value}


def _now() -> float:
    return time.time()


class CalendarReview:
    """Review proposal kalender — second local approval; tanpa provider."""

    def __init__(self) -> None:
        self._proposals: dict[str, dict] = {}

    def propose(self, title: str, start_ts: int, duration_min: int,
                outcome: object = None, timezone: object = None,
                terms: object = None, price: object = None,
                reference: object = None,
                reminder_min: object = None) -> str | None:
        """Proposal kalender review — validasi bounded; tanpa create."""
        admitted_t = _admit_string(title, MAX_TITLE_LEN)
        if not admitted_t.get("ok") or start_ts <= _now():
            return None
        if isinstance(duration_min, bool) or not isinstance(duration_min, int) \
                or not 1 <= duration_min <= 600:
            return None
        if outcome is not None:
            if outcome not in OutcomeType.__members__:
                return None
        if timezone is not None and not admit_timezone(timezone).get("ok"):
            return None
        if terms is not None and not _admit_string(terms, MAX_TERMS_LEN).get("ok"):
            return None
        if price is not None and not _admit_price(price).get("ok"):
            return None
        if reference is not None:
            if not _admit_string(reference, MAX_REFERENCE_LEN).get("ok"):
                return None
        if reminder_min is not None \
                and not _admit_reminder(reminder_min).get("ok"):
            return None
        pid = uuid.uuid4().hex
        self._proposals[pid] = {
            "title": admitted_t["value"],
            "start_ts": int(start_ts),
            "duration_min": int(duration_min),
            "outcome": outcome,
            "timezone": timezone,
            "terms": terms,
            "price": price,
            "reference": reference,
            "reminder_min": reminder_min,
            "status": "pending",
        }
        return pid

    # ── alur approval (lokal; second approval) ──────────────────────────────
    def first_approve(self, proposal_id: str) -> bool:
        proposal = self._proposals.get(proposal_id)
        if proposal is None or proposal["status"] != "pending":
            return False
        proposal["status"] = "awaiting_second"
        return True

    def second_approve(self, proposal_id: str) -> bool:
        proposal = self._proposals.get(proposal_id)
        if proposal is None or proposal["status"] != "awaiting_second":
            return False
        proposal["status"] = "approved"     # siap live write (fase live)
        return True

    def mark_tentative(self, proposal_id: str) -> bool:
        proposal = self._proposals.get(proposal_id)
        if proposal is None or proposal["status"] != "pending":
            return False
        proposal["status"] = "tentative"
        return True

    def reject(self, proposal_id: str) -> bool:
        proposal = self._proposals.get(proposal_id)
        if proposal is None or proposal["status"] in ("approved", "rejected"):
            return False
        proposal["status"] = "rejected"
        return True

    def status(self, proposal_id: str) -> str | None:
        proposal = self._proposals.get(proposal_id)
        return proposal["status"] if proposal else None

    def review(self, proposal_id: str) -> dict:
        """Metadata review — tanpa nilai secret (sudah difilter di propose)."""
        proposal = self._proposals.get(proposal_id)
        if proposal is None:
            return {"ok": False}
        return {
            "ok": True,
            "status": proposal["status"],
            "outcome": proposal["outcome"],
            "timezone": proposal["timezone"],
            "price": proposal["price"],
            "reference": proposal["reference"],
            "reminder_min": proposal["reminder_min"],
            "start_ts": proposal["start_ts"],
            "duration_min": proposal["duration_min"],
        }


__all__ = ["CalendarReview", "OutcomeType", "map_outcome", "admit_timezone",
           "_KNOWN_TIMEZONES"]
