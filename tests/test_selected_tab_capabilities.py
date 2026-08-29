"""Selected-tab tools stay process-local and fail closed before a share."""
from __future__ import annotations

import asyncio

import pytest


@pytest.fixture(autouse=True)
def _restore_capability_registry():
    from jarvis.agent.capabilities import REGISTRY

    original = dict(REGISTRY._items)
    yield
    REGISTRY._items.clear()
    REGISTRY._items.update(original)


def _install_selected_tab_capability(monkeypatch, *, risk: str = "low"):
    from jarvis.agent import registry
    from jarvis.agent.base import Tool, ToolResult
    from jarvis.agent.capabilities import CapabilityDescriptor, REGISTRY

    class SelectedObserve(Tool):
        name = "selected_tab_observe"
        description = "offline selected-tab fixture"
        read_only = True
        wants_context = True

        def __init__(self):
            self.calls = []

        async def run(self, **kwargs):
            self.calls.append(dict(kwargs))
            return ToolResult.success("observed")

    tool = SelectedObserve()
    REGISTRY._items.clear()
    REGISTRY.register(CapabilityDescriptor(
        id="selected_tab.observe",
        tool_name=tool.name,
        toolset="selected_tab",
        risk=risk,
        timeout_s=5,
    ))
    monkeypatch.setattr(registry, "all_tools", lambda refresh=False: {tool.name: tool})
    monkeypatch.setattr(registry, "get", lambda _name: tool)
    monkeypatch.setattr(registry, "fingerprint", lambda: (1, (tool.name,)))
    registry.invalidate_schema_cache()
    return tool


def _schema_names(items):
    return {item["function"]["name"] for item in items}


def _mint_overlay(monkeypatch, *, session_id="session-a", task_id="T-a"):
    from jarvis.agent import local_run_capabilities

    adapter = object()
    monkeypatch.setattr(
        local_run_capabilities,
        "_is_trusted_local_adapter",
        lambda candidate: candidate is adapter,
    )
    overlay = local_run_capabilities.mint_selected_tab_overlay(
        session_id=session_id,
        task_id=task_id,
        adapter=adapter,
    )
    return overlay, adapter


def test_selected_tab_schema_is_hidden_without_process_local_overlay(monkeypatch):
    from jarvis.agent import registry

    _install_selected_tab_capability(monkeypatch)

    assert "selected_tab_observe" not in _schema_names(registry.schemas())


