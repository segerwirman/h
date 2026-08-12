"""18A opt-in composition of the bounded voice proposal hook."""
from __future__ import annotations

from jarvis.core import config
from jarvis.integrations.voice_proposal_hook import VoiceProposalHook


def _enabled() -> bool:
    return bool(config.get("routing.voice_desktop_proposals.enabled", False))


def compose(fallback):
    """Return a proposal-first hook; feature-off preserves ``fallback``."""
    if not _enabled():
        return fallback
    if getattr(fallback, "_jarvis_voice_proposal_hook", False):
        return fallback
    proposal = VoiceProposalHook()

    async def composite(live, gate) -> bool:
        if await proposal(live, gate):
            return True
        if callable(fallback):
            return bool(await fallback(live, gate))
        return False

    composite._jarvis_voice_proposal_hook = True
    return composite


__all__ = ["compose"]
