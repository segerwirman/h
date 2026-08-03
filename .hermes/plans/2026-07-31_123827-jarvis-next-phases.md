# JARVIS Next Phases Implementation Plan

> **Continuity note (2026-08-02):** This historical plan is retained for domain detail only. `session.md` and `2026-08-01_224934-jarvis-master-implementation-roadmap.md` govern current numbering/order. Phase 20.2 is COMPLETE and Phase 20.3 Git worktree segmentation/recovery is NEXT. The legacy Phase 21 facade below is superseded by master Phase 27.

> **For Hermes:** Execute exactly one numbered phase only after Takeda explicitly selects it. Use strict RED → GREEN → refactor. Do not edit frozen files listed in `config/frozen_manifest.json`.

**Goal:** Turn the remaining JARVIS roadmap into a dependency-ordered delivery plan after Phase 17J, while retaining local confirmation, minimal authority, privacy-first persistence, and reversible small commits.

**Architecture:** Work from stability foundations to user-facing creative/productivity features, then to mediated remote capability, and finally high-risk desktop primitives only on explicit product need. Every phase is an independently shippable vertical slice with narrow persistence schemas and deny-by-default ingress.

**Tech stack:** Python 3.11, PyQt6, SQLite, native tool/capability registry, encrypted secret store, Google OAuth, bounded monitor scheduler, Playwright, existing image provider.

## Global gates for every phase

```text
1. Read JARVIS.MD, .hermes/handoffs/current.md, .hermes.md, and this plan.
2. Inspect relevant editable source + existing tests before modifying anything.
3. Write one focused test; run it and observe expected RED.
4. Implement the smallest additive GREEN change.
5. Run focused regression first; run isolated Qt tests when relevant.
6. Run: unset PYTHONPATH; python -m py_compile <changed .py files>
7. Run: git diff --check
8. Run: python scripts/verify_frozen.py
9. Update all four continuity documents only after the phase is green.
10. Make a small reversible commit only after user approves the exact dirty-worktree scope.
```

## Capability and authority order

| Order | Phase group | Outcome | Authority added |
|---:|---|---|---|
| 1 | 17K–17M | Monitor lifecycle consolidation | None beyond current local monitor control |
| 2 | Studio A–D | Local content-production workflow | Local files/assets only; no remote publishing |
| 3 | UI U1–U2 | Simplify UI and separate legacy privacy helper | None |
| 4 | Settings S1–S2 | Safer provider configuration UX | Existing local provider configuration only |
| 5 | 15B | Mediated Telegram proposal queue | Remote request only; desktop confirmation remains sole mutation authority |
| 6 | 15C | Verified remote media controls | Bounded browser-media state/proposals only |
| 7 | 19–20 | Explicitly requested desktop primitives | Named local-only semantic actions, never generic automation; legacy Phase 21 numbering superseded |

Existing completed milestones (14.5, 15S, 15A, 16A–16D, 17A–17J, 18A–18B) are baseline; do not reimplement them.

---

# Milestone 1 — Monitor Reliability Consolidation

## Phase 17K — Restart-Safe Job Lifecycle ✅ COMPLETE

**Outcome:** Persisted enabled state and finite safe status survive runtime reconstruction; only enabled jobs install exactly once per worker, and `stop()` joins a launched worker before replacement construction.

**Files:**
- Modify: `jarvis/monitoring/worker.py` only if RED demonstrates a lifecycle gap
- Modify: `jarvis/monitoring/runtime.py` only if RED demonstrates bootstrap gap
- Test: `tests/test_monitor_restart_lifecycle.py`
- Regression: `tests/test_monitor_job_controls.py`, `tests/test_monitor_worker.py`, `tests/test_monitor_runtime.py`

### Tasks
1. RED: create one enabled and one disabled persisted job; recreate registry/runtime from the same SQLite files.
2. RED: assert only the enabled record reaches `MonitorScheduler.create_monitor_job()` exactly once.
3. RED: assert `last_status`/`last_status_at` survive recreation and no raw result field exists in persistence/public metadata.
4. GREEN: add only missing idempotency or rehydration behavior; do not add scans, schedules, remote APIs, or generic cron.
5. Regression: verify `start → tick → stop → recreate → start`; duplicate start remains rejected.

**Acceptance criteria:** desktop-local only; disabled job never installs; no raw result/exception/body persists; no new worker thread leak.

## Phase 17L — Worker Restart/Shutdown Soak ✅ COMPLETE

**Outcome:** A fixed local fixture allowlist proves low-N enabled, disabled, safe-failure, and restart behavior with fail-closed metadata-only aggregate output.

