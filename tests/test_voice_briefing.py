"""18B: explicit voice briefing is read-only and summary-only."""
from __future__ import annotations
import asyncio


def test_native_voice_schema_exposes_only_parameterless_voice_briefing():
    from jarvis.integrations import voice_native_tools
    declaration = next(item for item in voice_native_tools.declarations() if item["name"] == "voice_briefing")
    assert declaration["parameters"] == {"type": "OBJECT", "properties": {}}
    assert "read-only" in declaration["description"].lower()


def test_voice_briefing_tool_returns_only_bounded_spoken_text(monkeypatch):
    from jarvis.agent.tools import voice_briefing
    monkeypatch.setattr(voice_briefing, "_safe_briefing", lambda: {
        "briefing": "Ada 1 acara. Ada 2 email belum dibaca.",
        "raw": {"body": "secret", "coordinate": [1, 2]},
    })
    result = asyncio.run(voice_briefing.VoiceBriefing().run())
    assert result.ok is True
    assert result.content == {"briefing": "Ada 1 acara. Ada 2 email belum dibaca."}
    assert "secret" not in result.display and "coordinate" not in result.display
    assert len(result.display) <= 600


def test_voice_briefing_degrades_to_safe_message_not_raw_exception(monkeypatch):
    from jarvis.agent.tools import voice_briefing
    monkeypatch.setattr(voice_briefing, "_safe_briefing", lambda: (_ for _ in ()).throw(RuntimeError("token raw")))
    result = asyncio.run(voice_briefing.VoiceBriefing().run())
    assert result.ok is True
    assert "token" not in result.display.lower()


def test_voice_briefing_source_never_imports_gmail_calendar_raw_or_tts():
    from jarvis.agent.tools import voice_briefing
    source = open(voice_briefing.__file__, encoding="utf-8").read()
    for forbidden in ("gmail_safe", "google_calendar", "fetch_source", "text_to_speech", "send_from_anywhere"):
        assert forbidden not in source


def test_non_explicit_conversation_does_not_match_voice_briefing_rule():
    from jarvis.integrations import voice_briefing_rules
    assert voice_briefing_rules.match("jelaskan briefing") is False
    assert voice_briefing_rules.match("bacakan briefing") is True
    assert voice_briefing_rules.match("briefing pagi") is True
    assert voice_briefing_rules.match("apa kabar") is False
