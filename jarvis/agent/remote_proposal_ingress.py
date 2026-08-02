"""Narrow text-to-metadata adapter for one bounded remote request lane."""
from __future__ import annotations

_PHRASES = {
    "aktifkan mode fokus": "focus_mode_enable",
    "nyalakan mode fokus": "focus_mode_enable",
    "nonaktifkan mode fokus": "focus_mode_disable",
    "matikan mode fokus": "focus_mode_disable",
    "putar media": "media_play",
    "pause media": "media_pause",
    "mute media": "media_mute",
    "unmute media": "media_unmute",
    "volume naik": "media_volume_up",
    "volume turun": "media_volume_down",
}


def stage_text(queue, *, actor_id: str, session_id: str, text: str, paired: bool) -> dict:
    actor = str(actor_id or "").strip()
    session = str(session_id or "").strip()
    if not actor or not session or not isinstance(paired, bool):
        return {"accepted": False, "reason": "remote_proposal_context_rejected"}
    action = _PHRASES.get(" ".join(str(text or "").casefold().split()), "")
    return queue.request(
        actor_id=actor,
        session_id=session,
        action=action,
        paired=paired,
    )


__all__ = ["stage_text"]
