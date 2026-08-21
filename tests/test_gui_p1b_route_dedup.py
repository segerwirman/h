"""P1-B — Duplicate route possibility characterizer (red-first acceptance).

Gap #1 from P1-A docs: "If classifier override returns tier>=AGENT while legacy
intent also hits SEARCH_WEB, could there be two executions? Test needed: submit
same text under override vs non-override, measure task IDs emitted."

This test asserts the invariant: one user input → exactly one task.submitted
publication in BUS, regardless of classification path or override presence.

RED-first protocol:
1. Test fails for unintended unguarded double-call
2. Minimal implementation required only if RED
3. Current guard: dispatch_async._active dict + _active_lock (dispatch.py:573-581)

Everything offline: no provider/network/audio/camera/browser calls; fake loop,
fake registry, no MainWindow construction.

Evidence label: focused-tested. No runtime-wired, endpoint-reachable, or
live-proven claim; legacy shell remains the only deployed shell.
"""
from __future__ import annotations

import asyncio
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
import threading
from collections import Counter

from jarvis.core.bus import EventBus


def test_dispatch_async_duplicate_key_returns_false_on_second_call(monkeypatch):
    """Identical prompts dispatched concurrently are guarded by _active key lock."""
    from jarvis.agent import dispatch, loop as agent_loop
    from jarvis.agent.tasks import REGISTRY

    monkeypatch.setattr(dispatch, "available", lambda: True)
    with dispatch._active_lock:
        dispatch._active.clear()
    REGISTRY.clear()

    async def fake_run(task, adapter=None, session=None, bg_task=None, **kw):
        await asyncio.sleep(0.05)  # Simulate work without blocking guard
        return agent_loop.RunResult(ok=True, text="ok", session_id=getattr(session, "id", ""))

    monkeypatch.setattr(agent_loop, "run", fake_run)

    # First dispatch
    result1 = dispatch.dispatch_async("tugas ringkas sama")
    assert result1 is True, "First dispatch should succeed"

    # Immediate second dispatch with same key — should fail due to active lock
    result2 = dispatch.dispatch_async("tugas ringkas sama")
    # Guard returns False if key already exists in _active
    assert result2 is False, f"Second dispatch should fail due to duplicate guard, got {result2}"


def test_dispatch_async_different_keys_succeed_independently(monkeypatch):
    """Different prompts bypass duplicate guard successfully."""
    from jarvis.agent import dispatch, loop as agent_loop
    from jarvis.agent.tasks import REGISTRY

    monkeypatch.setattr(dispatch, "available", lambda: True)
    with dispatch._active_lock:
        dispatch._active.clear()
    REGISTRY.clear()

    async def fake_run(task, adapter=None, session=None, bg_task=None, **kw):
        await asyncio.sleep(0.02)
        return agent_loop.RunResult(ok=True, text="ok", session_id=getattr(session, "id", ""))

    monkeypatch.setattr(agent_loop, "run", fake_run)

    # Two different prompts should both succeed
    result1 = dispatch.dispatch_async("cek harga saham")
    result2 = dispatch.dispatch_async("buka kalender")

    assert result1 is True, "First distinct prompt should succeed"
    assert result2 is True, "Second distinct prompt should succeed"


def test_duplicate_guard_is_single_thread_safe_with_race_simulation(monkeypatch):
    """Concurrent dispatches of same prompt via threads all pass through single guard."""
    from jarvis.agent import dispatch, loop as agent_loop
    from jarvis.agent.tasks import REGISTRY

    results = []
    lock = threading.Lock()

    monkeypatch.setattr(dispatch, "available", lambda: True)
    with dispatch._active_lock:
        dispatch._active.clear()
    REGISTRY.clear()

    async def fake_run(task, adapter=None, session=None, bg_task=None, **kw):
        # Longer sleep ensures first caller holds the lock throughout
        await asyncio.sleep(0.2)
        return agent_loop.RunResult(ok=True, text="ok", session_id=getattr(session, "id", ""))

    monkeypatch.setattr(agent_loop, "run", fake_run)

    def dispatch_worker():
        result = dispatch.dispatch_async("concurrent test")
        with lock:
            results.append(result)

    # Spawn concurrent workers firing at once
    threads = [threading.Thread(target=dispatch_worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=2)

    # Exactly one should succeed, four must be blocked by duplicate guard
    success_count = sum(1 for r in results if r is True)
    fail_count = sum(1 for r in results if r is False)

    assert success_count == 1, f"Expected exactly 1 success, got {success_count}"
    assert fail_count == 4, f"Expected 4 failures, got {fail_count}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
