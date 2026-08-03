"""Phase 23 — bounded per-scene duration policy and cumulative SRT timing.

Pure in-memory helpers only: no filesystem, no render, no network.
Durations are finite integers within a bounded range; the total project
duration is capped. SRT output uses standard HH:MM:SS,mmm cumulative timing.
"""
from __future__ import annotations

MAX_SCENE_DURATION_S = 600
MAX_TOTAL_DURATION_S = 3600
DEFAULT_DURATION_S = 5


def admit_duration(value: object) -> dict:
    """Admit only a finite bounded integer duration in seconds."""
    if isinstance(value, bool) or not isinstance(value, int):
        return {"ok": False, "reason": "content_duration_type_rejected"}
    if not 1 <= value <= MAX_SCENE_DURATION_S:
        return {"ok": False, "reason": "content_duration_range_rejected"}
    return {"ok": True, "duration": value}


def admit_durations(values: object) -> dict:
    """Admit a sequence of bounded durations with a total project cap."""
    if not isinstance(values, (list, tuple)):
        return {"ok": False, "reason": "content_durations_type_rejected"}
    durations = []
    for value in values:
        result = admit_duration(value)
        if not result.get("ok"):
            return {"ok": False,
                    "reason": result.get("reason", "content_duration_rejected")}
        durations.append(result["duration"])
    if sum(durations) > MAX_TOTAL_DURATION_S:
        return {"ok": False, "reason": "content_durations_total_rejected"}
    return {"ok": True, "durations": durations}


def default_durations(count: int) -> list[int]:
    """Bounded default per-scene duration (backward-compatible 5s each)."""
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        return []
    return [DEFAULT_DURATION_S] * count


def cumulative_timings(durations: list[int]) -> list[tuple[int, int]]:
    """Exact cumulative (start_s, end_s) windows for each scene."""
    windows = []
    cursor = 0
    for duration in durations:
        windows.append((cursor, cursor + duration))
        cursor += duration
    return windows


def srt_timestamp(total_seconds: int) -> str:
    """Standard SRT timestamp HH:MM:SS,mmm (milliseconds always 000)."""
    seconds = max(0, int(total_seconds))
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},000"


def build_srt(durations: list[int], texts: list[str]) -> dict:
    """Cumulative SRT string; text count must match duration count."""
    admitted = admit_durations(durations)
    if not admitted.get("ok"):
        return {"ok": False,
                "reason": admitted.get("reason", "content_srt_durations_rejected")}
    if len(texts) != len(durations):
        return {"ok": False, "reason": "content_srt_texts_mismatch"}
    blocks = []
    for index, ((start, end), text) in enumerate(
            zip(cumulative_timings(durations), texts), start=1):
        blocks.append(
            f"{index}\n{srt_timestamp(start)} --> {srt_timestamp(end)}\n{text}\n")
    return {"ok": True, "content": "".join(blocks)}


__all__ = [
    "admit_duration", "admit_durations", "default_durations",
    "cumulative_timings", "srt_timestamp", "build_srt",
    "MAX_SCENE_DURATION_S", "MAX_TOTAL_DURATION_S", "DEFAULT_DURATION_S",
]
