# JARVIS Post-Phase-20 Stabilization and Next Implementation Plan

> **For Hermes:** Implement exactly one phase at a time with strict RED → GREEN → focused regression → independent review. Do not begin the next phase without Takeda's explicit instruction.

**Goal:** Turn the large post-initial-commit worktree into a sequence of independently verifiable, reversible commits; close the only known regression; prove Phase 19/20 on the real Content Studio UI; then continue capability development without broadening remote or generic desktop authority.

**Architecture:** Work in five layers: governance and tool catalog correctness, Git recovery checkpoints, production-path acceptance, Content Studio usability, then narrow capability facades. Existing feature code stays additive. Generic coordinate/type/key/drag, remote UIA, filesystem upload, account/payment, and frozen-boundary changes remain denied.

**Tech Stack:** Python 3.11, PyQt6, pytest, UI Automation/pywinauto, SQLite, native JARVIS capability registry, RuntimeSupervisor, Git.

---

## Baseline from the 2026-08-01 read-only audit

```text
Branch: main
HEAD: d5fa35a Initial commit
Tracked modified: 26
Untracked: 156
Staged: 0
Frozen: OK (10 files, baseline 094b696)
Changed Python compile: 181 PASS
Fresh validation:
- Monitoring: 98 passed
- Remote setup/proposals/media: 55 passed
- Content Studio + desktop-safe: 224 passed
- Briefing/GWS/settings/privacy: 91 passed
- Voice: 127 passed
- Native agent/runtime: 183 passed, 1 failed
Known blocker: tests/test_toolgroups_usage.py — new tools fall into fallback `other`
```

## Global gates for every phase

1. Read `JARVIS.MD`, `.hermes/handoffs/current.md`, `.hermes.md`, and this plan.
2. Re-fingerprint the worktree before modifying files: `git status --short`, branch, HEAD, frozen verifier.
3. If unrelated paths changed since the audit, stop and perform a read-only scope audit before implementation.
4. Write one focused RED test and observe the expected failure.
5. Apply only the minimal additive GREEN change.
6. Run the phase-specific regression and relevant cross-boundary tests.
7. Run `python -m py_compile` for every changed Python file.
8. Run `git diff --check` and `python scripts/verify_frozen.py`.
9. Request independent code review before staging.
10. Stage only the exact phase allowlist; inspect `git diff --cached --stat` and `git diff --cached`.
11. Commit only after Takeda approves the staged scope.
12. Update all four continuity sources after each completed phase: `JARVIS.MD`, `.hermes/handoffs/current.md`, `.hermes.md`, and this roadmap/current relevant roadmap.

---

# Track A — Stabilization and Recovery Checkpoints

## Phase 20.1 — Tool Catalog Completeness and Desktop Resource Serialization

**Priority:** P0 blocker
**Status:** ✅ COMPLETE — 2026-08-02.

**Goal:** Map every discovered production tool to an explicit user-visible tool group and serialize all desktop-safe tools against the same desktop resource as generic computer control.

**Why now:** The only known fresh regression is `test_toolgroups_usage.py`; 18 new tools currently fall into fallback `other`. Tool groups are not cosmetic: they control capability UI, user toggles, schema exclusion, and exclusive resource planning.

**Files:**
- Modify: `jarvis/agent/toolgroups.py`
- Modify if required: `tests/test_toolgroups_usage.py`
- Add focused test only if existing coverage cannot express desktop-safe resource ownership.

**Required groups:**

| Group ID | Modules |
|---|---|
| `desktop_safe` | `desktop_observe`, `desktop_visual_observe`, every `desktop_safe_*` module |
| `content_studio` | `content_studio` |
| `native_system` | `native_voice_system` |
| `native_messaging` | `native_messaging` |
| `voice_briefing` | `voice_briefing` |
| `web_monitoring` | `web_monitor` |
| `youtube_voice` | `youtube_voice` |

**Resource contract:**
- Every `desktop_safe_*`, `desktop_observe`, and `desktop_visual_observe` tool requires exclusive resource `desktop`.
- Generic `computer` tools retain `desktop` ownership.
- Content Studio model-only operations do not acquire desktop unless invoked through a desktop-safe native executor.

