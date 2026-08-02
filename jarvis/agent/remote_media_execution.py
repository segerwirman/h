"""Narrow verified execution adapter for an injected browser-media runner."""
from __future__ import annotations

from jarvis.agent.remote_media_policy import admit, render_result


def _postcondition(action: str, state: dict) -> bool:
    """Intent-specific committed-state proof; unknown shapes fail closed."""
    if not isinstance(state, dict):
        return False
    if action == "play":
        return state.get("playing") is True
    if action == "pause":
        return state.get("playing") is False
    if action == "mute":
        return state.get("muted") is True
    if action == "unmute":
        return state.get("muted") is False
    # status / volume_* have no observable baseline here; success means the
    # renderer shape is valid (render_result enforces playing/muted/volume).
    return True


async def execute(action: str, *, runner) -> dict:
    allowed = admit(action)
    if not allowed.get("allowed"):
        return {"ok": False, "reason": allowed["reason"]}
    try:
        result = await runner(action=allowed["action"])
        if not getattr(result, "ok", False):
            return {"ok": False, "reason": "remote_media_unavailable"}
        content = getattr(result, "content", None)
    except Exception:
        return {"ok": False, "reason": "remote_media_unavailable"}
    if not _postcondition(allowed["action"], content):
        return {"ok": False, "reason": "remote_media_state_not_matched"}
    return render_result(content)


_PROPOSAL_ACTIONS = {
    "media_play": "play", "media_pause": "pause", "media_mute": "mute",
    "media_unmute": "unmute", "media_volume_up": "volume_up",
    "media_volume_down": "volume_down",
}


async def execute_proposal(action: str, *, runner) -> dict:
    media_action = _PROPOSAL_ACTIONS.get(str(action or ""))
    if media_action is None:
        return {"ok": False, "reason": "remote_media_action_rejected"}
    return await execute(media_action, runner=runner)


__all__ = ["execute", "execute_proposal"]
