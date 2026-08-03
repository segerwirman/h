"""18A: desktop window owns local approval and Focus Mode execution."""
from __future__ import annotations
from pathlib import Path


def test_window_subscribes_voice_proposal_pending_and_handles_confirm_locally():
    source = Path("jarvis/ui/window.py").read_text(encoding="utf-8")
    assert 'BUS.subscribe("voice_proposal.pending"' in source
    assert "def _on_voice_proposal_pending" in source
    assert "_approve_voice_proposal" in source


def test_window_voice_proposal_path_has_no_remote_or_uia_executor():
    source = Path("jarvis/ui/window.py").read_text(encoding="utf-8")
    start = source.index("def _on_voice_proposal_pending")
    end = source.index("def _on_confirm", start)
    segment = source[start:end]
    for forbidden in ("send_from_anywhere", "desktop_safe_click", "CuaSafetyGate", "coordinate", "observation_id"):
        assert forbidden not in segment
    assert "focus_mode_enable" in segment and "focus_mode_disable" in segment


def test_proposal_queue_global_singleton_has_no_remote_approval_method():
    from jarvis.integrations import voice_desktop_proposals
    assert voice_desktop_proposals.get_queue() is voice_desktop_proposals.get_queue()
    assert not hasattr(voice_desktop_proposals.VoiceDesktopProposalQueue, "approve_remote")
    assert not hasattr(voice_desktop_proposals.VoiceDesktopProposalQueue, "execute_from_voice")
