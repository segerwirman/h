"""Framework maturity Phase 2 — capability descriptors gate exposure."""
from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _restore_global_capability_registry():
    """Capability unit tests may replace the global registry, never leak it."""
    from jarvis.agent.capabilities import REGISTRY

    original = dict(REGISTRY._items)
    yield
    REGISTRY._items.clear()
    REGISTRY._items.update(original)


def test_registry_hanya_mengekspos_capability_enabled_dan_policy_allowed():
    from jarvis.agent.capabilities import CapabilityDescriptor, CapabilityRegistry
    from jarvis.agent.execution_context import ExecutionContext

    registry = CapabilityRegistry()
    registry.register(CapabilityDescriptor(
        id="files.write", tool_name="write_file", toolset="files_write",
        risk="high", timeout_s=30,
    ))
    remote = ExecutionContext.create(
        source="telegram", actor_id="remote", session_id="s", surface="remote",
        toolsets={"messaging"},
    )

    assert registry.exposed_tool_names(remote) == []


def test_registry_menampilkan_safe_tool_yang_enabled():
    from jarvis.agent.capabilities import CapabilityDescriptor, CapabilityRegistry
    from jarvis.agent.execution_context import ExecutionContext

    registry = CapabilityRegistry()
    registry.register(CapabilityDescriptor(
        id="status.read", tool_name="status", toolset="safe", risk="low", timeout_s=5,
    ))
    local = ExecutionContext.create(
        source="desktop", actor_id="local", session_id="s", surface="desktop",
        toolsets={"safe"},
    )

    assert registry.exposed_tool_names(local) == ["status"]


def test_approval_store_persist_approved_state(tmp_path):
    from jarvis.agent.approval import ApprovalStore

    store = ApprovalStore(tmp_path / "approvals.sqlite")
    request = store.request("trace-1", "files.write", "approval_required")
    assert store.get(request.id).state == "pending"
    assert store.resolve(request.id, approved=True).state == "approved"
    assert store.get(request.id).state == "approved"
    assert "trace-1" not in repr(store.get(request.id).safe_dict())


def test_registry_schemas_context_hanya_memuat_capability_terekspos(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.capabilities import CapabilityDescriptor, REGISTRY
    from jarvis.agent.execution_context import ExecutionContext

    REGISTRY._items.clear()
    REGISTRY.register(CapabilityDescriptor(
        id="status.read", tool_name="status", toolset="safe", risk="low", timeout_s=5,
    ))
    monkeypatch.setattr(registry, "all_tools", lambda: {})
    context = ExecutionContext.create(
        source="desktop", actor_id="local", session_id="s", surface="desktop",
        toolsets={"safe"},
    )

    assert registry.schemas(context=context) == []


def test_tool_execute_menolak_capability_high_risk_sebelum_tool_run(monkeypatch):
    import asyncio
    from jarvis.agent import registry
    from jarvis.agent.base import Tool
    from jarvis.agent.capabilities import CapabilityDescriptor, REGISTRY
    from jarvis.agent.execution_context import ExecutionContext

    class Dangerous(Tool):
        name = "dangerous"
        description = "test"
        timeout_s = 1

        async def run(self, **_):
            raise AssertionError("must not run before approval")

    REGISTRY._items.clear()
    REGISTRY.register(CapabilityDescriptor(
        id="files.write", tool_name="dangerous", toolset="files_write",
        risk="high", timeout_s=5,
    ))
    monkeypatch.setattr(registry, "get", lambda _name: Dangerous())
    context = ExecutionContext.create(
        source="desktop", actor_id="local", session_id="s", surface="desktop",
        toolsets={"files_write"},
    )

    result = asyncio.run(registry.execute("dangerous", {}, context=context))

    assert result.ok is False
    assert "approval" in result.error.lower()


def test_approval_yang_disetujui_melanjutkan_tool_dari_memori_saja(monkeypatch, tmp_path):
    import asyncio
    import re
    from jarvis.agent import registry
    from jarvis.agent.approval import ApprovalStore
    from jarvis.agent.base import Tool, ToolResult
    from jarvis.agent.capabilities import CapabilityDescriptor, REGISTRY
    from jarvis.agent.execution_context import ExecutionContext
    from jarvis.agent import paths

    class Dangerous(Tool):
        name = "dangerous_continuation"
        description = "test"
        timeout_s = 1
        requires_confirmation = True

        def __init__(self):
            self.calls = []

        async def run(self, **args):
            self.calls.append(dict(args))
            return ToolResult.success("dijalankan")

    from jarvis.agent import approval_continuations
    approval_continuations.clear()
    monkeypatch.setattr(paths, "data_dir", lambda: tmp_path)
    tool = Dangerous()
    REGISTRY._items.clear()
    REGISTRY.register(CapabilityDescriptor(
        id="files.write", tool_name=tool.name, toolset="files_write",
        risk="high", timeout_s=5,
    ))
    monkeypatch.setattr(registry, "get", lambda _name: tool)
    context = ExecutionContext.create(
        source="desktop", actor_id="local", session_id="session-a", surface="desktop",
        toolsets={"files_write"},
    )

    blocked = asyncio.run(registry.execute(tool.name, {"path": "private.txt"}, context=context))
    request_id = re.search(r"\(([0-9a-f]+)\)", blocked.error or "").group(1)
    store = ApprovalStore(tmp_path / "approvals.sqlite")
    assert tool.calls == [] and store.get(request_id).state == "pending"

    store.resolve(request_id, approved=True)
    resumed = asyncio.run(approval_continuations.resume(request_id))

    assert resumed.ok is True
    assert tool.calls == [{"path": "private.txt"}]
    assert asyncio.run(approval_continuations.resume(request_id)).ok is False
    assert "private.txt" not in repr(store.get(request_id).safe_dict())
