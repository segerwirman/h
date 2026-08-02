"""Framework maturity Phase 1 — bounded execution identity."""
from __future__ import annotations

import asyncio
import importlib


def test_execution_context_safe_metadata_merahasiakan_actor_dan_secret():
    try:
        context = importlib.import_module("jarvis.agent.execution_context")
    except ModuleNotFoundError as exc:
        assert exc.name == "jarvis.agent.execution_context"
        raise

    item = context.ExecutionContext.create(
        source="telegram", actor_id="123456", session_id="chat-42",
        surface="remote", toolsets={"messaging"}, secrets={"token": "rahasia"},
    )
    safe = item.safe_metadata()

    assert safe["source"] == "telegram"
    assert safe["surface"] == "remote"
    assert safe["toolsets"] == ["messaging"]
    assert safe["actor_id"] != "123456"
    assert safe["session_id"] == "chat-42"
    assert len(safe["trace_id"]) >= 12
    assert "rahasia" not in repr(safe)
    assert "token" not in safe


def test_execution_context_child_mewarisi_policy_tanpa_secret():
    context = importlib.import_module("jarvis.agent.execution_context")
    parent = context.ExecutionContext.create(
        source="desktop", actor_id="local-user", session_id="s1",
        surface="desktop", toolsets={"safe", "files_read"},
        secrets={"api_key": "x"},
    )

    child = parent.for_child(toolsets={"safe"})

    assert child.source == "delegation"
    assert child.session_id == "s1"
    assert child.toolsets == frozenset({"safe"})
    assert child.trace_id != parent.trace_id
    assert child.secrets == {}




def test_execution_context_child_drops_desktop_safe_and_becomes_delegation():
    context = importlib.import_module("jarvis.agent.execution_context")
    parent = context.ExecutionContext.create(
        source="agent", actor_id="local-user", session_id="desktop-parent",
        surface="desktop", toolsets={"agent", "desktop_safe"},
    )

    child = parent.for_child()

    assert child.source == "delegation"
    assert "desktop_safe" not in child.toolsets


def test_delegate_runtime_child_schema_hides_desktop_safe(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.execution_context import ExecutionContext
    from jarvis.agent.loop import RunResult
    from jarvis.agent.session import Session
    from jarvis.agent.tools.delegate import DelegateTask

    captured = {}

    async def run(_task, **kwargs):
        captured["context"] = kwargs["context"]
        return RunResult(ok=True, text="selesai", iterations=1)

    monkeypatch.setattr(agent_loop, "run", run)
    parent_context = ExecutionContext.create(
        source="agent", actor_id="local", session_id="desktop-parent",
        surface="desktop", toolsets={"agent", "desktop_safe"},
    )
    result = asyncio.run(DelegateTask().run(
        "audit read-only", _session=Session(task="parent"), _context=parent_context,
    ))

    child = captured["context"]
    names = {item["function"]["name"] for item in registry.schemas(context=child)}
    assert result.ok is True
    assert child.source == "delegation"
    assert "desktop_safe" not in child.toolsets
    assert not {"desktop_observe", "desktop_safe_click", "desktop_safe_scroll", "desktop_safe_set_value"} & names


def test_dispatch_menolak_context_remote_tanpa_toolset_heavy(monkeypatch):
    from jarvis.agent import dispatch
    from jarvis.agent.execution_context import ExecutionContext

    context = ExecutionContext.create(
        source="telegram", actor_id="remote", session_id="s",
        surface="remote", toolsets={"messaging"},
    )
    monkeypatch.setattr(dispatch, "available", lambda: True)

    assert dispatch.dispatch_async("hapus file", context=context) is False


def test_inbound_message_membuat_context_remote_aman():
    from jarvis.gateway.base import InboundMessage

    item = InboundMessage(message_id="m", platform="telegram",
                          conversation_id="c", sender_id="user")
    safe = item.execution_context().safe_metadata()

    assert safe["source"] == "telegram"
    assert safe["surface"] == "remote"
    assert safe["actor_id"] != "user"
