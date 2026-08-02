"""Pure narrow policy and safe result renderer for remote browser media."""
from __future__ import annotations

import math

_ALLOWED = frozenset({"status", "play", "pause", "mute", "unmute", "volume_up", "volume_down"})


def admit(action: str) -> dict:
    value = str(action or "").strip().casefold()
    if value not in _ALLOWED:
        return {"allowed": False, "reason": "remote_media_action_rejected"}
    return {"allowed": True, "action": value}


def render_result(state: dict | None) -> dict:
    if not isinstance(state, dict) or not isinstance(state.get("playing"), bool):
        return {"ok": False, "reason": "remote_media_unavailable"}
    muted = state.get("muted")
    volume = state.get("volume")
    if not isinstance(muted, bool) or not isinstance(volume, (int, float)) or isinstance(volume, bool):
        return {"ok": False, "reason": "remote_media_unavailable"}
    numeric_volume = float(volume)
    if not math.isfinite(numeric_volume):
        return {"ok": False, "reason": "remote_media_unavailable"}
    percent = max(0, min(100, round(numeric_volume * 100)))
    return {"ok": True, "media": {
        "state": "playing" if state["playing"] else "paused",
        "muted": muted,
        "volume_percent": percent,
    }}


__all__ = ["admit", "render_result"]
