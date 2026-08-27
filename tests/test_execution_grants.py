"""Checkpoint B — capability eligibility and process-local grants."""
from __future__ import annotations

from dataclasses import fields
from types import SimpleNamespace

import pytest


EXPLICIT_DIRECT_IDS = {
    "web.web_search",
    "web.web_extract",
    "web.yt_search_data",
    "web.yt_video_info",
    "web.yt_trending",
    "memory.memory_search",
    "gws_read.gmail_safe_summary",
    "gws_read.gcal_safe_agenda",
    "gws_read.morning_briefing",
}


def test_direct_grant_catalog_is_exact_low_risk_allowlist():
    from jarvis.agent.capabilities import REGISTRY

    eligible = {
        item.id for item in REGISTRY.descriptors() if item.direct_grant
    }
    assert eligible == EXPLICIT_DIRECT_IDS
    assert all(
        item.risk == "low"
        for item in REGISTRY.descriptors()
        if item.direct_grant
    )


def test_synthesized_local_descriptors_fail_closed(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.capabilities import CapabilityRegistry

    class ReadOnlyTool:
        name = "synthetic_read"
        read_only = True
        timeout_s = 3

    monkeypatch.setattr(
        registry, "all_tools", lambda: {"synthetic_read": ReadOnlyTool()},
    )
    descriptors = CapabilityRegistry().descriptors()

    assert len(descriptors) == 1
    assert descriptors[0].id.endswith(".synthetic_read")
    assert descriptors[0].risk == "low"
    assert descriptors[0].direct_grant is False


def test_unknown_capability_cannot_opt_into_direct_grant():
    from jarvis.agent.capabilities import (
        CapabilityDescriptor,
        CapabilityRegistry,
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="not allowlisted"):
        registry.register(CapabilityDescriptor(
            "files.read", "read_file", "files_read", "low", 10,
            direct_grant=True,
        ))


def test_high_risk_capability_cannot_opt_into_direct_grant():
    from jarvis.agent.capabilities import (
        CapabilityDescriptor,
        CapabilityRegistry,
    )

    registry = CapabilityRegistry()
    with pytest.raises(ValueError, match="requires low risk"):
        registry.register(CapabilityDescriptor(
            "web.web_search", "web_search", "web", "high", 10,
            direct_grant=True,
        ))


def test_policy_denial_prevents_direct_grant_registration(monkeypatch):
    from jarvis.agent import capabilities

    monkeypatch.setattr(
        capabilities.policy,
        "decide",
        lambda *_args, **_kwargs: SimpleNamespace(
            allowed=False, needs_approval=False),
    )
    with pytest.raises(ValueError, match="policy denied"):
        capabilities.CapabilityRegistry().register(
            capabilities.CapabilityDescriptor(
                "web.web_search", "web_search", "web", "low", 10,
                direct_grant=True,
            )
        )


class _Clock:
    def __init__(self, value: float = 100.0) -> None:
        self.value = value

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


def _issue(manager, *, purpose="direct_execution", task_id="T-real",
           trace_id="trace-real", capabilities=("web.web_search",),
           ttl_s=30.0, uses=1, generation=0):
    return manager.issue(
        purpose=purpose,
        task_id=task_id,
        trace_id=trace_id,
        capability_ids=capabilities,
        ttl_s=ttl_s,
        uses=uses,
        generation=generation,
    )


def test_grant_verifies_only_exact_scope_and_consumes_atomically():
    from jarvis.agent.execution_grants import (
        ExecutionGrantManager,
        PURPOSE_DIRECT_EXECUTION,
    )

    manager = ExecutionGrantManager(now_fn=_Clock())
    grant = _issue(manager, uses=2, generation=7)
    common = dict(
        purpose=PURPOSE_DIRECT_EXECUTION,
        task_id="T-real",
        trace_id="trace-real",
        capability_id="web.web_search",
        generation=7,
    )

    for key, wrong in (
        ("purpose", "communication_override"),
        ("task_id", "T-other"),
        ("trace_id", "trace-other"),
        ("capability_id", "web.web_extract"),
        ("generation", 8),
    ):
        candidate = dict(common)
        candidate[key] = wrong
        assert manager.verify(grant.id, **candidate) is False
        assert manager.get(grant.id).uses_left == 2

    assert manager.verify(grant.id, **common) is True
    assert manager.get(grant.id).uses_left == 1
    assert manager.verify(grant.id, **common) is True
    assert manager.verify(grant.id, **common) is False


def test_wrong_purpose_never_satisfies_direct_execution():
    from jarvis.agent.execution_grants import (
        ExecutionGrantManager,
        PURPOSE_COMMUNICATION_OVERRIDE,
        PURPOSE_DIRECT_EXECUTION,
    )

    manager = ExecutionGrantManager(now_fn=_Clock())
    grant = _issue(manager, purpose=PURPOSE_COMMUNICATION_OVERRIDE)

    assert manager.verify(
        grant.id,
        purpose=PURPOSE_DIRECT_EXECUTION,
        task_id="T-real",
        trace_id="trace-real",
        capability_id="web.web_search",
        generation=0,
    ) is False
    assert manager.get(grant.id).uses_left == 1


def test_grant_expiry_and_explicit_revocation_fail_closed():
    from jarvis.agent.execution_grants import (
        ExecutionGrantManager,
        PURPOSE_DIRECT_EXECUTION,
    )

    clock = _Clock()
    manager = ExecutionGrantManager(now_fn=clock)
    expired = _issue(manager, ttl_s=5)
    clock.advance(5)
    assert manager.verify(
        expired.id,
        purpose=PURPOSE_DIRECT_EXECUTION,
        task_id="T-real",
        trace_id="trace-real",
        capability_id="web.web_search",
        generation=0,
    ) is False
    assert manager.get(expired.id) is None

    revoked = _issue(manager)
    assert manager.revoke(revoked.id) is True
    assert manager.revoke(revoked.id) is False
    assert manager.get(revoked.id) is None


def test_task_and_generation_revocation_are_scoped():
    from jarvis.agent.execution_grants import (
        ExecutionGrantManager,
        PURPOSE_COMMUNICATION_OVERRIDE,
        PURPOSE_DIRECT_EXECUTION,
    )

    manager = ExecutionGrantManager(now_fn=_Clock())
    task_a = _issue(manager, task_id="T-a", generation=4)
    task_b = _issue(manager, task_id="T-b", generation=4)
    comm = _issue(
        manager,
        purpose=PURPOSE_COMMUNICATION_OVERRIDE,
        task_id="T-c",
        generation=4,
    )

    assert manager.revoke_task("T-a") == 1
    assert manager.get(task_a.id) is None
    assert manager.get(task_b.id) is not None
    assert manager.revoke_generation(
        4, purpose=PURPOSE_DIRECT_EXECUTION,
    ) == 1
    assert manager.get(task_b.id) is None
    assert manager.get(comm.id) is not None


def test_grant_store_is_bounded_and_prunes_expired_entries():
    from jarvis.agent.execution_grants import ExecutionGrantManager

    clock = _Clock()
    manager = ExecutionGrantManager(now_fn=clock, max_grants=1)
    _issue(manager, ttl_s=2)
    with pytest.raises(RuntimeError, match="store full"):
        _issue(manager, task_id="T-second")

    clock.advance(2)
    replacement = _issue(manager, task_id="T-second")
    assert manager.get(replacement.id) is not None
    assert len(manager) == 1


@pytest.mark.parametrize("ttl_s", [0, -1, float("inf"), float("nan")])
def test_invalid_grant_ttl_is_rejected(ttl_s):
    from jarvis.agent.execution_grants import ExecutionGrantManager

    with pytest.raises(ValueError, match="ttl and uses"):
        _issue(ExecutionGrantManager(), ttl_s=ttl_s)


def test_grant_object_contains_scope_identifiers_only():
    from jarvis.agent.execution_grants import Grant

    assert {item.name for item in fields(Grant)} == {
        "id",
        "purpose",
        "task_id",
        "trace_id",
        "capability_ids",
        "expires_at",
        "uses_left",
        "generation",
    }
    prohibited = {
        "passphrase", "password", "secret", "args", "arguments",
        "continuation", "prompt", "content",
    }
    assert prohibited.isdisjoint({item.name for item in fields(Grant)})


def _isolate_dispatch(monkeypatch):
    from jarvis.agent import dispatch, policy
    from jarvis.agent.execution_grants import MANAGER
    from jarvis.agent.tasks import REGISTRY

    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(
        policy,
        "decide",
        lambda *_args, **_kwargs: SimpleNamespace(
            allowed=True, needs_approval=False, reason="offline_test",
        ),
    )
    monkeypatch.setattr(dispatch.BUS, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch.threading, "Thread", _HeldThread)
    REGISTRY.clear()
    MANAGER.clear()
    with dispatch._active_lock:
        dispatch._active.clear()
    return dispatch, REGISTRY, MANAGER


class _HeldThread:
    """Capture a worker target without running it."""

    targets = []

    def __init__(self, *, target, **_kwargs) -> None:
        self._target = target

    def start(self) -> None:
        self.targets.append(self._target)


def test_dispatch_grant_binds_real_submitted_task_id(monkeypatch):
    from jarvis.agent.execution_context import ExecutionContext

    _HeldThread.targets.clear()
    dispatch, registry, manager = _isolate_dispatch(monkeypatch)
    context = ExecutionContext.create(
        source="typed",
        actor_id="local",
        session_id="grant-binding",
        surface="desktop",
        toolsets={"agent", "web"},
    )

    task = dispatch.dispatch_task(
        "cari dokumentasi resmi",
        context=context,
        direct_grant_capability_ids={"web.web_search"},
    )

    assert task is not None
    with dispatch._active_lock:
        handle = next(iter(dispatch._active.values()))
    grant = manager.get(handle.session.execution_grant_id)
    assert handle.bg_task is task
    assert grant is not None
    assert grant.task_id == task.id
    assert grant.trace_id == context.trace_id
    assert grant.capability_ids == frozenset({"web.web_search"})

    assert dispatch.cancel_task(task.id) is True
    assert manager.get(grant.id) is None
    assert handle.session.execution_grant_id == ""
    with dispatch._active_lock:
        dispatch._active.clear()
    registry.clear()


def test_cancel_all_revokes_every_bound_grant(monkeypatch):
    from jarvis.agent.execution_context import ExecutionContext

    _HeldThread.targets.clear()
    dispatch, registry, manager = _isolate_dispatch(monkeypatch)
    contexts = [
        ExecutionContext.create(
            source="typed",
            actor_id="local",
            session_id=f"grant-all-{index}",
            surface="desktop",
            toolsets={"agent", "web"},
        )
        for index in range(2)
    ]
    tasks = [
        dispatch.dispatch_task(
            f"cari dokumentasi {index}",
            context=context,
            direct_grant_capability_ids={"web.web_search"},
        )
        for index, context in enumerate(contexts)
    ]

    assert all(task is not None for task in tasks)
    assert len(manager) == 2
    assert dispatch.cancel_all() == 2
    assert len(manager) == 0
    with dispatch._active_lock:
        assert all(
            handle.session.execution_grant_id == ""
            for handle in dispatch._active.values()
        )
        dispatch._active.clear()
    registry.clear()


def test_grant_issue_failure_finishes_submitted_task_and_cleans_handle(
        monkeypatch):
    from jarvis.agent.execution_context import ExecutionContext

    _HeldThread.targets.clear()
    dispatch, registry, manager = _isolate_dispatch(monkeypatch)
    context = ExecutionContext.create(
        source="typed",
        actor_id="local",
        session_id="grant-failure",
        surface="desktop",
        toolsets={"agent", "web"},
    )

    def fail_issue(**_kwargs):
        raise RuntimeError("store unavailable")

    monkeypatch.setattr(manager, "issue", fail_issue)
    result = dispatch.dispatch_task(
        "cari dokumentasi gagal",
        context=context,
        direct_grant_capability_ids={"web.web_search"},
    )

    assert result is None
    snapshot = registry.snapshot()
    assert len(snapshot) == 1
    assert snapshot[0].status.value == "failed"
    assert snapshot[0].error == "direct grant unavailable"
    assert dispatch.active_count() == 0
    assert len(manager) == 0
    assert _HeldThread.targets == []
    registry.clear()
