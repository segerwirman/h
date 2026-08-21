# Fase 35 — MCP Close Kill Failure Telemetry (Implemented)

**Status:** ✅ Completed, committed `dcdcdd3`  
**Date:** 2026-08-21  
**Type:** Single boundary remediation (MCP/subprocess), fake test verified  

---

## Executive Summary

**Authorized boundary closure:** Migrated blanket exception swallowing in `MCPServer.close()` to use `quiet.swallowed()` for observable failure telemetry when subprocess kill fails.

**Raw inventory delta:** **129 → 128 matches**, **S110: 106 → 105**, S112 unchanged (23). One target finding removed from inventory; no new debt introduced.

**Impact:** Stale MCP server subprocess cleanup failures now produce telemetry events (`mcp.close_kill_failed`) while preserving fail-open control flow and return values.

---

## Implementation Details

### Files Modified

**Single source edit:** `jarvis/agent/mcp_client.py`
- Line 27: Added `quiet` import to module header
- Line 173: Replaced `except Exception: pass` with `except Exception as exc: swallowed("mcp.close_kill_failed", exc)`

**Net delta:** +1 import line / -1 pass block = `0` lines overall (one-to-one swap)

### Event Names Registered

| Context | Telemetry event | Parameters |
|---------|-----------------|------------|
| Process kill failure | `mcp.close_kill_failed` | `exc` (OSError, CalledProcessError, or similar) |

The `swallowed()` helper records these under suppressed configuration by default ("Catat kegagalan yang sengaja ditelan. Tidak pernah melempar").

### Intentional Non-Migration

**Line 104 retained:** `except Exception: continue` di `_read_response()` parser **not changed**. This is protocol-normal behavior (skipping non-JSON log lines from MCP servers, which are expected noise). Adding telemetry here would cause high-frequency log spam without product benefit. Decision rationale documented inline.

---

## Test Evidence

### New Focused Test

**File:** `tests/test_mcp_close_kill_failed.py` (created)

**Test cases:**
1. `test_mcp_close_kill_failed_records_event_and_keeps_flow`: Fake proc whose `kill()` raises `OSError("process already gone")`. Asserts `swallowed()` fires with correct event name and exception, close() returns None, `_proc` cleared, no exception propagated.
2. `test_mcp_close_without_proc_records_no_event`: Idempotent close on fresh instance. No telemetry, no-op safe.

**Determinism:** Fake process object entirely offline; zero subprocess spawn, zero network calls.

### Regression Test Suite

**Command executed (offscreen):**
```bash
QT_QPA_PLATFORM=offscreen JARVIS_NO_MIC_METER=1 PYTHONDONTWRITEBYTECODE=1 \
python -m pytest tests/test_mcp_close_kill_failed.py \
                     tests/test_mcp_hub.py \
                     tests/test_mcp_catalog.py \
  --basetemp C:/Users/deathscythe hell/AppData/Local/Temp/jarvis_pytest_f35 -q
```

**Result:** **15 passed** in 1.47 seconds

Suite includes real echo-server subprocess spawn via `echo_server` fixture — verifies end-to-end handshake, tool call, and close path still works normally.

---

## Evidence Label Upgrade

**Domain:** MCP client subprocess lifecycle (`jarvis/agent/mcp_client.py::MCPServer.close()`)  
**From:** `not-run` (no observation executed for this specific error path)  
**To:** `fixture-accepted` (fake proc test + existing echo-server suite verify fail-open contract holds)

This upgrade is narrowly scoped: it asserts that kill failures now record telemetry instead of passing silently. It does NOT claim `endpoint-reachable` or `live-proven` for actual MCP server availability.

---

## Preservation Review

- ✅ No FROZEN files touched (baseline `094b696` integrity verified post-commit: `FROZEN integrity: OK (10 files, baseline 094b696)`)
- ✅ User-dirty paths preserved (config.yaml and other modified tracked files remain untouched)
- ✅ No semantic/routing/BUS subscriber modifications
- ✅ No control-flow changes (return value None, always clears `_proc`, never raise new exceptions)
- ✅ No callback order changes (close() called synchronously from caller thread)
- ✅ No retry logic modifications
- ✅ No fail-open behavior changes (all paths remain safe-fail, never propagate exceptions)
- ✅ Line 104 intentionally retained as protocol-normal skip (documented rationale)

---

## Metrics

| Metric | Pre | Post | Delta |
|--------|-----|------|-------|
| Raw S110 findings | 106 | 105 | -1 |
| Raw S112 findings | 23 | 23 | 0 |
| Total findings | 129 | 128 | -1 |
| Files affected | 37 | 37 | 0 |
| Lines added (git diff) | - | +1 import, +1 try-block header | net 0 |
| Lines deleted (git diff) | - | -1 pass block, -1 empty except header | net 0 |
| Focus tests | 0 | 2 | +2 |
| Regression suite passed | 13 | 15 | +2 |

---

## Boundary Scope Confirmation

**Narrow scope delivered:**
- ✅ Edit `jarvis/agent/mcp_client.py` only (one target location: line 173)
- ✅ Import `jarvis.core.quiet` where appropriate
- ✅ Replace `except Exception: pass` → `except Exception as exc: swallowed(..., exc)`
- ✅ Add two focused fake tests (idempotent + failure case)
- ✅ Verify FROZEN integrity unchanged
- ✅ Run MCP hub + catalog regression suite (real subprocess spawn included)
- ✅ Single commit with explicit staging (`dcdcdd3`)

**Explicitly NOT modified:**
- ❌ Line 104 JSON parser skip retained (protocol-normal non-JSON line handling)
- ❌ No semantic/routing/BUS subscriber modifications
- ❌ No provider/auth/network credentials accessed
- ❌ No actual MCP server spawns in migration work (echo-server fixture already in suite)
- ❌ No runtime observation performed during implementation (fake/offline first)

---

## Product Need Justification

**Rationale for reopening MCP/subprocess boundary:** SLICE19 documentation explicitly cites "MCP/subprocess" as one example category that can be reopened with explicit authorization.

**Concrete business impact:**
- When `MCPServer.close()` kills a stale or frozen subprocess, failures are currently silent
- Silent leaks accumulate over time (stale Node.js subprocesses from npx MCP servers)
- No visibility into whether the MCP tool set degraded due to orphaned processes
- Minimal fix adds observability without changing lifecycle guarantees

**Risk assessment:**
- Low risk: `close()` already wrapped in try-except; migration only adds logging
- High benefit: operational visibility into MCP server health without adding dependencies
- Measurable: kill failure count via swallowed() telemetry

---

## Next Steps

**Option A:** Continue Phase 35 batch closure (identify next single-file target)  
**Option B:** Pause Phase 35, implement P8 visual expansion proposal from docs/P8_VISUAL_EXPANSION.md  
**Option C:** Return to review pending items (FASE35_REOPENING_REVIEW.md decision, config.yaml cleanup, boot.py user-dirty resolution)

Two successful narrow boundary closures prove Phase 35 approach works. Decision now about roadmap direction: clean-up more low-hanging fruit vs. shift focus to GUI presentation layer improvements.

---

*Documented after single-commit migration: `dcdcdd3`.*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