**TDD tasks:**
1. RED: assert production `all_groups()` contains no `other` fallback.
2. RED: assert each new module belongs to its intended group.
3. RED: assert `resources_for_tool()` returns `{"desktop"}` for all desktop-safe tools.
4. GREEN: add explicit `ToolGroup` entries and `MODULE_RESOURCES` mappings.
5. Regression: verify disabled group removes corresponding schemas only for new sessions.

**Validation:**
```bash
QT_QPA_PLATFORM=offscreen python -m pytest -q \
  tests/test_toolgroups_usage.py \
  tests/test_execution_context.py \
  tests/test_desktop_safe_policy.py \
  tests/test_desktop_safe_lifecycle.py \
  tests/test_agent_core.py
python -m py_compile jarvis/agent/toolgroups.py
python scripts/verify_frozen.py
git diff --check
```

**Acceptance criteria:** no fallback `other` in the production registry; all desktop-safe actions serialize on the desktop resource; no capability exposure is broadened.

**Outcome:** all 48 source tool modules and 99 runtime tools have explicit mappings; no duplicate IDs/modules/memberships; nine desktop-safe tools share `desktop`; Content Studio prompt remains resource-free; optional safe Google/briefing modules are mapped while disabled/unavailable providers remain disabled/unavailable.

**Evidence:** RED observed for production fallback, missing explicit group, empty desktop resource, and four optional unmapped modules. GREEN focused suite 13 passed; final agent/provider matrix 259 passed plus desktop/domain matrix 93 passed (352 total); compile/diff/frozen PASS; independent reviewer verdict `passed=true` with no blockers or suggestions.

**Rollback:** revert only the explicit group/resource mapping; fallback behavior remains available in baseline but must not be committed as final state.

---

## Phase 20.2 — Continuity and Audit Metadata Cleanup

**Priority:** P1 housekeeping
**Dependency:** Phase 20.1 green.

**Status:** ✅ COMPLETE — 2026-08-02. Documentation-only; no runtime/config/provider/frozen/index change, staging, or commit.

**Goal:** Make durable documentation match the actual Phase 20 state and validation evidence without changing runtime code.

**Files:**
- Modify: `JARVIS.MD`
- Modify: `.hermes/handoffs/current.md`
- Modify: `.hermes.md`
- Modify: `docs/archive/plans/2026-07-31_032152-jarvis-roadmap.md`
- Modify: `docs/archive/plans/2026-07-31_123827-jarvis-next-phases.md`
- Keep this plan as the new source for post-Phase-20 implementation.

**Tasks:**
1. Remove stale placeholder update markers.
2. Record the fresh audit evidence: 777/778 tests passed before Phase 20.1 and the exact blocker.
3. After Phase 20.1, replace that with the new green result.
4. State explicitly that live Telegram/provider/audio/UIA acceptance remains separate from fixture tests.
5. Keep the next phase consistent across all continuity documents.

**Validation:** repository-wide search for stale Phase 20/deferred placeholder markers; Markdown diff review; frozen verifier.

**Acceptance criteria:** every continuity source says Phase 20 is complete, Phase 20.1 is the stabilization gate, and Phase 20.3 is the next checkpoint phase.

**Outcome:** all active continuity sources and relevant domain roadmaps now agree on Phase 20.2 completion and Phase 20.3 as next. Legacy Phase-21-as-next markers are explicitly superseded. Capability evidence uses the canonical `source-present`, `configured`, `runtime-wired`, `focused-tested`, `fixture-accepted`, and `live-proven` labels from the master roadmap; no source/unit/fake/fixture result is promoted to live proof.

**Verification:** stale marker/next-phase audit, Markdown UTF-8/fence/whitespace + manual review, non-document/index hash comparison, tracked-worktree `git diff --check`, frozen baseline `094b696`, and independent documentation review PASS. Untracked Markdown was validated separately because Git diff does not cover it. No Python test or compile was required because only Markdown changed.

---

## Phase 20.3 — Git Worktree Segmentation and Recovery Commits

**Priority:** P0 operational safety
**Dependency:** Phase 20.1–20.2 green.
**Status:** ✅ COMPLETE — 2026-08-03 (59 commit; ditutup commit DOC `29f94cd`).

**Goal:** Convert the 182-path dirty worktree into small, reviewable recovery commits without resetting or losing user work.

