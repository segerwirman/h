"""Characterization tests for Google tools on the Gemini Live voice seam."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.agent.base import ToolResult


def _legacy_module(*, declarations=None):
    fallback = object()

    class _Live:
        def __init__(self, *, muted=False):
            self.ui = SimpleNamespace(muted=muted, states=[])
            self.ui.set_state = self.ui.states.append
            self.fallback_calls = []

        async def _execute_tool(self, fc):
            self.fallback_calls.append(fc)
            return fallback

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=list(declarations or []),
        JarvisLive=_Live,
        types=SimpleNamespace(FunctionResponse=lambda **values: values),
    )
    return legacy, fallback


def test_google_install_preserves_success_response_and_ui_state(monkeypatch):
    from jarvis.agent import registry
    from jarvis.integrations import google_voice, voice_native_tools

    legacy, _fallback = _legacy_module()
    calls = []
    result = ToolResult.success({"events": 2}, display="dua agenda")

    async def execute(name, args):
        calls.append((name, args))
        return result

    monkeypatch.setattr(voice_native_tools, "_legacy", None)
    monkeypatch.setattr(google_voice, "declarations", lambda: [])
    monkeypatch.setattr(registry, "execute", execute)

    voice_native_tools.sync_google_declarations(legacy)
    voice_native_tools.install(legacy)
    live = legacy.JarvisLive()
    call = SimpleNamespace(
        id="google-call-1", name="gcal_events", args={"start": "today"}
    )
    response = asyncio.run(live._execute_tool(call))

    assert calls == [("gcal_events", {"start": "today"})]
    assert response == {
        "id": "google-call-1",
        "name": "gcal_events",
        "response": {
            "result": result.for_llm(),
            "ok": True,
            "error": "",
        },
    }
    assert live.ui.states == ["THINKING", "LISTENING"]
    assert live.fallback_calls == []


def test_google_install_preserves_failure_muted_and_exception_contract(monkeypatch):
    from jarvis.agent import registry
    from jarvis.integrations import google_voice, voice_native_tools

    legacy, _fallback = _legacy_module()
    failure = ToolResult.fail("scope ditolak")

    async def execute_failure(_name, _args):
        return failure

    monkeypatch.setattr(voice_native_tools, "_legacy", None)
    monkeypatch.setattr(google_voice, "declarations", lambda: [])
    monkeypatch.setattr(registry, "execute", execute_failure)
    voice_native_tools.sync_google_declarations(legacy)
    voice_native_tools.install(legacy)

    live = legacy.JarvisLive(muted=True)
    call = SimpleNamespace(id="google-call-2", name="gmail_read", args=None)
    response = asyncio.run(live._execute_tool(call))

    assert response["id"] == "google-call-2"
    assert response["name"] == "gmail_read"
    assert response["response"] == {
        "result": failure.for_llm(),
        "ok": False,
        "error": "scope ditolak",
    }
    assert live.ui.states == ["THINKING"]

    async def execute_error(_name, _args):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(registry, "execute", execute_error)
    unmuted = legacy.JarvisLive()
    with pytest.raises(RuntimeError, match="registry unavailable"):
        asyncio.run(unmuted._execute_tool(call))
    assert unmuted.ui.states == ["THINKING"]


def test_google_install_delegates_fallback_and_is_idempotent(monkeypatch):
    from jarvis.integrations import google_voice, voice_native_tools

    legacy, fallback = _legacy_module()
    monkeypatch.setattr(voice_native_tools, "_legacy", None)
    monkeypatch.setattr(google_voice, "declarations", lambda: [])

    voice_native_tools.sync_google_declarations(legacy)
    voice_native_tools.install(legacy)
    installed = legacy.JarvisLive._execute_tool
    voice_native_tools.install(legacy)

    assert legacy.JarvisLive._execute_tool is installed
    live = legacy.JarvisLive()
    call = SimpleNamespace(id="fallback-1", name="system_status", args={})
    assert asyncio.run(live._execute_tool(call)) is fallback
    assert live.fallback_calls == [call]


def test_google_declaration_sync_replaces_without_duplicates(monkeypatch):
    from jarvis.integrations import google_voice, voice_native_tools

    legacy, _fallback = _legacy_module(
        declarations=[
            {"name": "base_tool"},
            {"name": "gcal_events", "version": "stale"},
            {"name": "task_start"},
        ]
    )
    current = [{"name": "gcal_events", "version": "fresh"}]
    monkeypatch.setattr(voice_native_tools, "_legacy", None)
    monkeypatch.setattr(google_voice, "declarations", lambda: list(current))

    voice_native_tools.sync_google_declarations(legacy)
    voice_native_tools.install(legacy)
    google_items = [
        item for item in legacy.TOOL_DECLARATIONS
        if item["name"] in google_voice.GOOGLE_TOOL_NAMES
    ]
    assert google_items == [{"name": "gcal_events", "version": "fresh"}]
    assert {"name": "base_tool"} in legacy.TOOL_DECLARATIONS
    task_start = next(
        item for item in legacy.TOOL_DECLARATIONS
        if item["name"] == "task_start"
    )
    assert "version" not in task_start

    current[:] = [{"name": "gmail_list", "version": "next"}]
    voice_native_tools.sync_google_declarations()
    google_items = [
        item for item in legacy.TOOL_DECLARATIONS
        if item["name"] in google_voice.GOOGLE_TOOL_NAMES
    ]
    assert google_items == [{"name": "gmail_list", "version": "next"}]
    assert {"name": "base_tool"} in legacy.TOOL_DECLARATIONS
    task_start = next(
        item for item in legacy.TOOL_DECLARATIONS
        if item["name"] == "task_start"
    )
    assert "version" not in task_start


def test_combined_wrapper_routes_native_and_google_once(monkeypatch):
    from jarvis.agent import registry
    from jarvis.integrations import google_voice, voice_native_tools

    legacy, fallback = _legacy_module()
    calls = []

    async def execute(name, args, **kwargs):
        calls.append((name, args, kwargs))
        return ToolResult.success(name)

    monkeypatch.setattr(voice_native_tools, "_legacy", None)
    monkeypatch.setattr(google_voice, "declarations", lambda: [])
    monkeypatch.setattr(registry, "execute", execute)

    voice_native_tools.sync_google_declarations(legacy)
    voice_native_tools.install(legacy)
    installed = legacy.JarvisLive._execute_tool
    voice_native_tools.install(legacy)

    live = legacy.JarvisLive()
    google_call = SimpleNamespace(id="g-1", name="gcal_next", args={})
    native_call = SimpleNamespace(
        id="n-1", name="capability_status", args={"detail": True}
    )
    fallback_call = SimpleNamespace(id="f-1", name="system_status", args={})

    google_response = asyncio.run(live._execute_tool(google_call))
    native_response = asyncio.run(live._execute_tool(native_call))
    fallback_response = asyncio.run(live._execute_tool(fallback_call))

    assert legacy.JarvisLive._execute_tool is installed
    assert calls == [
        ("gcal_next", {}, {}),
        (
            "capability_status",
            {"detail": True},
            {"adapter": None, "session": SimpleNamespace(id="voice-native-direct")},
        ),
    ]
    assert google_response["id"] == "g-1"
    assert native_response["id"] == "n-1"
    assert fallback_response is fallback
    assert live.fallback_calls == [fallback_call]
    assert not (
        voice_native_tools.native_tool_names()
        & google_voice.GOOGLE_TOOL_NAMES
    )
