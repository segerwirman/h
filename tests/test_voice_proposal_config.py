"""18A config and authority regressions."""
from __future__ import annotations


def test_voice_desktop_proposals_default_off_and_routing_is_not_clobbered():
    from jarvis.core import config
    assert config.get("routing.voice_desktop_proposals.enabled") is False
    assert config.get("routing.voice_l1_hook.timeout_ms") == 50


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