**Files:**
- Create: `scripts/monitor_worker_lifecycle_soak.py`
- Create: `tests/test_monitor_worker_lifecycle_soak.py`
- Modify only if RED requires: `jarvis/monitoring/worker.py`

### Tasks
1. RED: runner output must be metadata-only and fail closed on one failed fixture.
2. RED: run N lifecycle fixtures containing enabled, disabled, safe failure, and restart cases.
3. GREEN: produce fixed aggregate `{fixture,status,iterations}` records only; omit stdout/stderr, exceptions, titles, URLs, payloads, and DB paths.
4. Execute low-N real local runner only after unit tests pass.

**Acceptance criteria:** no duplicate thread/install, safe failure records only, later fixtures marked not-run after failure, no generic execution path.

## Phase 17M — Local Monitor Job UX Polish ✅ COMPLETE

**Outcome:** The hidden desktop-local sheet renders concise Indonesian labels for enabled and finite safe statuses, while omitting timestamps and raw failure/source content.

**Files:**
- Modify: `jarvis/ui/monitor_source_sheet.py`
- Test: `tests/test_monitor_source_sheet.py`, `tests/test_monitor_job_controls.py`

### Tasks
1. RED: sheet labels distinguish active, disabled, not-started, ok, and source-failed without timestamp formatting leaks or raw error text.
2. GREEN: add concise Indonesian presentation for the finite fields already persisted.
3. RED: invalid/no-selected-source control is honest and cannot mutate any other job.
4. Isolated offscreen Qt regression; confirm hidden-by-default behavior after parent window show.

**Acceptance criteria:** no fetch/scan/start/stop button, no remote entry point, no raw source response or exception shown.

---

# Milestone 2 — Local Content Studio

## Studio A — Project, Safe Prompt Intake, and Scene Planning ✅ COMPLETE

**Outcome:** An opt-in desktop-local Content Studio accepts bounded local creative briefs and supports project/scene planning without upload or automatic external execution.

**Files:**
- Create: `jarvis/core/content_project.py`
- Create: `jarvis/agent/tools/content_studio.py`
- Create: `jarvis/ui/content_studio.py`
- Test: `tests/test_content_project.py`, `tests/test_content_studio.py`
- Wiring only after pure model tests: editable UI seam discovered during implementation

### Tasks
1. RED: allow only bounded `.txt`, `.md`, `.docx`, `.pdf`; reject scripts, archives, executable and unknown binary input.
2. GREEN: local size-capped extraction; do not auto-upload or treat document text as system instruction.
3. RED: project/scene model serializes title, audience, tone, hook, CTA, narration, and visual prompt; no remote path in tool result.
4. GREEN: add project model and local tool facade with explicit local-only policy.
5. RED/GREEN: hidden Content Studio sheet with Brief, Brainstorm, and Timeline; no image generation yet.

**Acceptance criteria:** local only, no browser/login/upload, no automatic external call from file load, no frozen UI edit.

## Studio B — Scene-Scoped Image Generation ✅ COMPLETE

**Outcome:** A configured existing image lane may generate exactly one explicitly selected scene and returns local asset metadata only, never the generated path.

**Files:**
- Create: `jarvis/core/content_assets.py`
- Modify: `jarvis/core/content_project.py`, `jarvis/ui/content_studio.py`
- Test: `tests/test_content_assets.py`, `tests/test_content_image_generation.py`

### Tasks
1. RED: unconfigured provider gives a safe unavailable state; no fabricated output.
2. GREEN: model selected-scene request and local asset metadata with provider/model/state only.
3. RED: selected-scene invocation does not create asset for another scene or reveal local path to remote/context.
4. GREEN: connect existing image-provider seam and artifact-continuity local-open hook.
5. Add fake-provider regression; real provider proof is manual and separately reported.

**Acceptance criteria:** no OAuth token repurposing, no remote path leak, no bulk/all-scene generation, no publishing.

## Studio C — Studio Focus Integration ✅ COMPLETE

**Outcome:** Studio owns one local action-panel toggle and a reversible header Focus control; closing Studio restores prior Focus Mode state.

**Files:**
- Modified: `jarvis/ui/actionpanel.py`, `jarvis/ui/window.py`, `jarvis/ui/content_studio.py`
- Created: `jarvis/ui/studio_focus.py`
- Test: `tests/test_studio_focus.py`

