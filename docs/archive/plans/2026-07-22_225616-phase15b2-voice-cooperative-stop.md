# Phase 15B.2 Voice Cooperative Stop Plan

**Goal:** Make legacy `JarvisLive.run()` exit its reconnect loop when canonical shutdown requests voice stop.

**Architecture:** Preserve legacy implementation location for compatibility. Add `JarvisLive.request_stop()` using a thread-safe `threading.Event` plus loop-local `asyncio.Event`. The reconnect loop observes stop before connecting and after a task-group interruption. `jarvis.main` supervisor invokes `request_stop` before bounded thread join.

## TDD slices

1. Test `JarvisLive` exposes idempotent `request_stop()` without network/UI side effects.
2. Test a pre-requested stop makes `run()` return before client creation.
3. Add a minimal stop watcher task that interrupts the active `TaskGroup`; ensure reconnect delay is skipped when stopping.
4. Change `_start_voice_pipeline()` to retain the created live instance through a small controller/stop callback supplied to `RuntimeSupervisor`.
5. Verify focused, full, frozen, diff.

**Constraints:** no live voice/network/UI run; no rewrite/move of root `main.py`; no force-kill; no credential inspection.

```bash
unset PYTHONPATH; python -m pytest -q tests/test_runtime_supervisor.py
unset PYTHONPATH; python -m pytest -q
python scripts/verify_frozen.py
git diff --check
```