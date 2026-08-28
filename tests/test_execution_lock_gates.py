"""Task 9 — communication lock at dispatch and canonical tool execution."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from jarvis.agent.base import Tool, ToolResult
from jarvis.agent.capabilities import CapabilityDescriptor
from jarvis.agent.execution_context import ExecutionContext
from jarvis.agent.session import Session


class _Tool(Tool):
    name = "work"
    description = "fake executable work"
    timeout_s = 5

    def __init__(self, *, confirm=False) -> None:
        self.requires_confirmation = confirm
        self.runs = 0

    async def run(self, **_kwargs):
        self.runs += 1
        return ToolResult.success("done")


class _HeldThread:
    """Capture one dispatch worker without starting it."""

    targets = []

    def __init__(self, *, target, **_kwargs) -> None:
        self._target = target

    def start(self) -> None:
        self.targets.append(self._target)


class _Adapter:
    name = "test"
    interactive = True

    def __init__(self, answer="Lanjut", before_answer=None) -> None:
        self.answer = answer
        self.before_answer = before_answer
        self.asks = 0

    async def ask(self, *_args, **_kwargs):
        self.asks += 1
        if self.before_answer is not None:
            self.before_answer()
        return self.answer


@pytest.fixture(autouse=True)
def _reset_mode_and_grants():
    from jarvis.agent import communication_mode, dispatch
    from jarvis.agent.execution_grants import MANAGER
    from jarvis.agent.tasks import REGISTRY

    previous = communication_mode.MODE
    communication_mode.MODE = communication_mode.CommunicationMode()
    MANAGER.clear()
    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()
    _HeldThread.targets.clear()
    yield
    communication_mode.MODE.exit()
    MANAGER.clear()
    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()
    communication_mode.MODE = previous


def _install_tool(monkeypatch, tool, descriptor):
    from jarvis.agent import capabilities, registry

    monkeypatch.setattr(registry, "_tools", {tool.name: tool})
    monkeypatch.setattr(
        capabilities.REGISTRY,
        "descriptor_for_tool",
        lambda name: descriptor if name == tool.name else None,
    )
    return registry


def _context(trace="trace-123"):
    return ExecutionContext(
        source="typed",
        actor_id="local",
        session_id="execution-lock",
        surface="desktop",
        toolsets=frozenset({"local"}),
        trace_id=trace,
        secrets={},
    )


def _session(*, task_id="T-real", grant_id="", direct_grant_id=""):
    session = Session(task="fake")
    session.registry_task_id = task_id
    session.communication_grant_id = grant_id
    session.execution_grant_id = direct_grant_id
    return session


def test_dispatch_lock_refuses_before_registry_submit(monkeypatch):
    from jarvis.agent import communication_mode, dispatch
    from jarvis.agent import tasks

    calls = []
    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(tasks.REGISTRY, "submit", lambda *_a, **_k: calls.append("submit"))
    communication_mode.enter()

    result = dispatch.dispatch_task("do executable work")

    assert result is None
    assert calls == []
    assert dispatch.active_count() == 0


def _live_dispatch_handle(monkeypatch, *, trace="trace-123"):
    from jarvis.agent import communication_mode, dispatch, policy

    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(dispatch.threading, "Thread", _HeldThread)
    monkeypatch.setattr(dispatch.BUS, "publish", lambda *_a, **_k: None)
    monkeypatch.setattr(
        policy,
        "decide",
        lambda *_a, **_k: SimpleNamespace(
            allowed=True,
            needs_approval=False,
            reason="offline_test",
        ),
    )
    task = dispatch.dispatch_task("live task before communication lock", context=_context(trace))
    assert task is not None
    with dispatch._active_lock:
        handle = next(iter(dispatch._active.values()))
    generation = communication_mode.enter()
    return dispatch, task, handle, generation


def test_live_scope_comes_only_from_matching_active_session(monkeypatch):
    dispatch, task, handle, _generation = _live_dispatch_handle(monkeypatch)

    scope = dispatch.communication_authorization_scope(
        task.id,
        {"local.test.work"},
        ttl_s=45,
        uses=2,
    )

    assert scope is not None
    assert scope.task_id == task.id
    assert scope.trace_id == "trace-123"
    assert scope.capability_ids == frozenset({"local.test.work"})
    assert scope.ttl_s == 45
    assert scope.uses == 2
    assert dispatch.communication_authorization_scope(
        "T-missing", {"local.test.work"}
    ) is None

    handle.cancel()
    assert dispatch.communication_authorization_scope(
        task.id, {"local.test.work"}
    ) is None


def test_binding_attaches_exact_validated_override_to_live_session(monkeypatch):
    from jarvis.agent import communication_mode
    from jarvis.agent.execution_grants import MANAGER, PURPOSE_COMMUNICATION_OVERRIDE

    dispatch, task, handle, generation = _live_dispatch_handle(monkeypatch)
    grant = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id=task.id,
        trace_id="trace-123",
        capability_ids={"local.test.work"},
        ttl_s=30,
        uses=1,
        generation=generation,
    )

    assert dispatch.bind_communication_grant(
        grant.id,
        task_id=task.id,
        trace_id="trace-123",
        capability_ids={"local.test.work"},
    ) is True
    assert handle.session.communication_grant_id == grant.id
    assert MANAGER.get(grant.id) is not None

    communication_mode.exit()


def test_binding_rejects_and_revokes_scope_mismatch_or_terminal_task(monkeypatch):
    from jarvis.agent.execution_grants import MANAGER, PURPOSE_COMMUNICATION_OVERRIDE
    from jarvis.agent.tasks import REGISTRY

    dispatch, task, handle, generation = _live_dispatch_handle(monkeypatch)
    mismatch = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id=task.id,
        trace_id="trace-123",
        capability_ids={"local.test.work"},
        ttl_s=30,
        uses=1,
        generation=generation,
    )
    assert dispatch.bind_communication_grant(
        mismatch.id,
        task_id=task.id,
        trace_id="trace-other",
        capability_ids={"local.test.work"},
    ) is False
    assert MANAGER.get(mismatch.id) is None
    assert handle.session.communication_grant_id == ""

    terminal = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id=task.id,
        trace_id="trace-123",
        capability_ids={"local.test.work"},
        ttl_s=30,
        uses=1,
        generation=generation,
    )
    REGISTRY.finish(task.id, result="done")
    assert dispatch.bind_communication_grant(
        terminal.id,
        task_id=task.id,
        trace_id="trace-123",
        capability_ids={"local.test.work"},
    ) is False
    assert MANAGER.get(terminal.id) is None


def test_cancel_clears_and_revokes_bound_communication_grant(monkeypatch):
    from jarvis.agent.execution_grants import MANAGER, PURPOSE_COMMUNICATION_OVERRIDE

    dispatch, task, handle, generation = _live_dispatch_handle(monkeypatch)
    grant = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id=task.id,
        trace_id="trace-123",
        capability_ids={"local.test.work"},
        ttl_s=30,
        uses=1,
        generation=generation,
    )
    assert dispatch.bind_communication_grant(
        grant.id,
        task_id=task.id,
        trace_id="trace-123",
        capability_ids={"local.test.work"},
    ) is True

    assert dispatch.cancel_task(task.id) is True
    assert handle.session.communication_grant_id == ""
    assert handle.session.registry_task_id == ""
    assert MANAGER.get(grant.id) is None


def test_binding_api_accepts_identifiers_only():
    import inspect
    from jarvis.agent import dispatch

    assert set(inspect.signature(dispatch.bind_communication_grant).parameters) == {
        "grant_id",
        "task_id",
        "trace_id",
        "capability_ids",
    }
    assert set(
        inspect.signature(dispatch.request_communication_authorization).parameters
    ) == {
        "task_id",
        "capability_ids",
        "ttl_s",
        "uses",
    }


def test_authorization_request_bus_contains_scope_metadata_only(monkeypatch):
    dispatch, task, _handle, _generation = _live_dispatch_handle(monkeypatch)
    events = []
    monkeypatch.setattr(
        dispatch.BUS,
        "publish",
        lambda topic, **data: events.append((topic, data)),
    )

    assert dispatch.request_communication_authorization(
        task.id,
        {"local.test.work"},
        ttl_s=45,
        uses=1,
    ) is True
    assert events == [(
        "communication.authorization.required",
        {
            "task_id": task.id,
            "capability_ids": ["local.test.work"],
            "ttl_s": 45.0,
            "uses": 1,
        },
    )]
    combined = repr(events).casefold()
    assert "passphrase" not in combined
    assert "password" not in combined
    assert "secret" not in combined
    assert "trace-123" not in combined


def test_registry_lock_requests_local_auth_without_policy_side_effects(monkeypatch):
    from jarvis.agent import communication_mode, policy, registry

    tool = _Tool(confirm=True)
    descriptor = CapabilityDescriptor(
        "local.test.work", "work", "local", "high", 5,
    )
    _install_tool(monkeypatch, tool, descriptor)
    requests = []
    monkeypatch.setattr(
        registry,
        "_is_active_native_desktop_adapter",
        lambda _adapter: True,
    )
    monkeypatch.setattr(
        "jarvis.agent.dispatch.request_communication_authorization",
        lambda task_id, capability_ids: requests.append(
            (task_id, frozenset(capability_ids))
        ) or True,
    )
    decisions = []
    monkeypatch.setattr(
        policy,
        "decide",
        lambda *_a, **_k: decisions.append("policy") or SimpleNamespace(
            allowed=True,
            needs_approval=True,
            reason="high_risk",
        ),
    )
    communication_mode.enter()

    result = asyncio.run(registry.execute(
        "work", {}, adapter=_Adapter(), session=_session(), context=_context(),
    ))

    assert result.ok is False
    assert "otorisasi lokal diminta" in result.error
    assert requests == [("T-real", frozenset({"local.test.work"}))]
    assert decisions == []
    assert tool.runs == 0


def test_registry_lock_precedes_policy_and_approval_side_effects(monkeypatch):
    from jarvis.agent import communication_mode, policy

    tool = _Tool(confirm=True)
    descriptor = CapabilityDescriptor(
        "local.test.work", "work", "local", "high", 5,
    )
    registry = _install_tool(monkeypatch, tool, descriptor)
    decisions = []
    monkeypatch.setattr(
        policy,
        "decide",
        lambda *_a, **_k: decisions.append("policy") or SimpleNamespace(
            allowed=True,
            needs_approval=True,
            reason="high_risk",
        ),
    )
    communication_mode.enter()

    result = asyncio.run(registry.execute(
        "work", {}, adapter=_Adapter(), session=_session(), context=_context(),
    ))

    assert result.ok is False
    assert "dikunci" in result.error
    assert decisions == []
    assert tool.runs == 0


def test_exact_escape_id_runs_while_lock_is_active(monkeypatch):
    from jarvis.agent import communication_mode

    tool = _Tool()
    tool.name = "task_cancel"
    descriptor = CapabilityDescriptor(
        "local.task_tools.task_cancel", "task_cancel", "local", "medium", 5,
    )
    registry = _install_tool(monkeypatch, tool, descriptor)
    communication_mode.enter()

    result = asyncio.run(registry.execute("task_cancel", {}))

    assert result.ok is True
    assert tool.runs == 1


def test_override_unlocks_exact_scope_and_consumes_one_use(monkeypatch):
    from jarvis.agent import communication_mode, policy
    from jarvis.agent.execution_grants import MANAGER, PURPOSE_COMMUNICATION_OVERRIDE

    tool = _Tool()
    descriptor = CapabilityDescriptor(
        "local.test.work", "work", "local", "medium", 5,
    )
    registry = _install_tool(monkeypatch, tool, descriptor)
    monkeypatch.setattr(
        policy,
        "decide",
        lambda *_a, **_k: SimpleNamespace(
            allowed=True, needs_approval=False, reason="offline_test",
        ),
    )
    generation = communication_mode.enter()
    grant = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id="T-real",
        trace_id="trace-123",
        capability_ids={descriptor.id},
        ttl_s=30,
        uses=1,
        generation=generation,
    )
    session = _session(grant_id=grant.id)

    first = asyncio.run(registry.execute(
        "work", {}, session=session, context=_context(),
    ))
    second = asyncio.run(registry.execute(
        "work", {}, session=session, context=_context(),
    ))

    assert first.ok is True
    assert second.ok is False
    assert "dikunci" in second.error
    assert tool.runs == 1
    assert MANAGER.get(grant.id) is None


@pytest.mark.parametrize("changed", ["task", "trace", "capability", "generation"])
def test_override_mismatch_fails_closed_without_consuming(monkeypatch, changed):
    from jarvis.agent import communication_mode
    from jarvis.agent.execution_grants import MANAGER, PURPOSE_COMMUNICATION_OVERRIDE

    tool = _Tool()
    descriptor = CapabilityDescriptor(
        "local.test.work", "work", "local", "medium", 5,
    )
    registry = _install_tool(monkeypatch, tool, descriptor)
    generation = communication_mode.enter()
    grant = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id="T-other" if changed == "task" else "T-real",
        trace_id="trace-other" if changed == "trace" else "trace-123",
        capability_ids={
            "local.test.other" if changed == "capability" else descriptor.id
        },
        ttl_s=30,
        uses=1,
        generation=generation + 1 if changed == "generation" else generation,
    )

    result = asyncio.run(registry.execute(
        "work", {}, session=_session(grant_id=grant.id), context=_context(),
    ))

    assert result.ok is False
    assert tool.runs == 0
    assert MANAGER.get(grant.id).uses_left == 1


def test_policy_denial_wins_and_does_not_consume_override(monkeypatch):
    from jarvis.agent import communication_mode, policy
    from jarvis.agent.execution_grants import MANAGER, PURPOSE_COMMUNICATION_OVERRIDE

    tool = _Tool()
    descriptor = CapabilityDescriptor(
        "local.test.work", "work", "local", "high", 5,
    )
    registry = _install_tool(monkeypatch, tool, descriptor)
    generation = communication_mode.enter()
    grant = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id="T-real",
        trace_id="trace-123",
        capability_ids={descriptor.id},
        ttl_s=30,
        generation=generation,
    )
    monkeypatch.setattr(
        policy,
        "decide",
        lambda *_a, **_k: SimpleNamespace(
            allowed=False, needs_approval=False, reason="hard_denial",
        ),
    )

    result = asyncio.run(registry.execute(
        "work", {}, session=_session(grant_id=grant.id), context=_context(),
    ))

    assert result.ok is False
    assert "policy menolak" in result.error
    assert tool.runs == 0
    assert MANAGER.get(grant.id).uses_left == 1


def test_generation_is_rechecked_after_confirmation_await(monkeypatch):
    from jarvis.agent import communication_mode, policy
    from jarvis.agent.execution_grants import MANAGER, PURPOSE_COMMUNICATION_OVERRIDE

    tool = _Tool(confirm=True)
    descriptor = CapabilityDescriptor(
        "local.test.work", "work", "local", "medium", 5,
    )
    registry = _install_tool(monkeypatch, tool, descriptor)
    monkeypatch.setattr(
        policy,
        "decide",
        lambda *_a, **_k: SimpleNamespace(
            allowed=True, needs_approval=False, reason="offline_test",
        ),
    )
    generation = communication_mode.enter()
    grant = MANAGER.issue(
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id="T-real",
        trace_id="trace-123",
        capability_ids={descriptor.id},
        ttl_s=30,
        generation=generation,
    )

    def rotate_generation():
        communication_mode.exit()
        communication_mode.enter()

    adapter = _Adapter(before_answer=rotate_generation)
    result = asyncio.run(registry.execute(
        "work", {}, adapter=adapter,
        session=_session(grant_id=grant.id), context=_context(),
    ))

    assert adapter.asks == 1
    assert result.ok is False
    assert "tidak valid" in result.error
    assert tool.runs == 0


def test_direct_grant_only_bypasses_confirmation_for_eligible_descriptor(monkeypatch):
    from jarvis.agent import policy
    from jarvis.agent.execution_grants import MANAGER, PURPOSE_DIRECT_EXECUTION

    tool = _Tool(confirm=True)
    eligible = CapabilityDescriptor(
        "web.web_search", "work", "web", "low", 5, direct_grant=True,
    )
    registry = _install_tool(monkeypatch, tool, eligible)
    monkeypatch.setattr(
        policy,
        "decide",
        lambda *_a, **_k: SimpleNamespace(
            allowed=True, needs_approval=False, reason="offline_test",
        ),
    )
    grant = MANAGER.issue(
        purpose=PURPOSE_DIRECT_EXECUTION,
        task_id="T-real",
        trace_id="trace-123",
        capability_ids={eligible.id},
        ttl_s=30,
        generation=0,
    )
    session = _session(direct_grant_id=grant.id)

    result = asyncio.run(registry.execute(
        "work", {}, session=session, context=_context(),
    ))

    assert result.ok is True
    assert tool.runs == 1
    assert MANAGER.get(grant.id) is None

    tool.runs = 0
    ineligible = CapabilityDescriptor(
        "local.test.work", "work", "local", "low", 5, direct_grant=False,
    )
    _install_tool(monkeypatch, tool, ineligible)
    grant = MANAGER.issue(
        purpose=PURPOSE_DIRECT_EXECUTION,
        task_id="T-real",
        trace_id="trace-123",
        capability_ids={ineligible.id},
        ttl_s=30,
        generation=0,
    )
    denied = asyncio.run(registry.execute(
        "work", {}, session=_session(direct_grant_id=grant.id), context=_context(),
    ))

    assert denied.ok is False
    assert tool.runs == 0
    assert MANAGER.get(grant.id).uses_left == 1


def test_command_plan_replay_routes_through_registry_lock(monkeypatch):
    from jarvis.agent import command_plan, communication_mode, dispatch

    tool = _Tool()
    descriptor = CapabilityDescriptor(
        "local.test.work", "work", "local", "medium", 5,
    )
    _install_tool(monkeypatch, tool, descriptor)
    forgotten = []
    monkeypatch.setattr(
        command_plan,
        "recall",
        lambda _task: [{"tool": "work", "args": {}, "display": "done"}],
    )
    monkeypatch.setattr(command_plan, "forget", lambda task: forgotten.append(task))
    communication_mode.enter()

    result = asyncio.run(dispatch._replay_plan(
        "replay work",
        adapter=_Adapter(),
        session=_session(),
        context=_context(),
        allowed=None,
    ))

    assert result is None
    assert tool.runs == 0
    assert forgotten == ["replay work"]