### Tasks
1. RED: action icon toggles only Studio; same icon closes it, and opening does not activate unrelated panels.
2. GREEN: register Studio through existing ContentStage semantics.
3. RED: Focus ON/OFF restores preceding local focus state when Studio closes.
4. GREEN: add explicit Studio-header focus control; auto-enable only through an opt-in config.

**Verification:** 11 passed (including offscreen Qt), py_compile/giff diff/frozen OK, no generic desktop mutation, no frozen-file change.

**Acceptance criteria:** no generic desktop mutation, no persistent terminal overlay, no frozen file modification without approval.

## Studio D — Creative Timeline and Local Export ✅ COMPLETE

**Outcome:** A local scene timeline plus bounded project-owned exports (storyboard/prompt sheet/shot list/voiceover/captions/asset manifest/JSON/CSV) via a fixed format allowlist; unsafe formats fail closed, no render/publish/write/path leak.

**Files:**
- Created: `jarvis/core/content_export.py`
- Modified: `jarvis/ui/content_studio.py`
- Test: `tests/test_content_export.py`, `tests/test_content_studio.py`

**Verification:** content_export 7 passed; Studio suite 34 passed; py_compile/git diff/verify_frozen OK; no frozen-file change.

**Goal:** Export useful production artifacts from scene data without rendering or publishing video.

**Files:**
- Create: `jarvis/core/content_export.py`
- Modify: `jarvis/ui/content_studio.py`
- Test: `tests/test_content_export.py`

### Tasks
1. RED: Studio timeline is distinct from global audit/context timeline.
2. GREEN: local model-only ordering, duration, narration, visual prompt, and asset state.
3. RED: Markdown storyboard, prompt sheet, shot list, voiceover draft, captions, asset manifest, JSON/CSV export contain only project-owned content.
4. GREEN: bounded export implementation; reject unsafe destination/type.

**Acceptance criteria:** no video editor/rendering, no cloud publishing, no automatic sharing, no secret/path leak to remote.

---

# Milestone 3 — UI and Provider Configuration Simplification

## UI U1 — Retire Awareness Icon ✅ COMPLETE

**Outcome:** `awareness` removed from the default `action_panel.icons`; watcher stays default-off and undeleted; icon re-addable via config; Studio/Focus unaffected.

**Files:**
- Modified: `config.yaml`
- Test: `tests/test_actionpanel_awareness_retire.py`

**Verification:** retire tests 3 passed; `test_actionpanel_toggle.py` 5/5 per-test green (combined-run exit 127 is the known cumulative Qt teardown artefact); py_compile/git diff/verify_frozen OK.

**Goal:** Remove the broad legacy awareness icon from the default user-facing action panel while retaining required privacy helpers.

**Files:**
- Modify: editable action-panel configuration/wiring seam discovered by inspection
- Test: relevant `tests/test_actionpanel_*.py`

### Tasks
1. RED: default icon list excludes awareness while Studio/Focus behavior remains valid.
2. GREEN: remove only default icon/signal wiring.
3. Regression: watcher stays default-off; no OCR/persistence UI becomes visible.

## UI U2 — Legacy Screen Awareness Assessment ✅ COMPLETE

**Outcome:** Pure shared privacy denylist extracted and static consumer assessment recorded in `2026-08-07-ui-u2-screen-awareness-assessment.md`; watcher remains unchanged and unpruned.

**Verification:** privacy helper/UIA/visual/action-panel regressions 44 passed; py_compile/git diff/verify_frozen OK.

**Goal:** Separate shared privacy denylist from legacy watcher before any deletion proposal.

**Files:**
- Create: `jarvis/core/privacy_denylist.py`
- Modify only after dependency audit: `jarvis/core/screen_awareness.py`, `jarvis/automation/uia_capture.py`, `jarvis/automation/visual_observe.py`
- Test: `tests/test_privacy_denylist.py` plus existing awareness tests

### Tasks
1. Read-only AST/dependency audit; classify every watcher consumer active/lazy/legacy/orphan.
2. RED: shared denylist contract.
3. GREEN: extract denylist additively; retain watcher behavior.
4. Stop after assessment unless Takeda explicitly approves a separate prune phase.

## Settings S1 — Simple Provider Settings ✅ COMPLETE

**Outcome:** Daily provider setup defaults to Select → Connect/Key → Test → Choose Model → Activate. Expert routing is hidden, Test remains in-memory, Save/Activate remain distinct, and errors are classified without raw detail/credential UI leakage.

**Verification:** focused S1 3 passed; provider/settings regression 30 passed; py_compile/git diff/verify_frozen OK.

**Goal:** Make daily provider setup use Select → Connect/Key → Test → Choose Model → Activate.

