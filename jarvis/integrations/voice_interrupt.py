"""Typed microphone interrupt events bound to local playback evidence."""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from jarvis.core import config
from jarvis.integrations import voice_playback_level

_CANDIDATE_MAX_AGE_S = 1.5
_POST_DRAIN_GRACE_S = 0.45


@dataclass(frozen=True)
class VoiceInterruptEvent:
    detected_at: float
    source: str
    capture_generation: int
    playback_generation: int
    playback_epoch: int
    playback_level: float
    rms: float
    threshold: float
    noise_floor: float

    @property
    def token(self) -> str:
        micros = int(max(0.0, self.detected_at) * 1_000_000)
        return (
            f"{self.source}:{self.capture_generation}:"
            f"{self.playback_generation}:{self.playback_epoch}:{micros}"
        )


def _positive_float(value: float, default: float) -> float:
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return default


def build_microphone_event(
    win: Any,
    verdict: Any,
    *,
    detected_at: float | None = None,
) -> tuple[VoiceInterruptEvent | None, str]:
    """Capture one immutable candidate only while local playback is active."""
    now = time.monotonic() if detected_at is None else float(detected_at)
    playback = voice_playback_level.snapshot(now=now)
    if not voice_playback_level.is_installed():
        return None, "voice_interrupt_playback_unmeasured"
    if not playback.active:
        if playback.drained_at and now - playback.drained_at <= _positive_float(
            config.get("voice.barge_in.post_drain_grace_s", _POST_DRAIN_GRACE_S),
            _POST_DRAIN_GRACE_S,
        ):
            return None, "voice_interrupt_post_drain"
        return None, "voice_interrupt_playback_inactive"
    return VoiceInterruptEvent(
        detected_at=now,
        source="microphone",
        capture_generation=int(
            getattr(win, "_voice_capture_generation", 0) or 0
        ),
        playback_generation=playback.generation,
        playback_epoch=playback.epoch,
        playback_level=max(0.0, min(1.0, playback.level)),
        rms=max(0.0, float(getattr(verdict, "rms", 0.0) or 0.0)),
        threshold=max(
            0.0, float(getattr(verdict, "threshold", 0.0) or 0.0)
        ),
        noise_floor=max(
            0.0, float(getattr(verdict, "noise_floor", 0.0) or 0.0)
        ),
    ), "voice_interrupt_candidate"


def validate_event(
    win: Any,
    event: VoiceInterruptEvent,
    *,
    now: float | None = None,
) -> str:
    """Return an accepted/stale reason without consulting transient UI state."""
    stamp = time.monotonic() if now is None else float(now)
    if event.source != "microphone":
        return "voice_interrupt_source_invalid"
    if stamp < event.detected_at or stamp - event.detected_at > _positive_float(
        config.get("voice.barge_in.event_max_age_s", _CANDIDATE_MAX_AGE_S),
        _CANDIDATE_MAX_AGE_S,
    ):
        return "voice_interrupt_event_stale"
    capture_generation = int(
        getattr(win, "_voice_capture_generation", event.capture_generation) or 0
    )
    if capture_generation != event.capture_generation:
        return "voice_interrupt_capture_stale"
    playback = voice_playback_level.snapshot(now=stamp)
    if playback.generation != event.playback_generation:
        return "voice_interrupt_playback_stale"
    if event.playback_epoch and playback.epoch != event.playback_epoch:
        return "voice_interrupt_playback_stale"
    # A queued event remains valid after the matching authoritative drain. That
    # state transition is exactly the race that used to turn voice into ESC.
    if not playback.active:
        if not playback.drained_at or playback.drained_at < event.detected_at:
            return "voice_interrupt_playback_aborted"
        if stamp - playback.drained_at > _positive_float(
            config.get("voice.barge_in.event_max_age_s", _CANDIDATE_MAX_AGE_S),
            _CANDIDATE_MAX_AGE_S,
        ):
            return "voice_interrupt_event_stale"
    return "voice_interrupt_accepted"


__all__ = [
    "VoiceInterruptEvent",
    "build_microphone_event",
    "validate_event",
]