def test_delegated_context_cannot_expose_selected_tab_schema(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.execution_context import ExecutionContext

    _install_selected_tab_capability(monkeypatch)
    delegated = ExecutionContext.create(
        source="delegation",
        actor_id="local",
        session_id="session-a",
        surface="browser_tab",
        toolsets={"selected_tab"},
    )

    assert "selected_tab_observe" not in _schema_names(
        registry.schemas(context=delegated)
    )


def test_matching_overlay_exposes_only_explicit_selected_tab_schema(monkeypatch):
    from jarvis.agent import registry

    _install_selected_tab_capability(monkeypatch)
    overlay, _adapter = _mint_overlay(monkeypatch)

    assert _schema_names(registry.schemas(overlay=overlay)) == {
        "selected_tab_observe"
    }


def test_overlay_names_cannot_broaden_unrelated_context_tools(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.base import Tool
    from jarvis.agent.capabilities import CapabilityDescriptor, REGISTRY
    from jarvis.agent.execution_context import ExecutionContext
    from jarvis.agent.local_run_capabilities import LocalRunCapabilityOverlay

    class UnrelatedTool(Tool):
        name = "unrelated_writer"
        description = "offline unrelated fixture"

        async def run(self, **_kwargs):
            raise AssertionError("schema test must not execute tools")

    selected = _install_selected_tab_capability(monkeypatch)
    unrelated = UnrelatedTool()
    REGISTRY.register(CapabilityDescriptor(
        id="files.unrelated_writer",
        tool_name=unrelated.name,
        toolset="files_write",
        risk="medium",
        timeout_s=5,
    ))
    monkeypatch.setattr(
        registry,
        "all_tools",
        lambda refresh=False: {
            selected.name: selected,
            unrelated.name: unrelated,
        },
    )
    registry.invalidate_schema_cache()
    context = ExecutionContext.create(
        source="ui",
        actor_id="local",
        session_id="session-a",
        surface="browser_tab",
        toolsets={"selected_tab"},
    )
    overlay = LocalRunCapabilityOverlay(
        session_id="session-a",
        task_id="T-a",
        context=context,
        tool_names=frozenset({selected.name, unrelated.name}),
        _adapter=object(),
    )

    assert _schema_names(registry.schemas(context=context, overlay=overlay)) == {
        selected.name
    }


def test_selected_tab_execution_rejects_explicit_context_without_overlay(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.execution_context import ExecutionContext

    tool = _install_selected_tab_capability(monkeypatch)
    context = ExecutionContext.create(
        source="ui",
        actor_id="local",
        session_id="session-a",
        surface="browser_tab",
        toolsets={"selected_tab"},
    )
    session = type(
        "Session",
        (),
        {"id": "session-a", "registry_task_id": "T-a"},
    )()

    result = asyncio.run(registry.execute(
        tool.name,
        {},
        adapter=None,
        session=session,
        context=context,
    ))

    assert result.ok is False
    assert "overlay" in (result.error or "").casefold()
    assert tool.calls == []


def test_selected_tab_execution_requires_matching_overlay_binding(monkeypatch):
    from jarvis.agent import registry

    tool = _install_selected_tab_capability(monkeypatch)
    overlay, adapter = _mint_overlay(monkeypatch)
    wrong_session = type(
        "Session",
        (),
        {"id": "session-b", "registry_task_id": "T-a"},
    )()

    result = asyncio.run(registry.execute(
        tool.name,
        {},
        adapter=adapter,
        session=wrong_session,
        overlay=overlay,
    ))

    assert result.ok is False
    assert "binding" in (result.error or "").casefold()
    assert tool.calls == []


def test_matching_overlay_reaches_runtime_share_gate_and_stays_closed(monkeypatch):
    from jarvis.agent import registry

    tool = _install_selected_tab_capability(monkeypatch)
    overlay, adapter = _mint_overlay(monkeypatch)
    session = type(
        "Session",
        (),
        {"id": "session-a", "registry_task_id": "T-a"},
    )()

    result = asyncio.run(registry.execute(
        tool.name,
        {},
        adapter=adapter,
        session=session,
        overlay=overlay,
    ))

    assert result.ok is False
    assert result.error == "selected_tab_not_active"
    assert tool.calls == []


def test_loop_forwards_overlay_to_schema_and_execution(monkeypatch, tmp_path):
    from jarvis.agent import loop as agent_loop
    from jarvis.agent import model_routing
    from jarvis.agent.adapters.base import NullAdapter
    from jarvis.agent.base import ToolResult
    from jarvis.agent.llm_client import ChatResponse, ToolCall
    from jarvis.agent.session import Session

    overlay = object()
    captured = {"schemas": None, "execute": None}
    responses = [
        ChatResponse(tool_calls=[
            ToolCall(id="selected-1", name="selected_tab_observe", arguments={})
        ]),
        ChatResponse(content="done"),
    ]

    class FakeClient:
        def available(self):
            return True

        def chat(self, _messages, _tools=None, **_kwargs):
            return responses.pop(0)

    def schemas(**kwargs):
        captured["schemas"] = kwargs
        return []

    async def execute(name, args, adapter, session, context, overlay=None):
        captured["execute"] = (name, args, adapter, session, context, overlay)
        return ToolResult.success("observed")

    monkeypatch.setattr(model_routing, "heavy_resolution",
                        lambda: (FakeClient(), "fake", "offline"))
    monkeypatch.setattr(agent_loop.registry, "schemas", schemas)
    monkeypatch.setattr(agent_loop.registry, "execute", execute)
    monkeypatch.setattr(
        agent_loop.registry,
        "all_tools",
        lambda: {"selected_tab_observe": type("T", (), {"read_only": True})()},
    )
    monkeypatch.setattr(agent_loop, "reflect_async", lambda _session: None)
    monkeypatch.setattr(
        "jarvis.agent.session.db_path",
        lambda: tmp_path / "agent.sqlite",
    )
    session = Session(task="offline", adapter_name="null")

    result = asyncio.run(agent_loop.run(
        "offline",
        adapter=NullAdapter(),
        session=session,
        overlay=overlay,
    ))

    assert result.ok is True
    assert captured["schemas"]["overlay"] is overlay
    assert captured["execute"][-1] is overlay


def test_dispatch_mints_overlay_after_real_registry_binding(monkeypatch):
    import threading

    from jarvis.agent import dispatch
    from jarvis.agent.adapters.base import Adapter
    from jarvis.agent.loop import RunResult

    class LocalAdapter(Adapter):
        name = "ui"
        source = "typed"

        def __init__(self):
            self.task_id = ""

        def scoped(self, *, task_id, source=None):
            scoped = LocalAdapter()
            scoped.task_id = task_id
            return scoped

        async def send(self, _content, **_kwargs):
            return None

        async def progress(self, _text):
            return None

    class Task:
        def __init__(self):
            self.id = "T-real"
            self.title = "offline"
            self.cancel = threading.Event()

    class Registry:
        def __init__(self):
            self.task = Task()

        def submit(self, *_args, **_kwargs):
            return self.task

        def update(self, *_args, **_kwargs):
            return None

        def acquire_slot(self, _task):
            return True

        def mark_running(self, _task_id):
            return None

        def release_slot(self, _task):
            return None

        def finish(self, *_args, **_kwargs):
            return None

    registry = Registry()
    captured = {}
    done = threading.Event()

    def mint(*, session_id, task_id, adapter):
        assert session_id
        assert task_id == "T-real"
        assert adapter.task_id == "T-real"
        captured["mint"] = (session_id, task_id, adapter)
        return "overlay-real"

    async def run(_task, **kwargs):
        captured["run"] = kwargs
        return RunResult(ok=True, text="done", session_id=kwargs["session"].id)

    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr("jarvis.agent.tasks.REGISTRY", registry)
    monkeypatch.setattr("jarvis.agent.loop.run", run)
    monkeypatch.setattr(
        "jarvis.agent.local_run_capabilities.mint_selected_tab_overlay",
        mint,
    )
    monkeypatch.setattr(dispatch, "_learn_command", lambda *_args: None)
    monkeypatch.setattr(dispatch, "_learn_plan", lambda *_args: None)

    task = dispatch.dispatch_task(
        "offline selected tab",
        adapter=LocalAdapter(),
        on_done=lambda _text: done.set(),
    )

    assert task is registry.task
    assert done.wait(2)
    assert captured["run"]["overlay"] == "overlay-real"
    session = captured["run"]["session"]
    assert session.registry_task_id == "T-real"
    assert captured["mint"][0] == session.id


def test_execution_context_child_drops_selected_tab_authority():
    from jarvis.agent.execution_context import ExecutionContext

    parent = ExecutionContext.create(
        source="ui",
        actor_id="local",
        session_id="session-a",
        surface="browser_tab",
        toolsets={"agent", "desktop_safe", "selected_tab"},
    )

    child = parent.for_child()

    assert child.source == "delegation"
    assert "desktop_safe" not in child.toolsets
    assert "selected_tab" not in child.toolsets
