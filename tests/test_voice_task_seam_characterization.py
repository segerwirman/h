"""Characterization tests for the pre-folded task voice seam."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace


def _legacy_module(*, declarations=None):
    fallback = object()

    class _Live:
        def __init__(self):
            self.fallback_calls = []
            self.session = None
            self._turn_done_event = None
            self._speaking_lock = threading.Lock()
            self._is_speaking = False

        async def _execute_tool(self, fc):
            self.fallback_calls.append(fc)
            return fallback

        async def run(self):
            await asyncio.sleep(0)
            return "run-result"

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=list(declarations or []),
        JarvisLive=_Live,
        types=SimpleNamespace(FunctionResponse=lambda **values: values),
        _load_system_prompt=lambda: "PERSONA\n",
    )
    return legacy, fallback


def _install_stack(monkeypatch, legacy):
    from jarvis.integrations import voice_native_tools, voice_tasks

    monkeypatch.setattr(voice_tasks, "_subscribed", False)
    monkeypatch.setattr(voice_native_tools, "_legacy", None)

    voice_native_tools.install(legacy)

    return voice_tasks


def test_old_stack_replaces_declarations_in_task_native_safety_order(monkeypatch):
    from jarvis.integrations import voice_clarify, voice_native_tools, voice_tasks

    legacy, _fallback = _legacy_module(declarations=[
        {"name": "base_tool"},
        {"name": "task_start", "version": "stale-task"},
        {"name": "capability_status", "version": "stale-native"},
        {"name": "clarify", "version": "stale-clarify"},
        {"name": "shutdown_jarvis", "version": "stale-safety"},
        {"name": "close_app", "version": "stale-safety"},
    ])

    _install_stack(monkeypatch, legacy)

    names = [item["name"] for item in legacy.TOOL_DECLARATIONS]
    assert names.count("task_start") == 1
    assert names.count("capability_status") == 1
    assert names.count("clarify") == 1
    assert names.count("shutdown_jarvis") == 1
    assert names.count("close_app") == 1
    assert names.index("task_start") < names.index("capability_status")
    assert names.index("capability_status") < names.index("clarify")
    assert names.index("clarify") < names.index("shutdown_jarvis")
    assert "version" not in next(
        item for item in legacy.TOOL_DECLARATIONS
        if item["name"] in voice_tasks.TASK_TOOL_NAMES
    )
    assert "version" not in next(
        item for item in legacy.TOOL_DECLARATIONS
        if item["name"] in voice_clarify.CLARIFY_TOOL_NAMES
    )
    assert voice_native_tools.native_tool_names().isdisjoint(
        voice_tasks.TASK_TOOL_NAMES
    )


def test_old_stack_preserves_prompt_order_once(monkeypatch):
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


def test_old_stack_dispatches_task_once_with_legacy_response(monkeypatch):
    from jarvis.agent import dispatch, registry
    from jarvis.integrations import voice_tasks

    legacy, _fallback = _legacy_module()
    calls = []
    scopes = []

    class _Result:
        ok = False
        error = "task failed"

        def for_llm(self):
            return "task result"

    async def execute(name, args):
        calls.append((name, args))
        scope = dispatch.current_source_scope()
        scopes.append(
            (scope.source, scope.completion_owner, scope.conversation_id)
            if scope is not None else ("", "", "")
        )
        return _Result()

    monkeypatch.setattr(registry, "execute", execute)
    _install_stack(monkeypatch, legacy)

    live = legacy.JarvisLive()
    call = SimpleNamespace(
        id="task-call-1", name="task_status", args={"id": "T-1"}
    )
    response = asyncio.run(live._execute_tool(call))

    assert calls == [("task_status", {"id": "T-1"})]
    assert scopes == [("voice-task-tool", "registry", "voice-live")]
    assert response == {
        "id": "task-call-1",
        "name": "task_status",
        "response": {
            "result": "task result",
            "ok": False,
            "error": "task failed",
        },
    }


def test_prompt_rebuild_memuat_context_aktif_tanpa_duplikasi(monkeypatch):
    from jarvis.agent import conversation_context
    from jarvis.integrations import voice_native_tools

    store = conversation_context.ConversationContextStore()
    monkeypatch.setattr(conversation_context, "STORE", store)
    legacy, _fallback = _legacy_module()
    _install_stack(monkeypatch, legacy)

    empty_prompt = legacy._load_system_prompt()
    assert "[KONTEKS PERCAKAPAN LANGSUNG]" not in empty_prompt

    store.begin_task(
        "voice-live",
        task_id="T-reconnect",
        task="riset framework AI",
        source="voice-task-tool",
    )
    first_config_prompt = legacy._load_system_prompt()
    second_config_prompt = legacy._load_system_prompt()
    voice_native_tools.install(legacy)
    reinstalled_prompt = legacy._load_system_prompt()

    for prompt in (first_config_prompt, second_config_prompt, reinstalled_prompt):
        assert "T-reconnect" in prompt
        assert "riset framework AI" in prompt
        assert prompt.count("[KONTEKS PERCAKAPAN LANGSUNG]") == 1


def test_old_stack_delegates_unknown_tool_exactly_once(monkeypatch):
    legacy, fallback = _legacy_module()
    _install_stack(monkeypatch, legacy)

    live = legacy.JarvisLive()
    call = SimpleNamespace(id="fallback-call-1", name="system_status", args={})

    assert asyncio.run(live._execute_tool(call)) is fallback
    assert live.fallback_calls == [call]


def test_old_stack_run_flusher_is_idempotent_and_cancelled(monkeypatch):
    from jarvis.integrations import voice_tasks

    legacy, _fallback = _legacy_module()
    started = asyncio.Event()
    cancelled = asyncio.Event()

    async def fake_notice_loop(_live):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            cancelled.set()
            raise

    monkeypatch.setattr(voice_tasks, "_notice_loop", fake_notice_loop)
    _install_stack(monkeypatch, legacy)
    run_wrapper = legacy.JarvisLive.run
    from jarvis.integrations import voice_native_tools
    voice_native_tools.install(legacy)

    assert legacy.JarvisLive.run is run_wrapper

    async def exercise():
        result = await legacy.JarvisLive().run()
        await asyncio.sleep(0)
        return result

    assert asyncio.run(exercise()) == "run-result"
    assert started.is_set()
    assert cancelled.is_set()
