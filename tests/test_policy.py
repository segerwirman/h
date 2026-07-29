"""Framework maturity Phase 1 — policy decisions are surface-aware."""
from __future__ import annotations

import importlib


def test_policy_menolak_remote_desktop_control():
    try:
        policy = importlib.import_module("jarvis.agent.policy")
    except ModuleNotFoundError as exc:
        assert exc.name == "jarvis.agent.policy"
        raise
    context = importlib.import_module("jarvis.agent.execution_context")
    remote = context.ExecutionContext.create(
        source="telegram", actor_id="a", session_id="s", surface="remote",
        toolsets={"desktop"},
    )

    result = policy.decide(remote, capability="desktop.close_window", risk="high")

    assert result.allowed is False
    assert result.needs_approval is False
    assert result.reason == "remote_surface_denied"


def test_policy_meminta_approval_untuk_file_write_desktop():
    policy = importlib.import_module("jarvis.agent.policy")
    context = importlib.import_module("jarvis.agent.execution_context")
    desktop = context.ExecutionContext.create(
        source="desktop", actor_id="local", session_id="s", surface="desktop",
        toolsets={"files_write"},
    )

    result = policy.decide(desktop, capability="files.write", risk="high")

    assert result.allowed is False
    assert result.needs_approval is True
    assert result.reason == "approval_required"


def test_policy_mengizinkan_safe_capability_dalam_toolset():
    policy = importlib.import_module("jarvis.agent.policy")
    context = importlib.import_module("jarvis.agent.execution_context")
    desktop = context.ExecutionContext.create(
        source="desktop", actor_id="local", session_id="s", surface="desktop",
        toolsets={"safe"},
    )

    result = policy.decide(desktop, capability="status.read", risk="low")

    assert result.allowed is True
    assert result.needs_approval is False
    assert result.reason == "allowed"
