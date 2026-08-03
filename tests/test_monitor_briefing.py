"""Phase 17D: opt-in local monitor section for the morning briefing."""
from __future__ import annotations

import asyncio


def test_monitor_boot_briefing_defaults_off(monkeypatch):
    from jarvis.core import briefing
    monkeypatch.setattr(briefing.config, "get", lambda key, default=None: default)
    assert briefing.boot_monitor_enabled() is False


def test_compose_briefing_omits_monitor_when_disabled():
    from jarvis.core import briefing
    text = briefing.compose_briefing(
        agenda={"count": 0, "items": []}, gmail={"unread_count": 0, "items": []},
        monitor={"source": "News", "items": [{"title": "Monitor Update", "url": "https://e/u"}]},
        include_monitor=False,
    )
    assert "Monitor Update" not in text


def test_compose_briefing_includes_bounded_monitor_titles_without_urls():
    from jarvis.core import briefing
    monitor = {"source": "News", "items": [
        {"title": "Update A", "url": "https://example.org/a", "hash": "x"},
        {"title": "Update B", "url": "https://example.org/b", "hash": "y"},
        {"title": "Update C", "url": "https://example.org/c", "hash": "z"},
        {"title": "Update D", "url": "https://example.org/d", "hash": "q"},
    ]}
    text = briefing.compose_briefing(
        agenda={}, gmail={}, monitor=monitor, include_monitor=True)
    assert "Update A" in text and "Update C" in text
    assert "Update D" not in text
    assert "https://" not in text and "hash" not in text
    assert len(text) <= 600


def test_monitor_payload_with_body_or_secret_is_omitted():
    from jarvis.core import briefing
    text = briefing.compose_briefing(
        monitor={"source": "News", "items": [{"title": "X", "body": "secret"}]},
        include_monitor=True,
    )
    assert "secret" not in text and "X" not in text


def test_briefing_tool_reads_monitor_store_only_when_enabled(monkeypatch):
    from jarvis.agent.tools import briefing_tool
    from jarvis.agent.tools.briefing_tool import BriefingTool
    monkeypatch.setattr(briefing_tool, "_agenda_today", lambda: {"count": 0, "items": []})
    monkeypatch.setattr(briefing_tool, "_gmail_unread", lambda: {"unread_count": 0, "items": []})
    monkeypatch.setattr(briefing_tool.briefing, "boot_monitor_enabled", lambda: True)
    calls = []
    monkeypatch.setattr(briefing_tool, "_monitor_latest", lambda: calls.append(True) or {
        "source": "News", "items": [{"title": "Safe monitor item", "url": "https://e/u", "hash": "h"}]})
    result = asyncio.run(BriefingTool().run())
    assert result.ok is True and calls == [True]
    assert "Safe monitor item" in result.content["briefing"]
    assert "https://" not in result.content["briefing"]


def test_briefing_tool_does_not_touch_monitor_store_when_disabled(monkeypatch):
    from jarvis.agent.tools import briefing_tool
    from jarvis.agent.tools.briefing_tool import BriefingTool
    monkeypatch.setattr(briefing_tool, "_agenda_today", lambda: {"count": 0, "items": []})
    monkeypatch.setattr(briefing_tool, "_gmail_unread", lambda: {"unread_count": 0, "items": []})
    monkeypatch.setattr(briefing_tool.briefing, "boot_monitor_enabled", lambda: False)
    monkeypatch.setattr(briefing_tool, "_monitor_latest", lambda: (_ for _ in ()).throw(AssertionError("must not read")))
    result = asyncio.run(BriefingTool().run())
    assert result.ok is True


def test_monitor_failure_does_not_block_calendar_or_email(monkeypatch):
    from jarvis.agent.tools import briefing_tool
    from jarvis.agent.tools.briefing_tool import BriefingTool
    monkeypatch.setattr(briefing_tool, "_agenda_today", lambda: {"count": 1, "items": [{"title": "Standup", "time": "10:00"}]})
    monkeypatch.setattr(briefing_tool, "_gmail_unread", lambda: {"unread_count": 2, "items": []})
    monkeypatch.setattr(briefing_tool.briefing, "boot_monitor_enabled", lambda: True)
    monkeypatch.setattr(briefing_tool, "_monitor_latest", lambda: (_ for _ in ()).throw(RuntimeError("db failed")))
    result = asyncio.run(BriefingTool().run())
    assert "Standup" in result.content["briefing"] and "2 email" in result.content["briefing"]
    assert "db failed" not in result.content["briefing"]
