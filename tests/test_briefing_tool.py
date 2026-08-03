"""Fase 16D: briefing tool — on-request local morning briefing."""
from __future__ import annotations

import asyncio


def test_briefing_tool_read_only_no_input():
    from jarvis.agent.tools.briefing_tool import BriefingTool

    tool = BriefingTool()
    assert tool.read_only is True
    assert tool.requires_confirmation is False


def test_briefing_tool_composes_from_calendar_and_gmail(monkeypatch):
    from jarvis.agent.tools import briefing_tool
    from jarvis.agent.tools.briefing_tool import BriefingTool

    monkeypatch.setattr(briefing_tool, "_agenda_today",
                        lambda: {"count": 1, "items": [{"title": "Standup", "time": "10:00"}]})
    monkeypatch.setattr(briefing_tool, "_gmail_unread",
                        lambda: {"unread_count": 2, "items": []})

    result = asyncio.run(BriefingTool().run())

    assert result.ok is True
    assert "1 acara" in result.content["briefing"]
    assert "2 email" in result.content["briefing"]


def test_briefing_tool_degrades_when_sources_unavailable(monkeypatch):
    from jarvis.agent.tools import briefing_tool
    from jarvis.agent.tools.briefing_tool import BriefingTool

    monkeypatch.setattr(briefing_tool, "_agenda_today",
                        lambda: (_ for _ in ()).throw(RuntimeError("no calendar scope")))
    monkeypatch.setattr(briefing_tool, "_gmail_unread",
                        lambda: {"unread_count": 0, "items": []})

    result = asyncio.run(BriefingTool().run())

    # honest, non-crashing: calendar failure does not abort the whole briefing
    assert result.ok is True
    assert "briefing" in result.content


def test_briefing_tool_email_content_off_by_default(monkeypatch):
    from jarvis.agent.tools import briefing_tool
    from jarvis.agent.tools.briefing_tool import BriefingTool

    monkeypatch.setattr(briefing_tool, "_agenda_today", lambda: {"count": 0, "items": []})
    monkeypatch.setattr(briefing_tool, "_gmail_unread",
                        lambda: {"unread_count": 1, "items": [
                            {"subject": "Rahasia proyek", "sensitive": False, "sender": "a@b.com", "time": "t"}]})

    result = asyncio.run(BriefingTool().run())

    # default include_email_content is False -> subject not spoken
    assert "Rahasia proyek" not in result.content["briefing"]
    assert "1 email" in result.content["briefing"]
