# P10 — Controlled Default Promotion

**Status:** Complete  
**Date:** 2026-08-21  
**Promotion:** `shell: modern` becomes the default `ui.shell` value  

---

## Change Summary

**Single configuration change:**

```yaml
ui.shell: modern          # legacy | modern (promotion)
```

Previously (`legacy`), now (`modern`). All other settings unchanged, including:

```yaml
ui.modern_shell:
  fallback_to_legacy: true    # rollback safety preserved
```

---

## Gates Verified (Pre-Commit)

| Gate | Expectation | Result | Pass? |
|------|-------------|--------|-------|
| Focused regressions pass | P9 × 5 + P7 × 20 + P8 × 13 = 38/38 | ✅ YES |
| No duplicate executor/task/speech/browser owner | Single BUS subscriber per task topic | ✅ YES |
| Startup fallback tested | `fallback_to_legacy: true` absorbs modern failure | ✅ YES |
| Rollback tested | Set `ui.shell: legacy` restores previous default | ✅ YES |
| Legacy remains available | Explicit opt-in still works; no code removed | ✅ YES |
| Documentation updated | This file states promotion and rollback path | ✅ YES |
| User approval recorded | Proceeded only after explicit authorization | ✅ YES |
| FROZEN integrity OK | 10 files, baseline `094b696` | ✅ YES |

---

## What Was Measured

- **P9 dual-shell semantic parity:** all eight roadmap §13 comparison targets match between legacy and modern (identical intents, submissions, logs, stages, approvals, cleanup).
- **Modern seam wiring:** IntentController text/interrupt seams bound to `MainWindow.handle_command` / `_do_interrupt`; legacy leaves seams unbound.
- **Subscriber invariant:** both shells add exactly +1 UI subscriber per task topic; no second owner created.
- **Construction performance:** modern shell ~0.91s; legacy rollback ~0.17s (offscreen, stubbed).
- **Fallback reliability:** simulated modern installation failure logs bounded diagnostic and falls back to legacy without crash when `fallback_to_legacy: true`.
- **FROZEN integrity verified** before commit.

---

## What Did Not Run

Per offline/fake-only constraints:

- ❌ No Gemini Live session starts
- ❌ No browser/CDP endpoint probes
- ❌ No camera/vision checks
- ❌ No network HTTP requests
- ❌ No voice input/output sessions
- ❌ No visual rendering quality validation (separately authorized)

Evidence label: **focused-tested**. Claims are limited to shell selection semantics, BUS subscriber counts, seam binding, and config behavior.

---

## Legacy Remains Available

Legacy is NOT deprecated or removed. To roll back:

```yaml
ui.shell: legacy          # explicit opt-in
```

Rollback requires source/config change only; no additional code paths are deleted. Retirement of legacy requires separate authorization and a production observation window per roadmap §14.

---

## Next Steps (Per Roadmap §14)

After P10, the next recommended milestone is a **final acceptance matrix** across executor/documents/tasks/GUI/browser/voice owners. This is only with explicit intent — do not proceed without separate authorization.

---

*This document records the P10 promotion. It does not authorize further changes.*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
