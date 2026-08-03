"""18A final-voice ingress: stage a proposal; never execute a desktop action."""
from __future__ import annotations

from jarvis.core.bus import BUS
from jarvis.integrations.voice_desktop_proposals import VoiceDesktopProposalQueue, get_queue


class VoiceProposalHook:
    def __init__(self, *, queue: VoiceDesktopProposalQueue | None = None) -> None:
        self._queue = queue or get_queue()

    async def __call__(self, live, gate) -> bool:
        result = self._queue.request_from_voice(getattr(gate, "text", ""), final=True)
        if not result.get("accepted"):
            return False
        BUS.publish("voice_proposal.pending", proposal_id=result["proposal_id"], action=result["action"])
        reset = getattr(gate, "reset", None)
        if callable(reset):
            reset()
        speak = getattr(live, "speak", None)
        if callable(speak):
            speak("Permintaan diterima. Menunggu persetujuan lokal.")
        return True


__all__ = ["VoiceProposalHook"]
