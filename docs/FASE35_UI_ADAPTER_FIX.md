# Fase 35 — UI Adapter Swallowed Telemetry Fix (Implemented)

**Status:** ✅ Completed, committed `38c2ffa`  
**Date:** 2026-08-21  
**Type:** Single boundary remediation, fake test verified  

---

## Executive Summary

**Authorized boundary closure:** Migrated blanket exception swallowing in `jarvis/agent/adapters/ui.py` to use the existing `quiet.swallowed()` helper for observability.

**Before → After raw S110 inventory:**
- **Before:** 131 findings / 38 files / 108 S110 / 23 S112 (pre-migration snapshot)
- **After:** 129 findings / 37 files / 106 S110 / 23 S112 (post-migration snapshot)
- **Delta:** -2 S110 findings removed from file count (both in `adapters/ui.py`)

**Impact:** Silent exception failures now produce telemetry events while preserving fail-open control flow, callback order, and return values.

---

## Implementation Details

### Files Modified

**Single source edit:** `jarvis/agent/adapters/ui.py`
- Line 13: Added `quiet` import to module header
- Line 119: Refactored existing swallow from local `from jarvis.core import quiet` import to top-level import; preserved `exc` capture
- Line 153: Replaced `except Exception: pass` with `except Exception as exc: swallowed("agent.adapter.ui.confirm_speech_failed", exc)`
- Line 183: Replaced `except Exception: pass` with `except Exception as exc: swallowed("agent.adapter.ui.artifact_remember_failed", exc)`

**Net delta:** +5 lines / -6 lines = `-1` line overall (import consolidation, two `pass` blocks replaced with single-line telemetry calls)

### Event Names Registered

| Context | Telemetry event | Parameters |
|---------|-----------------|------------|
| Progress narration failure | `agent.adapter.ui.progress_narration_failed` | `exc`, context dict |
| Confirm speech announcement failure | `agent.adapter.ui.confirm_speech_failed` | `exc` |
| Artifact remember failure | `agent.adapter.ui.artifact_remember_failed` | `exc` |

The `swallowed()` helper records these under suppressed configuration by default (as indicated in its docstring: "Catat kegagalan yang sengaja ditelan. Tidak pernah melempar").

---

## Test Evidence

### New Focused Test

**File:** `tests/test_ui_adapter_exceptions_handled_gracefully.py` (created)

**Test cases:**
1. `test_confirm_speech_failure_records_event_and_keeps_flow`: Verifies that a broken `_speak_line()` triggers `swallowed()` with proper event name and exception object, without interrupting the confirm question flow. Deterministic 0.1 s timeout via FakeConfig stub.
2. `test_artifact_remember_failure_records_event_and_continues`: Verifies that `remember_artifact()` failure triggers `swallowed()` with correct event and exception, while image remains logged to user-facing `write_log()`.

### Regression Test Suite

**Command executed (offscreen):**
```bash
QT_QPA_PLATFORM=offscreen JARVIS_NO_MIC_METER=1 PYTHONDONTWRITEBYTECODE=1 \
python -m pytest tests/test_ui_adapter_exceptions_handled_gracefully.py \
                     tests/test_ui_adapter_quiet.py \
                     tests/test_gui_p6a_adapter_seam.py \
                     tests/test_gui_p6b_adapter_optin.py \
                     tests/test_gui_p6c_adapter_acceptance.py \
  --basetemp C:/Users/deathscythe hell/AppData/Local/Temp/jarvis_pytest_f35 -q
```

**Result:** **21 passed** in 9.13 seconds

No adapter seam regression or parity loss observed.

---

## Evidence Label Upgrade

**Domain:** Agent adapter layer (`jarvis/agent/adapters/ui.py`)  
**From:** `not-run` (no observation executed for this specific pattern)  
**To:** `fixture-accepted` (focused RED-first tests verify behavior contract holds)

This upgrade is narrowly scoped: it asserts that the three blanket handlers now record failures to `swallowed()` instead of passing silently. It does NOT claim `endpoint-reachable` or `live-proven` for actual voice/media subsystems.

---

## Preservation Review

- ✅ No FROZEN files touched (baseline `094b696` integrity verified post-commit: `FROZEN integrity: OK (10 files, baseline 094b696)`)
- ✅ User-dirty paths preserved (config.yaml and other modified tracked files remain untouched)
- ✅ No semantic/routing/BUS subscriber modifications
- ✅ No control-flow changes (return values unchanged: None on timeout, void async methods continue normally)
- ✅ No callback order changes (async execution order identical)
- ✅ No retry logic modifications
- ✅ No fail-open behavior changes (all paths remain safe-fail, never raise new exceptions)

---

## Metrics

| Metric | Pre | Post | Delta |
|--------|-----|------|-------|
| Raw S110 findings | 108 | 106 | -2 |
| Raw S112 findings | 23 | 23 | 0 |
| Total findings | 131 | 129 | -2 |
| Files affected | 38 | 37 | -1 |
| Lines added (git diff) | - | +5 | +5 |
| Lines deleted (git diff) | - | -6 | -6 |
| Focus tests | 0 | 2 | +2 |
| Regression suite passed | 18 | 21 | +3 |

---

## Boundary Scope Confirmation

**Narrow scope delivered:**
- ✅ Edit `jarvis/agent/adapters/ui.py` only (3 target locations)
- ✅ Import `jarvis.core.quiet` where appropriate
- ✅ Replace `except Exception: pass` → `except Exception as exc: swallowed(..., exc)`
- ✅ Add ONE focused test file (2 deterministic tests)
- ✅ Verify FROZEN integrity unchanged
- ✅ Run focused regression suite (adapter seam + focus tests)
- ✅ Single commit with explicit staging

**Explicitly NOT modified:**
- ❌ No semantic/routing/BUS subscriber modifications
- ❌ No provider/auth/network credentials accessed
- ❌ No audio/voice/live subsystems started
- ❌ No GUI desktop automation launched
- ❌ No runtime observation performed (fake/offscreen only)

---

## Next Steps

**Option A:** Proceed to next Phase 35 candidate (if authorized)  
**Option B:** Resume roadmap P8 visual expansion proposal implementation  
**Option C:** Pause Phase 35 until concrete product need emerges

If continuing Phase 35: identify one additional boundary with documented business justification (e.g., scheduler Telegram notifications, MCP client retry handling, dashboard health check) and request explicit authorization.

---

*Documented after single-commit migration: `38c2ffa`.*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
