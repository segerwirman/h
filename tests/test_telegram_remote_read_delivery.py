"""Fase 15A: hasil GWS direct Telegram harus melalui renderer session-bound."""
from __future__ import annotations

import asyncio


def _ctx(session_id="chat-a"):
    from jarvis.agent.execution_context import ExecutionContext
    return ExecutionContext.create(source="telegram", actor_id="actor", session_id=session_id,
                                   surface="remote", toolsets={"gws_read"})


def test_google_direct_remote_renders_safe_payload_before_delivery(monkeypatch):
    from jarvis.agent.adapters import telegram_light
    from jarvis.agent.base import ToolResult
    from jarvis.agent.router import Route, Tier

    async def fake_tool(name, args, *, context=None):
        assert name == "gmail_safe_summary"
        return ToolResult.success({"unread_count": 1, "items": [
            {"sender": "ab…@example.com", "subject": "Rapat", "time": "t", "sensitive": False}]})
    from jarvis.agent import registry
    monkeypatch.setattr(registry, "execute", fake_tool)
    from jarvis.integrations import google_direct
    monkeypatch.setattr(google_direct, "enabled_by_tool_group", lambda _name: True)
    from jarvis.agent import registry
    monkeypatch.setattr(registry, "get", lambda _name: object())

    result = asyncio.run(telegram_light._google_direct("ada email baru?", context=_ctx()))

    assert result.ok is True
    assert "Email belum dibaca: 1" in result.content
    assert "ab…@example.com" in result.content


def test_google_direct_remote_rejects_malformed_output(monkeypatch):
    from jarvis.agent.adapters import telegram_light
    from jarvis.agent.base import ToolResult

    async def fake_tool(name, args, *, context=None):
        return ToolResult.success({"token": "NO-LEAK", "items": []})
    from jarvis.agent import registry
    monkeypatch.setattr(registry, "execute", fake_tool)
    from jarvis.integrations import google_direct
    monkeypatch.setattr(google_direct, "enabled_by_tool_group", lambda _name: True)
    from jarvis.agent import registry
    monkeypatch.setattr(registry, "get", lambda _name: object())

    result = asyncio.run(telegram_light._google_direct("ada email baru?", context=_ctx()))

    assert result.ok is False
    assert "NO-LEAK" not in str(result.error)
    assert result.error == "remote_read_payload_rejected"


def test_google_direct_local_keeps_native_tool_result(monkeypatch):
    from jarvis.agent.adapters import telegram_light
    from jarvis.agent.base import ToolResult
    from jarvis.agent.execution_context import ExecutionContext

    async def fake_tool(name, args, *, context=None):
        return ToolResult.success("local native result")
    from jarvis.agent import registry
    monkeypatch.setattr(registry, "execute", fake_tool)
    monkeypatch.setattr(registry, "get", lambda _name: object())
    from jarvis.integrations import google_direct
    monkeypatch.setattr(google_direct, "enabled_by_tool_group", lambda _name: True)
    local = ExecutionContext.create(source="ui", actor_id="local", session_id="desktop",
                                    surface="desktop", toolsets={"gws_read"})

    result = asyncio.run(telegram_light._google_direct("agenda hari ini", context=local))

    assert result.content == "local native result"


def test_remote_fallthrough_never_reaches_local_branches():
    from jarvis.integrations import google_direct

    assert google_direct.match_command(
        "video terbaru dari langganan", remote=True) is None
    assert google_direct.match_command(
        "buat acara besok", remote=True) is None
    assert google_direct.match_command(
        "video terbaru dari langganan", remote=False) is not None