**Files:**
- Modify: `jarvis/ui/settings_providers.py`, `jarvis/core/settings_service.py`
- Test: `tests/test_provider_settings_redesign.py`, `tests/test_settings_providers_ui.py`

### Tasks
1. RED: simple controls visible and advanced routing hidden by default.
2. GREEN: connection state only; never display credentials.
3. RED: Test Connection uses an in-memory draft and cannot persist a key/base URL.
4. GREEN: Save and Activate remain distinct; model selector stays disabled until valid catalog response.

## Settings S2 — Advanced Routing Disclosure ✅ COMPLETE

**Outcome:** Existing light/heavy expert routing uses a local `TAMPILKAN/SEMBUNYIKAN ROUTING LANJUTAN` disclosure, collapsed by default; visibility-only toggle has no routing/config write or policy mutation.

**Verification:** focused S2 2 passed; provider/settings regression 32 passed; py_compile/git diff/verify_frozen OK.

**Goal:** Preserve expert routing controls behind collapsed progressive disclosure.

**Files:**
- Modify: `jarvis/ui/settings_providers.py`, `jarvis/core/settings_service.py`
- Test: provider settings regression plus advanced disclosure test

### Tasks
1. RED: advanced group hidden initially and opens only on local interaction.
2. GREEN: expose existing role settings without changing provider safety policy.
3. RED: no credential or raw provider error reaches UI/test output.

---

# Milestone 4 — Mediated Remote Requests

## Phase 15B — Telegram to Local Proposal Queue ✅ COMPLETE

**Outcome:** Paired Telegram exact Focus Mode phrases stage only actor/session-bound metadata; desktop-local sheet is sole approve/cancel/execute boundary with TTL and one-shot semantics.

**Verification:** core/ingress/UI/wiring 11 passed; remote capability/voice regression 15 passed; full focused 15B 34 passed; py_compile/git diff/verify_frozen OK.

**Goal:** Allow a paired Telegram actor to request an existing bounded mutation, while only desktop UI approves and executes.

**Files:**
- Create: `jarvis/agent/remote_proposals.py`, `jarvis/ui/remote_proposal_sheet.py`
- Modify: editable Telegram adapter, approval continuation seam
- Test: `tests/test_remote_proposals.py`, `tests/test_remote_proposal_ui.py`

### Tasks
1. RED: actor/request/session binding, TTL, one-time consumption, cancel, stale-context rejection.
2. GREEN: metadata-only proposal types for already-bounded actions only.
3. RED: remote never supplies raw tool arguments, UIA refs, coordinates, screenshot, secret, or approval action.
4. GREEN: desktop sheet renders a sanitized description and owns accept/reject.
5. RED/GREEN: fresh observation at execution; stale target cancels rather than retries.

**Acceptance criteria:** remote output has only safe execution metadata/reason code; no Telegram confirmation; no generic action facade.

## Phase 15C — Verified Remote Media Controls ✅ COMPLETE

**Outcome:** Paired media proposals are fixed and desktop-approved; existing BrowserMedia post-action verification gates success, while remote result is metadata-only.

**Verification:** focused remote/proposal/media/UI regression 44 passed; py_compile/git diff/verify_frozen OK. Broader browser selection has 8 unrelated legacy failures, recorded in handoff.

**Goal:** Support narrow browser-media status/play/pause/mute/volume through existing post-action verification.

**Files:**
- Modify: `jarvis/agent/tools/browser.py`, remote policy/proposal seams
- Test: `tests/test_browser_media.py`, `tests/test_remote_media_policy.py`

### Tasks
1. RED: remote media status safe/unavailable behavior; no URL/title/content leak.
2. GREEN: admit only explicit state commands via narrow policy.
3. RED: mutating media action follows proposal/verification contract where required.
4. GREEN: validate resulting browser media state and return metadata-only result.

**Acceptance criteria:** no coordinates, browser DOM dump, arbitrary navigation, login, payment/account surface, or remote desktop control.

---

# Milestone 5 — High-Risk Desktop Primitives (Explicit Product Need Only)

## Phase 19 — Intent-Specific Bounded Text Setter ✅ COMPLETE

**Outcome:** Content Studio Judul Project only — bounded policy 1-120, sheet set_project_title intent-specific, native UIA ValuePattern desktop tool desktop_safe_set_content_title with local confirmation + same-surface RuntimeId recapture, no generic dispatch.

**Decision:** Content Studio — field Judul Project (chosen by Takeda).

**Verification:** title_policy 7 + studio 6 + desktop_safe_title 8 + native tool 3 = 24 Phase-19 specific; focused suite 40 with existing studio project; plus 50 native safety (click/scroll/value/toggle); py_compile/frozen OK.

