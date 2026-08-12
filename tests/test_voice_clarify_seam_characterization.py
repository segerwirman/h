"""Characterization tests for clarify on the Gemini Live voice seam."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace


def _legacy_module(*, declarations=None):
    fallback = object()

    class _Live:
        def __init__(self):
            self.fallback_calls = []

        async def _execute_tool(self, fc):
            self.fallback_calls.append(fc)
            return fallback

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=list(declarations or []),
        JarvisLive=_Live,
        types=SimpleNamespace(FunctionResponse=lambda **values: values),
        _load_system_prompt=lambda: "PERSONA\n[MULTI-TASKING]\n",
    )
    return legacy, fallback


def _install_stack(monkeypatch, legacy):
    from jarvis.integrations import voice_native_tools

    monkeypatch.setattr(voice_native_tools, "_legacy", None)

    voice_native_tools.install(legacy)
    clarify_exec = legacy.JarvisLive._execute_tool
    clarify_prompt = legacy._load_system_prompt
    voice_native_tools.install(legacy)
    assert legacy.JarvisLive._execute_tool is clarify_exec
    assert legacy._load_system_prompt is clarify_prompt

    return voice_native_tools


def test_stack_replaces_declarations_in_runtime_order(monkeypatch):
    from jarvis.integrations import voice_clarify

    legacy, _fallback = _legacy_module(declarations=[
        {"name": "base_tool"},
        {"name": "capability_status", "version": "stale-native"},
        {"name": "clarify", "version": "stale-clarify"},
        {"name": "shutdown_jarvis", "version": "stale-safety"},
        {"name": "close_app", "version": "stale-safety"},
    ])

    _install_stack(monkeypatch, legacy)

    names = [item["name"] for item in legacy.TOOL_DECLARATIONS]
    assert names.count("capability_status") == 1
    assert names.count("clarify") == 1
    assert names.count("shutdown_jarvis") == 1
    assert names.count("close_app") == 1
    assert names.index("capability_status") < names.index("clarify")
    assert names.index("clarify") < names.index("shutdown_jarvis")
    assert names.index("shutdown_jarvis") < names.index("close_app")
    clarify = next(item for item in legacy.TOOL_DECLARATIONS
                   if item["name"] in voice_clarify.CLARIFY_TOOL_NAMES)
    assert "version" not in clarify


def test_stack_preserves_prompt_section_order_once(monkeypatch):
    legacy, _fallback = _legacy_module()

    _install_stack(monkeypatch, legacy)
    prompt = legacy._load_system_prompt()

    sections = [
        "[MULTI-TASKING]",
        "[KONTROL NATIVE CEPAT]",
        "[SAAT RAGU",
        "[MENUTUP SESUATU]",
    ]
    assert [prompt.count(section) for section in sections] == [1, 1, 1, 1]
    assert [prompt.index(section) for section in sections] == sorted(
        prompt.index(section) for section in sections
    )


def test_stack_preserves_clarify_response_and_call_id(monkeypatch):
    from jarvis.integrations import voice_clarify

    legacy, _fallback = _legacy_module()
    handled = []

    def handle(args):
        handled.append(args)
        return "Ajukan pertanyaan ini."

    monkeypatch.setattr(voice_clarify, "handle", handle)
    _install_stack(monkeypatch, legacy)

    live = legacy.JarvisLive()
    call = SimpleNamespace(
        id="clarify-call-1",
        name="clarify",
        args={"question": "Aplikasi atau browser?", "topic": "instagram"},
    )
    response = asyncio.run(live._execute_tool(call))

    assert handled == [{
        "question": "Aplikasi atau browser?",
        "topic": "instagram",
    }]
    assert response == {
        "id": "clarify-call-1",
        "name": "clarify",
        "response": {
            "result": "Ajukan pertanyaan ini.",
            "ok": True,
            "error": "",
        },
    }
    assert live.fallback_calls == []


def test_stack_delegates_unknown_tool_exactly_once(monkeypatch):
    legacy, fallback = _legacy_module()
    _install_stack(monkeypatch, legacy)

    live = legacy.JarvisLive()
    call = SimpleNamespace(id="fallback-call-1", name="system_status", args={})

    assert asyncio.run(live._execute_tool(call)) is fallback
    assert live.fallback_calls == [call]


def test_stack_dispatches_safety_once_with_legacy_response(monkeypatch):
    from jarvis.integrations import voice_safety

    legacy, _fallback = _legacy_module()
    monkeypatch.setattr(
        voice_safety,
        "handle_shutdown",
        lambda args, live=None: (f"confirmation:{args}", True),
    )
    _install_stack(monkeypatch, legacy)

    live = legacy.JarvisLive()
    call = SimpleNamespace(
        id="safety-call-1", name="shutdown_jarvis", args={"confirmed": "no"}
    )
    response = asyncio.run(live._execute_tool(call))

    assert response == {
        "id": "safety-call-1",
        "name": "shutdown_jarvis",
        "response": {
            "result": "confirmation:{'confirmed': 'no'}",
            "ok": True,
            "error": "",
        },
    }
    assert live.fallback_calls == []


def test_clarify_names_are_disjoint_from_neighboring_owners():
    from jarvis.integrations import (
        google_voice,
        voice_clarify,
        voice_native_tools,
        voice_safety,
        voice_tasks,
    )

    neighbors = (
        google_voice.GOOGLE_TOOL_NAMES
        | voice_native_tools.native_tool_names()
        | voice_safety.SAFETY_TOOL_NAMES
        | voice_tasks.TASK_TOOL_NAMES
    )
    assert not (voice_clarify.CLARIFY_TOOL_NAMES & neighbors)