**Important:** This phase changes Git index/history, not product behavior. Each commit requires an exact allowlist, targeted tests, staged diff review, and Takeda approval.

### Commit sequence

> ⚠️ Rencana A–J di bawah SUPERSEDED oleh eksekusi aktual (dependency-ordered nyata): remediasi audit A46–A53 → GWS safe-read A54–A57 → telegram A58+TEL → monitoring A59–A70+MR → voice V1–V5 → closure MR/MSG/TEL/UX1/UX2/REG/CAP1/CAP2/WIN/COV/SCR → docs continuity DOC `29f94cd`. Detail per-commit ada di `session.md`.

#### Commit A — Capability context and registry foundation

**Scope:**
- `jarvis/agent/execution_context.py`
- `jarvis/agent/capabilities.py`
- `jarvis/agent/policy.py`
- `jarvis/agent/registry.py`
- `jarvis/agent/dispatch.py`
- `jarvis/agent/loop.py`
- `jarvis/gateway/base.py`
- `jarvis/agent/toolgroups.py`
- directly corresponding tests only

**Purpose:** one canonical execution context, capability descriptor lookup, policy, confirmation, audit redaction, session cleanup, and group/resource enforcement.

#### Commit B — Telegram gateway and secure remote setup/read

**Scope:** Telegram adapters, remote setup queue/ingress, remote-read policy, setup UI, gateway startup wiring, exact tests.

#### Commit C — Remote proposal and verified media controls

**Scope:** remote proposal queue/ingress, media policy/executor, local proposal sheet, exact window/Telegram wiring, exact tests.

#### Commit D — Monitoring 17A–17M

**Scope:** entire `jarvis/monitoring/`, monitor tool/UI, runtime startup seam, monitor scripts/tests, monitor docs.

#### Commit E — Content Studio A–D

**Scope:** content project/assets/export, Content Studio tool/UI/focus, action panel/window/config seams, Studio tests.

#### Commit F — Desktop-safe foundation and Phase 19/20

**Scope:** CUA safety/capture/UIA backend, desktop-safe tools/session/lifecycle, title/reorder policies, acceptance/soak scripts, desktop-safe tests.

#### Commit G — GWS safe-read, briefing, and provider UX

**Scope:** Gmail/Calendar safe modules/tools, briefing, boot briefing, provider settings, direct Google route, exact tests.

#### Commit H — Voice native bridge and mediated voice features

**Scope:** native voice declarations, voice briefing/proposal hooks, UI adapter/window voice seams, exact voice tests.

#### Commit I — Privacy helper and awareness UI cleanup

**Scope:** pure denylist, watcher wrapper, UIA/visual consumers, awareness default-icon cleanup, assessment and tests.

#### Commit J — Final continuity snapshot

**Scope:** remaining documentation only, after all code commits and final validation.

### Per-commit procedure

1. `git reset` is forbidden unless Takeda explicitly approves an exact command and scope.
2. Stage with an explicit path allowlist, never `git add -A`.
3. Inspect `git diff --cached --name-status` and verify no cross-domain files leaked in.
4. Run the commit's targeted suite after staging.
5. Request independent reviewer verdict.
6. Commit with a small message, e.g. `feat(agent): enforce scoped capability context`.
7. Verify remaining dirty paths are expected before starting the next commit.

**Acceptance criteria:** TERPENUHI — no untracked product source remains unintentionally; every commit is independently understandable and reversible; frozen baseline unchanged (`094b696`).

---

# Track B — Production-Path Acceptance

## Phase 21 — Desktop-Safe Production-Path Fixture Acceptance Harness

**Priority:** P0 proof gap
**Dependency:** recovery commits A, E, F.
**Status:** ✅ COMPLETE — 2026-08-03. Production-path `fixture-accepted` untuk Phase 19/20 (title + reorder verified) via fixture PyQt disposable; acceptance run menemukan & meremediasi G1 (text_field identity), G2 (plain listitem card), G4 (verifikasi visual order pasca-reorder — RuntimeId tidak stabil), F1/F2 (foreground title-bar click, drag thread). Rincian: `session.md` + master roadmap.

**Goal:** Prove Phase 19/20 against a disposable real PyQt Content Studio surface using the production UIA backend, local confirmation authority, one action, and recapture—without touching user applications.

