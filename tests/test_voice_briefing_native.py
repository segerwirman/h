"""18B native execution returns only the safe briefing field."""
from __future__ import annotations


def test_voice_briefing_is_read_only_and_no_confirmation():
    from jarvis.agent.tools.voice_briefing import VoiceBriefing
    tool = VoiceBriefing()
    assert tool.read_only is True
    assert tool.requires_confirmation is False
    assert tool.params_schema.model_fields == {}
