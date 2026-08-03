# Post-Phase 8 Readiness and Canary Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Pulihkan baseline test UI yang tidak terkait, lalu buktikan readiness desktop-safe melalui canary lokal yang tidak menambah authority baru.

**Architecture:** Fase 8 tetap membatasi authority ke observe, ALLOW-only single click, ALLOW-only semantic scroll, dan confirmed slider set-value melalui `UIAdapter` lokal. Sebelum canary, perbaiki contract test UI frozen tanpa mengubah frozen production behavior. Canary hanya memakai fixture PyQt disposable dan UIA native, tidak mengizinkan remote, voice, cron, delegation, koordinat, ketik, drag, atau generic desktop control.

**Tech Stack:** Python 3.11, pytest, PyQt6, pywinauto/UIA, native JARVIS registry/policy/session.

---

## Gate 0: Pulihkan baseline regression UI terpisah

### Task 0.1: Rekam expected contract fake window untuk ESC/back

**Objective:** Pastikan regression `ESC` pada panel aktif diuji terhadap contract produksi terkini.

**Files:**
- Modify: `tests/test_action_hint_and_back.py:250-290`
- Inspect only: `jarvis/ui/window.py:1955-1980` (frozen)

**Step 1: Triage fail saat ini**

Run:
```bash
unset PYTHONPATH
python -m pytest -q tests/test_action_hint_and_back.py::test_esc_saat_diam_dan_panel_terbuka_jadi_back
```

Expected current result: fail karena `_FakeWin` tidak memiliki `_close_stage_panels` yang dipanggil oleh `MainWindow._do_interrupt()`.

**Step 2: Perbaiki fake/test seam saja**

Tambahkan stub `_close_stage_panels()` pada `_FakeWin` yang meniru observasi kontrak panel aktual tanpa mengubah `jarvis/ui/window.py`.

**Step 3: Verify**

Run target ESC tests dan seluruh `tests/test_action_hint_and_back.py`.

**Boundary:** Jangan edit `jarvis/ui/window.py` tanpa approval frozen-file eksplisit.

---

## Gate 1: Freeze Fase 8 authority contract

### Task 1.1: Jalankan regression desktop-safe lengkap

**Files:**
- Test only: `tests/test_desktop_safe_approval_audit.py`
- Test only: `tests/test_desktop_safe_lifecycle.py`
- Test only: `tests/test_desktop_safe_policy.py`
- Test only: `tests/test_desktop_safe_click_tool.py`
- Test only: `tests/test_desktop_safe_scroll_tool.py`
- Test only: `tests/test_desktop_safe_set_value_tool.py`
- Test only: `tests/test_execution_context.py`
- Test only: `tests/test_agent_core.py`

**Step 1: Verify negative authority matrix**

Assert all remain denied before executor:

```text
remote / Telegram
voice / Gemini Live
cron
child delegation
missing/wrong ExecutionContext
forged adapter
BLOCK target
CONFIRM click target
guessed element ID after revoke
```

**Step 2: Verify positive local matrix**

```text
desktop observe
ALLOW semantic click
ALLOW semantic scroll
slider set-value via exact live UIAdapter + local BUS confirmation
```

**Step 3: Verify audit matrix**

Persisted tool/session/transcript must contain only opaque IDs, action, and `desktop_safe_failed`; never value, UI text, labels, RuntimeId, rect, coordinate, or raw error.

---

## Gate 2: Phase 9 disposable local-only canary

### Task 2.1: Define canary matrix and local kill conditions

**Objective:** Specify production-near but disposable proof before any future capability expansion.

**Files:**
- Create: `tests/test_desktop_safe_canary_contract.py`
- Create or modify: `scripts/cua_desktop_safe_canary.py`

**Step 1: Write failing canary contract test**

Test matrix must include:

| Scenario | Expected result |
|---|---|
| UIA fixture button ALLOW | exactly one click, verified recapture |
| UIA fixture scrollbar ALLOW | fixed internal delta, marker changes |
| UIA fixture slider | exact `UIAdapter` local confirmation then one setter |
| Delete/Send/Submit fixture | not exposed; guessed ID rejected; zero lease/executor |
| Password/Login fixture | BLOCK; zero lease/executor |
| forged adapter | rejected before ask/executor |
| delegation child context | schema lacks all desktop-safe tools |
| recapture/native exception | executed/unverified, no retry, observation invalid |

**Step 2: Run RED**

Run only the new test and confirm it fails for missing canary implementation/fixture.

**Step 3: Implement minimal disposable fixture**

Use a new visible PyQt fixture window containing non-sensitive controls. It must not read production UI text, screenshots, OCR, passwords, or `.env` data. Local confirmation must travel through `UIAdapter(window)` and local BUS `confirm`, never a fake adapter.

**Step 4: Verify GREEN**

Run the canary script and assert machine-readable output includes:

```text
accepted
executed
verified
marker_changed where applicable
negative scenario zero executor calls
```

**Step 5: Abort conditions**

Do not continue to a broader rollout if any result has:

```text
unverified success
more than one native action
reused observation
lease leak
schema exposure to non-local context
raw UI/error/value leaked to audit/session transcript
```

---

## Gate 3: Readiness review and rollback proof

### Task 3.1: Independent read-only review

**Objective:** Verify no authority expansion occurred while preparing canary.

**Files:**
- Review: `jarvis/agent/registry.py`
- Review: `jarvis/agent/policy.py`
- Review: `jarvis/agent/execution_context.py`
- Review: `jarvis/agent/tools/desktop_safe_click.py`
- Review: `jarvis/agent/tools/desktop_safe_set_value.py`
- Review: canary test/script from Gate 2

**Acceptance:** Report P0-P3, capability/schema matrix, audit data shape, and explicit confirmation that coordinate/type/key/drag, remote/voice/cron/delegation, generic desktop facade, and vision fallback remain absent.

### Task 3.2: Final verification

Run:
```bash
unset PYTHONPATH
python -m pytest -q \
  tests/test_action_hint_and_back.py \
  tests/test_desktop_safe_approval_audit.py \
  tests/test_desktop_safe_lifecycle.py \
  tests/test_desktop_safe_policy.py \
  tests/test_desktop_safe_click_tool.py \
  tests/test_desktop_safe_scroll_tool.py \
  tests/test_desktop_safe_set_value_tool.py \
  tests/test_execution_context.py \
  tests/test_agent_core.py
python scripts/cua_safe_click_acceptance.py
python scripts/cua_safe_scroll_acceptance.py
python scripts/cua_safe_set_value_acceptance.py
python -m py_compile jarvis/agent/registry.py jarvis/agent/loop.py jarvis/agent/execution_context.py
git diff --check
python scripts/verify_frozen.py
```

**Expected:** All targeted tests and disposable acceptances pass; frozen integrity remains green.

---

## Explicit non-goals

This plan does **not** add:

```text
right/double click
dropdown selection
text/key input
drag
coordinate input
screenshots/OCR/vision fallback
remote/Telegram execution
voice execution
cron/delegation execution
generic computer_control / desktop_control / screen_process
```

Only after canary is green and explicitly approved should the next capability design phase be considered.