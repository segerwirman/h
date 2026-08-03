"""18A opt-in composition of bounded voice proposal hook into legacy seam."""
from __future__ import annotations

from jarvis.core import config
from jarvis.integrations.voice_proposal_hook import VoiceProposalHook


def _enabled() -> bool:
    return bool(config.get("routing.voice_desktop_proposals.enabled", False))


def install(legacy) -> bool:
    """Install a fail-open composite hook; feature-off leaves legacy untouched."""
    if not _enabled():
        return False
    if getattr(legacy, "_jarvis_voice_proposal_hook", False):
        return True
    fallback = getattr(legacy, "VOICE_L1_HOOK", None)
    proposal = VoiceProposalHook()

    async def composite(live, gate) -> bool:
        if await proposal(live, gate):
            return True
        if callable(fallback):
            return bool(await fallback(live, gate))
        return False

    legacy.VOICE_L1_HOOK = composite
    legacy._jarvis_voice_proposal_hook = True
    return True


__all__ = ["install"]
