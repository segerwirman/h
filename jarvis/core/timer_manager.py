"""WA1-lanjutan — timer manager (multi-timer, pause/resume).

Multi-timer bersamaan: bounded count (MAX_TIMERS), label unik (duplicate
ditolak), rentang durasi 1 detik–7 hari. Pause membekukan remaining;
resume menggeser deadline (anti-drift). Status lazy (deadline monotonic).
`due()` melaporkan label yang selesai — untuk TTS announcement OPSIONAL
via callback `announce` (tidak pernah dipanggil otomatis oleh manager;
tanpa authority baru). Murni lokal, tanpa provider/network/file.
"""
from __future__ import annotations

import time

MAX_DURATION_S = 7 * 86400          # 7 hari
MAX_TIMERS = 8

_FIXED_REASONS = {
    "timer_duplicate_label",
    "timer_limit_reached",
    "timer_unknown_label",
    "timer_duration_rejected",
}


def _now() -> float:
    return time.monotonic()


def admit_duration(value: object) -> dict:
    if isinstance(value, bool) or not isinstance(value, int):
        return {"ok": False, "reason": "timer_duration_rejected"}
    if not 1 <= value <= MAX_DURATION_S:
        return {"ok": False, "reason": "timer_duration_rejected"}
    return {"ok": True, "duration_s": value}


class TimerManager:
    """Multi-timer; label unik; pause/resume anti-drift; due list."""

    def __init__(self, announce: object = None) -> None:
        self._timers: dict[str, dict] = {}
        self._announce = announce       # callable(label) opsional — TTS
        self._announced: set[str] = set()

    def add(self, label: str, duration_s: int) -> bool:
        admitted = admit_duration(duration_s)
        if not admitted.get("ok"):
            return False
        if label in self._timers:
            return False                # duplicate label
        if len(self._timers) >= MAX_TIMERS:
            return False                # limit tercapai
        self._timers[label] = {
            "state": "running",
            "duration_s": admitted["duration_s"],
            "remaining": float(admitted["duration_s"]),
            "deadline": _now() + admitted["duration_s"],
        }
        return True

    def remove(self, label: str) -> bool:
        if label not in self._timers:
            return False
        del self._timers[label]
        return True

    def pause(self, label: str) -> bool:
        timer = self._timers.get(label)
        if timer is None or timer["state"] != "running":
            return False
        timer["remaining"] = max(0.0, timer["deadline"] - _now())
        timer["state"] = "paused"
        return True

    def resume(self, label: str) -> bool:
        timer = self._timers.get(label)
        if timer is None or timer["state"] != "paused":
            return False
        timer["deadline"] = _now() + timer["remaining"]   # geser deadline
        timer["state"] = "running"
        return True

    def _refresh(self, label: str) -> dict:
        """Lazy done: deadline lewat → done (sekali)."""
        timer = self._timers[label]
        if timer["state"] == "running" and _now() >= timer["deadline"]:
            timer["state"] = "done"
            timer["remaining"] = 0.0
        return timer

    def status_list(self) -> list[dict]:
        """Metadata per timer — tanpa konten lain."""
        entries = []
        for label in self._timers:
            timer = self._refresh(label)
            entries.append({
                "label": label,
                "status": timer["state"],
                "remaining_s": int(round(timer["remaining"]))
                if timer["state"] != "running"
                else int(max(0, timer["deadline"] - _now())),
            })
        return entries

    def due(self) -> list[str]:
        """Label timer yang BARU selesai; announce (opsional) sekali per label."""
        finished = []
        for label in list(self._timers):
            timer = self._refresh(label)
            if timer["state"] == "done" and label not in self._announced:
                self._announced.add(label)
                finished.append(label)
        if finished and self._announce is not None:
            for label in finished:
                self._announce(label)
        return finished


__all__ = ["TimerManager", "admit_duration", "MAX_DURATION_S", "MAX_TIMERS",
           "_FIXED_REASONS"]