**Architecture:** create a dedicated local acceptance fixture process/window with stable automation IDs and scene cards. The harness is never part of normal boot and never targets arbitrary foreground windows.

**Files likely:**
- Create: `scripts/content_studio_desktop_safe_acceptance.py`
- Create: `tests/test_content_studio_desktop_safe_acceptance_contract.py`
- Modify only if RED proves needed: `jarvis/ui/content_studio.py`, `jarvis/automation/uia_capture.py`

**Slices:**

### 21A — Title setter production-path fixture proof
1. Launch disposable Content Studio fixture.
2. Observe title field through production UIA capture.
3. Confirm locally through real `UIAdapter` authority or fixture-local trusted confirmer.
4. Set one policy-admitted title.
5. Recapture and verify same surface + RuntimeId + new field value when UIA exposes it.
6. Close fixture and prove process/window cleanup.

### 21B — Reorder production-path fixture proof
1. Render at least three visible scene cards in one scene-list container.
2. Capture distinct source/destination RuntimeIds and one parent RuntimeId.
3. Perform exactly one production `reorder_semantic` action.
4. Recapture and verify same surface, same cards, and changed semantic order—not merely RuntimeId survival.
5. Reject source==destination, parent mismatch, surface replacement, and changed RuntimeId before native action.

**Safety:** disposable fixture only; no filesystem/drop zone; no user app; no network; no retry after attempted action; metadata-only output.

**Validation:** focused unit tests plus one manually approved disposable-fixture acceptance run. Report unit and fixture evidence separately; do not label it external/user-surface live proof.

**Acceptance criteria:** both Phase 19 and Phase 20 have production-path `fixture-accepted` proof; no action can escape the fixture window. External/user-app `live-proven` status remains not established unless separately approved and executed.

---

## Phase 22 — Content Studio Scene List Production UX

**Priority:** P1 usability
**Dependency:** Phase 21.
**Status:** ✅ COMPLETE — 2026-08-03 (SCN `a54c9af`): scene list visible + selection + order number + Move Up/Down deterministik (first-up/last-down reject) reuse `move_scene()`; selected & asset mapping ikut reorder; accessibility identity stabil. Rincian: `session.md` + master roadmap.

**Goal:** Make scene order visible and usable in Content Studio without requiring an agent to manufacture semantic references manually.

**Architecture:** add a local scene-list widget owned by `ContentStudioSheet`. Preferred default controls are deterministic **Move Up / Move Down** buttons for the selected scene. Semantic drag remains available only through the bounded desktop-safe tool and acceptance path.

**Files likely:**
- Modify: `jarvis/ui/content_studio.py`
- Modify if pure model seam is needed: `jarvis/core/content_scene_reorder.py`
- Test: `tests/test_content_studio_scene_list_ui.py`
- Regression: existing Content Studio, title, and reorder tests

**Tasks:**
1. RED: scene list starts empty and renders cards only from local `_scenes`.
2. RED: selected scene has visible current order and deterministic move controls.
3. GREEN: render cards and call existing `move_scene()`; do not duplicate reorder logic.
4. RED: moving first up or last down rejects without mutation.
5. RED: selection follows the moved scene.
6. GREEN: refresh timeline and asset metadata mapping after reorder.
7. Add stable accessibility role/name/automation identity needed by Phase 21.

**Acceptance criteria:** local user can see and reorder scenes; no network, export write, generic drag, or remote ingress; sheet remains hidden by default.

---

## Phase 23 — Content Studio Export Timing and Preview Hardening

**Priority:** P1 product completeness
**Dependency:** Phase 22.
**Status:** ✅ COMPLETE — 2026-08-03 (TIM `999c121`): duration policy bounded (1–600s/scene, total 3600s), cumulative SRT standar, `shot_list_csv` duration tervalidasi, `preview_export` in-memory tanpa file write. Rincian: `session.md` + master roadmap.

**Goal:** Improve export usefulness without adding rendering, publishing, or file-writing authority.

**Scope:**
- bounded per-scene duration policy;
- caption timestamp generation based on validated durations;
- local in-memory preview for storyboard/captions/shot-list;
- existing fixed format allowlist remains authoritative.

