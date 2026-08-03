"""18A: editable hook turns final voice into a local proposal, never execution."""
from __future__ import annotations
import asyncio


def test_hook_only_handles_final_text_and_publishes_metadata(monkeypatch):
    from jarvis.integrations import voice_proposal_hook
    events, spoken = [], []
    monkeypatch.setattr(voice_proposal_hook.BUS, "publish", lambda topic, **data: events.append((topic, data)))
    hook = voice_proposal_hook.VoiceProposalHook()
    class Gate:
        text = "aktifkan mode fokus"
        def __init__(self): self.reset_count = 0
        def reset(self): self.reset_count += 1
    gate = Gate()
    class Live:
        def speak(self, text): spoken.append(text)
    assert asyncio.run(hook(Live(), gate)) is True
    assert gate.reset_count == 1
    assert spoken and "persetujuan lokal" in spoken[0].lower()
    assert events[0][0] == "voice_proposal.pending"
    assert set(events[0][1]) == {"proposal_id", "action"}


def test_hook_rejects_unsupported_without_mutating_gate(monkeypatch):
    from jarvis.integrations import voice_proposal_hook
    events = []
    monkeypatch.setattr(voice_proposal_hook.BUS, "publish", lambda *a, **kw: events.append((a, kw)))
    class Gate:
        text = "klik tombol beli"
        def reset(self): raise AssertionError("must not reset")
    class Live:
        def speak(self, _): raise AssertionError("must not speak")
    assert asyncio.run(voice_proposal_hook.VoiceProposalHook()(Live(), Gate())) is False
    assert events == []


def test_hook_never_imports_executor_or_desktop_safe_tool():
    from jarvis.integrations import voice_proposal_hook
    source = open(voice_proposal_hook.__file__, encoding="utf-8").read()
    for forbidden in ("local_action_executor", "desktop_safe_click", "CuaSafetyGate", "approve_local"):
        assert forbidden not in source
