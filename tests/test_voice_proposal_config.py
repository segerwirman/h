"""18A config and authority regressions."""
from __future__ import annotations


def test_hook_stages_but_never_executes_focus_mode(monkeypatch):
    import asyncio
    from jarvis.integrations.voice_proposal_hook import VoiceProposalHook
    from jarvis.integrations.voice_desktop_proposals import VoiceDesktopProposalQueue
    queue = VoiceDesktopProposalQueue()
    hook = VoiceProposalHook(queue=queue)
    class Gate:
        text = "aktifkan mode fokus"
        def reset(self): pass
    class Live:
        def speak(self, _): pass
    assert asyncio.run(hook(Live(), Gate())) is True
    proposal = next(iter(queue._items.values()))
    assert proposal.status == "pending_local_approval"
    assert proposal.action == "focus_mode_enable"
    assert not hasattr(hook, "approve_local")
    assert not hasattr(hook, "execute")
