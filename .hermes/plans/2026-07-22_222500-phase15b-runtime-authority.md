# Phase 15B Runtime Authority Implementation Plan

> **For Hermes:** Execute in vertical TDD slices. Do not start voice, dashboard, gateway polling, or any external integration while testing.

**Goal:** Give the canonical JARVIS desktop runtime explicit ownership of background threads/services and deterministic bounded shutdown.

**Architecture:** Introduce a small native `RuntimeSupervisor` owning stop callbacks and thread handles. `jarvis.main` registers service shutdown in reverse order and runs legacy Gemini Live only through a named supervisor-owned voice thread. Legacy `JarvisLive` remains functionally intact in this initial slice; extraction into `jarvis/voice/runtime.py` follows after lifecycle seams prove stable.

**Tech Stack:** Python 3.11, threading, asyncio, pytest.

---

### Task 1: Supervisor primitive

**Files:**
- Create: `jarvis/runtime/supervisor.py`
- Test: `tests/test_runtime_supervisor.py`

1. RED: test reverse stop order, idempotent shutdown, bounded thread join, and exception isolation.
2. GREEN: `RuntimeSupervisor.add_stop()`, `add_thread()`, `shutdown()`.
3. Verification: `python -m pytest -q tests/test_runtime_supervisor.py`.

### Task 2: Supervisor-owned voice launch

**Files:**
- Modify: `jarvis/main.py:24-48,164-188`
- Test: `tests/test_runtime_supervisor.py`

1. RED: test `_start_voice_pipeline()` returns a non-daemon named thread and can be registered without importing/running legacy voice code.
2. GREEN: inject `supervisor`, return thread, remove anonymous daemon lifecycle.
3. Ensure voice startup still only occurs when `no_voice=False`.

### Task 3: Canonical shutdown wiring

**Files:**
- Modify: `jarvis/main.py:50-189`
- Test: `tests/test_runtime_supervisor.py`

1. RED: fake UI/service integration asserts shutdown reverse order and bounded voice join.
2. GREEN: register vision/social/wake/relay/gateway/cron/screen awareness callbacks through supervisor; call one `shutdown()` in `finally`.
3. Preserve existing optional-service degradation.

### Task 4: Headless lifecycle seam

**Files:**
- Modify: `jarvis/main.py`
- Test: `tests/test_runtime_supervisor.py`

1. RED: `run(..., ui_factory=...)` injectable seam allows a fake UI mainloop to return without constructing real Tk/voice/network services.
2. GREEN: keyword-only factory/dependency seam, production defaults unchanged.
3. Do not introduce a live health server or run production bootstrap in tests.

### Task 5: Voice extraction preparation

**Files:**
- Create: `jarvis/voice/runtime.py` only if the previous seam identifies a minimal safe adapter boundary.
- Modify: `jarvis/main.py`
- Test: `tests/test_runtime_supervisor.py`

Move only the launcher/adapter boundary, not the 1,800-line `main.JarvisLive` implementation. Keep root `main.py` compatibility until a later dedicated extraction phase.

### Task 6: Verification

```bash
unset PYTHONPATH; python -m pytest -q tests/test_runtime_supervisor.py tests/test_phase5_stage_home.py tests/test_xlix_p0.py
unset PYTHONPATH; python -m pytest -q
python scripts/verify_frozen.py
git diff --check
```

No commit/push until dirty workspace ownership is separated.

## Acceptance

- Background voice thread has a handle and bounded join.
- Shutdown callbacks run once, reverse registration order, despite individual failures.
- Canonical `jarvis.main` has one shutdown authority.
- Production default behavior remains unchanged; tests do not boot live voice/network/UI.
- All verification exits zero.

## Risks

- Root legacy voice loop has no native stop event; this slice can own the thread/join boundary but cannot safely force-kill it. Follow-up extraction must add cooperative cancellation inside `JarvisLive.run()`.
- UI constructor imports may be heavy; injectable seam must preserve desktop defaults.