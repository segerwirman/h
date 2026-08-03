"""Phase WA6 — post-call calendar proposal.

Proposal one-shot dengan field allowlist ketat (title, start_ts,
duration_min). Conflict check mencegah double-booking; create kalender
BUKAN otoritas modul ini — hanya local approval yang menandai "siap
create" via write path terpisah di fase live. Tanpa import provider,
network, atau file write. Metadata result only.
"""
from __future__ import annotations

import time

MIN_DURATION_MIN = 5
MAX_DURATION_MIN = 1440
MAX_TITLE_LEN = 120
_ALLOWED_FIELDS = ("title", "start_ts", "duration_min")


def admit_title(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, str):
        return {"ok": False, "reason": "cal_title_type_rejected"}
    text = value.strip()
    if not 1 <= len(text) <= MAX_TITLE_LEN:
        return {"ok": False, "reason": "cal_title_range_rejected"}
    if any(ord(ch) < 32 for ch in text):
        return {"ok": False, "reason": "cal_title_control_rejected"}
    return {"ok": True, "title": text}


def admit_duration(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, int):
        return {"ok": False, "reason": "cal_duration_type_rejected"}
    if not MIN_DURATION_MIN <= value <= MAX_DURATION_MIN:
        return {"ok": False, "reason": "cal_duration_range_rejected"}
    return {"ok": True, "duration_min": value}


def admit_start(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, int):
        return {"ok": False, "reason": "cal_start_type_rejected"}
    if value <= _now():
        return {"ok": False, "reason": "cal_start_past_rejected"}
    return {"ok": True, "start_ts": value}


def _now() -> int:
    return int(time.time())


class CalendarProposal:
    """One-shot proposal: draft → approved/rejected. Tanpa create otomatis."""

    def __init__(self) -> None:
        self._state = "idle"
        self._title: str | None = None
        self._start_ts: int | None = None
        self._duration_min: int | None = None

    def create(self, *, title: str, start_ts: int, duration_min: int,
               **extra: object) -> bool:
        if self._state != "idle":
            return False
        if extra:
            return False                       # allowlist ketat
        admitted = (admit_title(title), admit_start(start_ts),
                    admit_duration(duration_min))
        if not all(item.get("ok") for item in admitted):
            return False
        self._state = "draft"
        self._title = admitted[0]["title"]
        self._start_ts = admitted[1]["start_ts"]
        self._duration_min = admitted[2]["duration_min"]
        return True

    def has_conflict(self, existing: list[tuple[int, int]]) -> bool:
        """Overlap dengan event existing (start, end) → double-booking."""
        if self._state not in ("draft", "approved"):
            return False
        start = int(self._start_ts or 0)
        end = start + int(self._duration_min or 0) * 60
        for other_start, other_end in existing:
            if start < int(other_end) and int(other_start) < end:
                return True
        return False

    def approve(self) -> bool:
        """Local approval: draft → approved (sekali; siap create eksternal)."""
        if self._state != "draft":
            return False
        self._state = "approved"
        return True

    def reject(self) -> bool:
        """Local reject: draft → rejected (sekali)."""
        if self._state != "draft":
            return False
        self._state = "rejected"
        return True

    def status(self) -> str:
        return self._state

    def result(self) -> dict:
        """Metadata-only (field allowlist + status)."""
        return {
            "title": self._title,
            "start_ts": self._start_ts,
            "duration_min": self._duration_min,
            "status": self._state,
        }


__all__ = ["CalendarProposal", "admit_title", "admit_duration", "admit_start",
           "MIN_DURATION_MIN", "MAX_DURATION_MIN", "MAX_TITLE_LEN"]
