"""Fase 16B: gmail_safe tool — unread summary privacy-tiered, read-only."""
from __future__ import annotations

import asyncio


def test_gmail_safe_tool_is_read_only_no_body_input():
    from jarvis.agent.tools.gmail_safe import GmailSafeSummary

    tool = GmailSafeSummary()
    props = tool.json_schema()["properties"]
    assert tool.read_only is True
    assert tool.requires_confirmation is False
    assert not {"to", "subject", "body", "send", "message_id"} & set(props)


def test_gmail_safe_returns_masked_summary(monkeypatch):
    from jarvis.agent.tools import gmail_safe
    from jarvis.agent.tools.gmail_safe import GmailSafeSummary

    raw = [
        {"from": "Budi <budi.santoso@example.com>", "subject": "Rapat", "date": "t1"},
        {"from": "sec@z.com", "subject": "Your OTP 123456", "date": "t2"},
    ]
    monkeypatch.setattr(gmail_safe, "_fetch_unread_metadata", lambda limit: raw)
    monkeypatch.setattr(gmail_safe.google_auth, "has_read_scope", lambda api: True)

    result = asyncio.run(GmailSafeSummary().run())

    assert result.ok is True
    blob = str(result.content)
    assert "budi.santoso" not in blob
    assert "123456" not in blob
    assert result.content["unread_count"] == 2


def test_gmail_safe_unavailable_without_scope(monkeypatch):
    from jarvis.agent.tools import gmail_safe
    from jarvis.agent.tools.gmail_safe import GmailSafeSummary

    monkeypatch.setattr(gmail_safe.google_auth, "has_read_scope", lambda api: False)
    tool = GmailSafeSummary()

    assert tool.is_available() is False


def test_gmail_safe_error_is_sanitized(monkeypatch):
    from jarvis.agent.tools import gmail_safe
    from jarvis.agent.tools.gmail_safe import GmailSafeSummary

    def boom(_limit):
        raise RuntimeError("raw token abc123 leaked")
    monkeypatch.setattr(gmail_safe, "_fetch_unread_metadata", boom)
    monkeypatch.setattr(gmail_safe.google_auth, "has_read_scope", lambda api: True)

    result = asyncio.run(GmailSafeSummary().run())

    assert result.ok is False
    assert "abc123" not in str(result.error)
