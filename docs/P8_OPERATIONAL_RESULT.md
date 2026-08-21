# P8 — Operational Check Result

**Status:** PASSED  
**Date:** 2026-08-21  
**Run Type:** Single empty modern shell instance, offscreen, fully stubbed  

---

## Observation Output

```markdown
[modern-run] shell_selected='modern'
[modern-run] construction=success elapsed=0.95s (<5s: True)
[modern-run] window_property='modern' count=1 handle=True
[modern-run] task_topic_deltas={'task.submitted': 1, 'task.updated': 1, 'task.finished': 1}
[modern-run] intent_text_seam=registered (via _install_modern_treatment)
[modern-run] intent_interrupt_seam=registered (via _install_modern_treatment)

[legacy-rollback] shell_selected='legacy'
[legacy-rollback] construction=success elapsed=0.38s (<5s: True)
[legacy-rollback] window_property='legacy' count=1 handle=True
[legacy-rollback] task_topic_deltas={'task.submitted': 1, 'task.updated': 1, 'task.finished': 1}
[legacy-rollback] intent_text_seam=n/a (never registered for legacy)
[legacy-rollback] intent_interrupt_seam=n/a (never registered for legacy)

observation.complete
```

---

## Gates Verified

| Gate | Expectation | Result | Pass? |
|------|-------------|--------|-------|
| Shell selection success | `"modern"` or `"legacy"` selected without crash | Both selected successfully | ✅ YES |
| Construction time <5s | Window handles created quickly | Modern: 0.95s; Legacy: 0.38s | ✅ YES |
| Window property set | MainWindow has correct `SHELL_PROPERTY` marker | `'modern'` and `'legacy'` respectively | ✅ YES |
| BUS subscriber delta = +1 per topic | No second owner created for either shell | Exactly +1 for all three task topics | ✅ YES |
| FROZEN integrity | Unchanged from baseline | OK (10 files, baseline `094b696`) | ✅ YES |
| IntentController seams | Registered via `_install_modern_treatment()` for modern shell | Text routing → `handle_command`, interrupt → `_do_interrupt` | ✅ YES |

---

## Evidence Labels

- **operational-checked**: Modern shell constructed at least once successfully
- **fallback_verified**: Legacy remains available after modern run with identical deltas
- **focused-tested**: All 33 tests pass offline

NOT claimed:
- ❌ `live-proven`: Visual rendering quality untested
- ❌ `endpoint-reachable`: No network/CDP/browser probes executed
- ❌ `production-ready`: No user-facing visual validation yet

---

## What Was Observed (ONLY)

1. Shell selection succeeds for both `ui.shell: modern` and `ui.shell: legacy`
2. Window construction completes within bounded time (<1s each)
3. Identical BUS task-topic subscriber counts (+1 per topic) regardless of shell type
4. IntentController seams properly registered for modern shell path
5. FROZEN files untouched throughout observation

---

## What Was NOT Observed (Per Authorization Boundary)

- ❌ Gemini Live session starts
- ❌ Browser/CDP endpoint probes
- ❌ Camera/vision checks
- ❌ Network HTTP requests
- ❌ Voice input/output sessions
- ❌ DOM inspection or cookie reading
- ❌ Keyring credential access
- ❌ Visual rendering quality assessment
- ❌ Panel interaction behavior
- ❌ State projector real-time updates

---

## Post-Validation Next Step

**Recommended: Proceed to P9 — Dual-shell semantic acceptance**

Build P9 test harness that feeds both legacy and modern shells identical fake sequences and compares outputs:
- Same submitted commands
- Same BUS events (boot.check, notify, focus.changed)
- Same task lifecycle (submitted → updated → finished)
- Expected semantic state snapshots match across both shells

**Do NOT proceed to P8 visual redesign expansion** until P9 gates pass. P9 proves semantic parity BEFORE investing any visual changes beyond the first slice.

---

*This document is read-only evidence record. It does not authorize further source changes.*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
