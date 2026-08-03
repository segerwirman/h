"""Phase WA1 — native countdown timer core.

Durasi terbatas (bounded finite integer), cancel, selesai tepat waktu
(deadline monotonic — anti-drift), sinyal ringan ke bus, transisi status
jelas: idle → running → done/cancelled. Murni lokal: tanpa remote,
network, atau file write. Clock injectable untuk test deterministik.
"""
from __future__ import annotations

import time

from jarvis.core.bus import BUS

MAX_DURATION_S = 3600


def admit_duration(value: object) -> dict:
    """Admit only a finite bounded integer duration in seconds."""
    if isinstance(value, bool) or not isinstance(value, int):
        return {"ok": False, "reason": "countdown_duration_type_rejected"}
    if not 1 <= value <= MAX_DURATION_S:
        return {"ok": False, "reason": "countdown_duration_range_rejected"}
    return {"ok": True, "duration": value}


def _now() -> float:
    return time.monotonic()


class CountdownTimer:
    """Deadline-based countdown; anti-drift; publishes light bus signals."""

    IDLE = "idle"
    RUNNING = "running"
    DONE = "done"
    CANCELLED = "cancelled"

    def __init__(self) -> None:
        self._state = self.IDLE
        self._duration: int | None = None
        self._deadline: float | None = None
        self._announced = False

    # ── kontrol ──────────────────────────────────────────────────────────────
    def start(self, duration_s: int) -> bool:
        admitted = admit_duration(duration_s)
        if not admitted.get("ok"):
            return False
        self._state = self.RUNNING
        self._duration = admitted["duration"]
        self._deadline = _now() + self._duration
        self._announced = False
        return True

    def cancel(self) -> bool:
        """Running → cancelled (sekali); publish bus signal ringan."""
        if self._state != self.RUNNING:
            return False
        self._state = self.CANCELLED
        BUS.publish("timer.cancelled", duration_s=self._duration)
        return True

    # ── observasi (lazy transition) ──────────────────────────────────────────
    def status(self) -> str:
        if self._state == self.RUNNING and self._deadline is not None \
                and _now() >= self._deadline:
            self._state = self.DONE
            if not self._announced:
                self._announced = True
                BUS.publish("timer.finished", duration_s=self._duration)
        return self._state

    def remaining_s(self) -> int:
        if self._state == self.RUNNING and self._deadline is not None:
            return max(0, int(self._deadline - _now()))
        return 0

    def progress(self) -> float:
        """Fraksi 0..1 untuk orb (1.0 saat selesai)."""
        if self._duration is None or self._duration <= 0:
            return 0.0
        if self.status() == self.DONE:
            return 1.0
        if self._state != self.RUNNING or self._deadline is None:
            return 0.0
        elapsed = max(0.0, self._deadline - _now())
        return max(0.0, min(1.0, 1.0 - elapsed / self._duration))

    def duration_s(self) -> int | None:
        return self._duration


__all__ = ["CountdownTimer", "admit_duration", "MAX_DURATION_S"]