**Files likely:**
- Create: `jarvis/core/content_timing_policy.py`
- Modify: `jarvis/core/content_export.py`
- Modify: `jarvis/ui/content_studio.py`
- Test: `tests/test_content_timing_policy.py`, `tests/test_content_export_timing.py`

**Policy:** finite integer duration, bounded range, no negative/NaN/bool, total project duration capped. Export still returns strings only.

**Acceptance criteria:** valid cumulative SRT timing; no video render, cloud share, destination path, or automatic write.

---

# Track C — Reliability and Live Integrations

## Phase 24 — Runtime Lifecycle Reliability Sweep

**Priority:** P1 reliability
**Dependency:** Git recovery checkpoints complete.
**Status:** ✅ COMPLETE — 2026-08-03 (LIF `1011794`): ownership table 16 entri (cron, telegram, monitor worker, awareness, voice pipeline monitor, wake, browser, sweeper, dispatch, fire-and-forget, boot, classifier), cron/sweeper bounded join, subprocess limit didokumentasikan. Rincian: `session.md` + master roadmap.

**Goal:** Ensure every boot-started or task-owned thread/process has an explicit owner, stop path, join policy, and safe failure state.

**Audit/implementation targets:**
- daemon agent workers in `jarvis/agent/dispatch.py`;
- voice non-daemon thread + cooperative stop;
- monitor non-daemon worker;
- Telegram polling daemon thread;
- cron daemon scheduler;
- wake trigger;
- browser and computer session leases;
- OAuth and response-composer workers.

**Tasks:**
1. Build a static ownership table and test it against canonical boot modes.
2. RED: app shutdown with active queued/running task cannot leave desktop/browser leases owned.
3. RED: monitor/voice threads receive stop and bounded join.
4. RED: timeout/cancel state is honest where underlying subprocess cannot be hard-killed.
5. Add only missing lifecycle hooks; do not rewrite working services.

**Acceptance criteria:** no new authority; clean shutdown evidence for normal and `--no-voice`; known non-killable subprocess limitations documented rather than hidden.

---

## Phase 25 — Credential-Free Integration Canary Matrix

**Priority:** P1 release confidence
**Dependency:** Phase 24.
**Status:** ✅ COMPLETE — 2026-08-03 (CAN `11430b6`): probe status boolean per provider (telegram/google/llm/voice/image/whatsapp), `--no-voice` → voice skipped, tanpa menyimpan/mengekspos nilai secret. Rincian: `session.md` + master roadmap.

**Goal:** Provide one command that reports integration readiness without reading or exposing secret values or making external side effects.

**Output schema:**
```json
{
  "component": "telegram|heavy_provider|image|google|whatsapp|vision|voice",
  "configured": true,
  "runtime_wired": true,
  "live_proof": "not_run|passed|failed",
  "reason_code": "fixed_safe_code"
}
```

**Rules:** existence/status only; never token, account ID, base URL with credentials, raw provider error, path, or chat identity.

**Acceptance criteria:** differentiates source-present, configured, runtime-wired, test-covered, and live-proven; no fabricated readiness.

---

## Phase 26 — Explicit Live Acceptance Ring

**Priority:** P2, requires Takeda approval per integration.

**Goal:** Run separately approved live checks for configured integrations after offline validation is green.

**Rings:**
1. Voice: mic → Gemini Live → playback → cooperative stop; preserve Charon and manual audio baseline.
2. Telegram: paired actor `/status`, unknown command, safe `/tools`, bounded task delivery; no mutation.
3. Heavy provider: one read-only tool-free task and one read-only web task.
4. Image: one benign generated image; verify artifact lifecycle without exposing path remotely.
5. Google: read-only Calendar/Gmail safe summary if OAuth is configured.
6. WhatsApp: status only first; sending/call requires separate explicit approval.

**Acceptance criteria:** each result recorded independently; failure in one integration does not block unrelated offline-ready commits.

---

# Track D — Bounded Capability Expansion

## Phase 27 — Named Capability Request Facade

**Priority:** P2; replaces old overly-early Phase 21 generic-facade idea.
**Dependency:** Phase 21 live proof and Phase 24 lifecycle sweep.

**Goal:** Route a small enum of already-proven named capabilities through one request facade without exposing raw tool names or generic arguments.

