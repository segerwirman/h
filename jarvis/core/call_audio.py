"""Phase WA3 — bounded two-way audio proof linked to approved call session.

Inbound + outbound audio path via injected capture/playback functions
(fixture-only; tanpa hardware di CI; STT/TTS/voice_listener FROZEN tidak
disentuh). Start hanya untuk session yang SUDAH di-approve lokal (WA2);
session cancel/end menghentikan proof (sinyal stop via session). Durasi
bounded; result metadata-only; bus `call.audio.*` ringan.
"""
from __future__ import annotations

import time
from typing import Callable

from jarvis.core.bus import BUS

MIN_DURATION_S = 1
MAX_DURATION_S = 600


def admit_duration(value: object) -> dict:
    """Admit only a finite bounded integer duration in seconds."""
    if isinstance(value, bool) or not isinstance(value, int):
        return {"ok": False, "reason": "call_audio_duration_type_rejected"}
    if not MIN_DURATION_S <= value <= MAX_DURATION_S:
        return {"ok": False, "reason": "call_audio_duration_range_rejected"}
    return {"ok": True, "duration": value}


def _now() -> float:
    return time.monotonic()


class CallAudioProof:
    """One-shot audio proof: running → done/cancelled; deadline monotonic.

    capture(duration_s) -> int (jumlah sample) dan
    playback(duration_s) -> bool di-inject; tanpa keduanya proof tetap
    berjalan tetapi `audio_exercised` jujur False.
    """

    def __init__(self, *, capture: Callable[[int], int] | None = None,
                 playback: Callable[[int], bool] | None = None) -> None:
        self._capture = capture
        self._playback = playback
        self._state = "idle"
        self._session = None
        self._duration: int | None = None
        self._deadline: float | None = None
        self._announced = False
        self._samples_captured = 0
        self._playback_ok = False

    # ── kontrol ──────────────────────────────────────────────────────────────
    def start(self, session: object, duration_s: int) -> bool:
        """Mulai proof HANYA untuk session yang sudah active (approved)."""
        if self._state != "idle":
            return False
        if session is None or getattr(session, "status", lambda: "idle")() \
                != "active":
            return False
        admitted = admit_duration(duration_s)
        if not admitted.get("ok"):
            return False
        self._state = "running"
        self._session = session
        self._duration = admitted["duration"]
        self._deadline = _now() + self._duration
        if self._capture is not None:
            try:
                self._samples_captured = int(self._capture(self._duration) or 0)
            except Exception:  # noqa: BLE001
                self._samples_captured = 0
        if self._playback is not None:
            try:
                self._playback_ok = bool(self._playback(self._duration))
            except Exception:  # noqa: BLE001
                self._playback_ok = False
        BUS.publish("call.audio.started",
                    session_id=getattr(session, "session_id", lambda: "")())
        return True

    def stop(self) -> bool:
        """Akhiri proof lebih awal (running → done; sekali)."""
        if self._state != "running":
            return False
        self._state = "done"
        self._announce_done()
        return True

    # ── observasi (lazy deadline + sinyal stop via session) ──────────────────
    def status(self) -> str:
        if self._state != "running":
            return self._state
        session_state = getattr(self._session, "status", lambda: "active")()
        if session_state == "cancelled":
            self._state = "cancelled"
        elif session_state in ("done", "expired") \
                or (self._deadline is not None and _now() >= self._deadline):
            self._state = "done"
        if self._state == "done":
            self._announce_done()
        return self._state

    def _announce_done(self) -> None:
        if self._announced:
            return
        self._announced = True
        BUS.publish("call.audio.done",
                    session_id=getattr(self._session, "session_id", lambda: "")())

    def result(self) -> dict:
        """Metadata-only: tanpa audio/path/raw/payload."""
        return {
            "session_id": getattr(self._session, "session_id", lambda: "")(),
            "duration_s": self._duration,
            "status": self.status(),
            "audio_exercised": bool(self._capture is not None
                                    or self._playback is not None),
            "samples_captured": self._samples_captured,
            "playback_ok": self._playback_ok,
        }


__all__ = ["CallAudioProof", "admit_duration", "MIN_DURATION_S",
           "MAX_DURATION_S"]