**Files:** jarvis/core/content_title_policy.py, jarvis/ui/content_studio.py, jarvis/automation/uia_capture.py, cua_safety.py, desktop_safe_click.py (session set_content_title + set_text_native wiring), desktop_safe_set_content_title.py, desktop_observe.py (text_field descriptor), capabilities.py, tests: test_content_title_policy.py, test_content_studio_title_setter.py, test_desktop_safe_set_content_title.py/.tool.

**Safety:** exactly one intent content_studio_title, bounded length, rejects URL/password/OTP/payment/terminal/chat/path, schema {observation_id, element_id, project_title} only, confirmation mandatory, session ownership, RuntimeId same-surface recapture, no coordinates/key/drag/generic typing, no submit/navigation/publish/network/path-leak, no frozen change.

## Phase 20 — Semantic Bounded Reorder ✅ COMPLETE

**Goal:** Implement a named reorder-only semantic pattern on exact trusted surface Content Studio scene list.

**Decision:** Content Studio — scene timeline reorder local (chosen by product decision).

**Outcome:**
- Policy admit_reorder(from,to,size) bounded int, bool rejected, same-surface, same-parent, distinct RuntimeId, one native drag only.
- Sheet move_scene(from,to) via policy, preserves other fields, updates selected mapping, no filesystem/upload.
- UIA backend reorder_semantic same-surface + same-parent check, center-to-center drag only, RuntimeId proof.
- SafeDesktopSession.reorder_scene ownership + gate + same-surface recapture verifying both RuntimeId.
- Tool desktop_safe_reorder_scene schema {observation_id, source_element_id, destination_element_id} only, requires_confirmation, session bound, verified.

**Verification:** policy 4 + sheet 4 + desktop schema 3 + tool execution 2 = 9 Phase-20 specific; focused 73 passed incl Phase 19; py_compile PASS; verify_frozen OK baseline 094b696.

**Safety:** exact intent content_studio_scene_reorder, bounded indices, same-surface + same-parent RuntimeId, distinct source/dest, one drag, no filesystem/upload/coordinate/path/secret leak, confirmation mandatory, recapture proof, no frozen change.

**Files:** jarvis/core/content_scene_reorder.py, jarvis/ui/content_studio.py, jarvis/automation/uia_capture.py, cua_safety.py, desktop_safe_click.py (reorder_scene+reorder_native), desktop_safe_reorder_scene.py, desktop_observe.py (card role), capabilities.py, tests: test_content_scene_reorder_policy.py, test_content_studio_reorder.py, test_desktop_safe_reorder_scene.py/.tool.


## Legacy Phase 21 — Narrow Generic Request Facade (SUPERSEDED BY MASTER PHASE 27)

**Goal:** Route named existing capabilities through a limited facade only after Phases 19–20 have real stable use-cases.

**Contract:** accepts enum capability and opaque refs only; permanently rejects coordinate, selector, arbitrary action, key sequence, text, screenshot, DOM/UI labels.

---

# Deferred / permanently deny-by-default until separately approved

```text
- Generic desktop automation, typing, key sequences, drag/drop, coordinate actions.
- Telegram secret confirmation and direct UIA control.
- Remote screenshots/OCR or raw browser content delivery.
- Arbitrary website login, CAPTCHA bypass, payment/account/checkout actions.
- Generic cron task execution and remote monitor-job mutation.
- Automatic video rendering/editor integration and cloud publishing.
- Frozen-boundary edits without exact diff review and explicit approval.
```

# Recommended execution order

```text
17K → 17L → 17M
→ Studio A → Studio B → Studio C → Studio D
→ UI U1 → UI U2 → Settings S1 → Settings S2
→ 15B → 15C
→ Phase 19/20 complete; use the master roadmap for Phase 20.3 onward.
```

## Current next phase

**Phase 20.3 — Git Worktree Segmentation & Recovery Commits.** Begin with a read-only scope/generated-artifact/dependency audit. Do not stage during discovery; never use broad staging or destructive Git commands; commit only after exact cached-diff review, targeted validation, independent review, and Takeda approval. Do not begin master Phase 21.

## Risk and rollback policy

- Every phase must be a small reversible commit after explicit scope approval.
- Any migration is additive and must retain valid existing data; invalid persisted rows fail closed.
- Any added local UI remains hidden by default unless explicitly opened.
- Stop and report if a phase requires frozen code, broad authority, credentials, or a live external side effect not explicitly approved.