**Initial allowlist:**
- `content_studio_set_title`
- `content_studio_reorder_scene`
- `focus_mode_set`
- `browser_media_control`

**Schema:** capability enum + opaque proposal/ref IDs only. Values such as title remain governed by the dedicated intent-specific policy and are never accepted as a generic `text` parameter.

**Permanent rejects:** coordinate, selector, arbitrary action/tool name, key sequence, path, URL, screenshot, DOM/UI label, raw text dispatch, payment/account/login.

**Acceptance criteria:** facade cannot invoke anything absent from the fixed enum; every mutation preserves its original local confirmation and verification contract.

---

## Phase 28 — Mediated Remote Request Facade

**Priority:** P2, explicit product decision required.
**Dependency:** Phase 27.

**Goal:** Allow paired remote actors to request only the named proposal types already proven locally. Remote still cannot approve or execute.

**Contract:** actor/session binding, TTL, one-shot consume, fixed labels, metadata-only result, local desktop approval only. No raw UIA refs cross the remote boundary.

**Acceptance criteria:** remote phrases/API map to proposal enum only; no generic task, desktop toolset, screenshot, path, title content, or coordinate authority.

---

## Phase 29 — Optional Next Trusted UI Surface

**Priority:** Deferred until Takeda names one exact surface.

**Goal:** Add one further semantic action only when a real product need exists.

**Selection criteria:**
- exact local app and widget;
- stable semantic role + RuntimeId;
- source/destination or value domain can be proven;
- one reversible/bounded action;
- local confirmation;
- fresh recapture proof;
- no filesystem drop zone, login, payment, permission, terminal, or remote ingress.

**Possible candidates:** Content Studio timeline selection, local provider model selection, or one bounded settings toggle. Do not choose automatically.

---

# Explicitly deferred / deny-by-default

```text
- Generic coordinate/type/key/drag desktop facade.
- Remote UIA refs, screenshots, OCR, or desktop confirmation.
- Arbitrary tool-name or free-form argument facade.
- Generic remote cron tasks or monitor-job mutation.
- Automatic filesystem export, upload, cloud publish, or video rendering.
- Browser login, CAPTCHA, permission elevation, payment/account/checkout.
- Frozen-manifest changes without exact diff review and explicit approval.
```

---

# Recommended execution order

```text
Phase 20.1  Tool catalog + resource serialization ✅ COMPLETE
→ Phase 20.2 Continuity cleanup ✅ COMPLETE
→ Phase 20.3 Git segmentation/recovery commits (NEXT)
→ Phase 21   Desktop-safe production-path fixture acceptance
→ Phase 22   Content Studio scene-list production UX
→ Phase 23   Export timing/preview hardening
→ Phase 24   Runtime lifecycle reliability
→ Phase 25   Credential-free canary matrix
→ Phase 26   Explicit live acceptance ring
→ Phase 27   Named local capability facade
→ Phase 28   Mediated remote request facade (optional)
→ Phase 29   Next exact trusted UI surface (optional)
```

## Immediate next action

Run **Phase 20.3 only — Git Worktree Segmentation & Recovery Commits**. Start with a read-only audit of branch/HEAD/status/staged state/generated artifacts/frozen integrity and an actual dependency graph. Do not stage during discovery. Never use `git add -A`, reset/checkout/restore/clean/stash/discard/amend. For one dependency-complete slice at a time, stage an exact allowlist, inspect the full cached diff, run targeted tests/diff/frozen checks, obtain independent review, and ask Takeda to approve that exact staged scope before commit. Do not mix provider/credential/live integration/authority/frozen changes and do not begin Phase 21.

## Definition of done for the whole roadmap

- Worktree is segmented into reversible commits instead of one 182-path delta.
- Production tool registry has no fallback `other` for known tools.
- Desktop-safe tools share exclusive desktop resource ownership.
- Phase 19/20 obtain production-path `fixture-accepted` proof; external/user-app `live-proven` status remains a separate explicit acceptance class.
- Content Studio exposes a usable local scene list and deterministic reorder UX.
- Offline readiness is never mislabeled as live connectivity.
- Every capability expansion remains named, bounded, locally confirmed, recapture-verified, and remote-deny-by-default.
- Frozen baseline remains intact unless Takeda separately approves an exact frozen diff.
