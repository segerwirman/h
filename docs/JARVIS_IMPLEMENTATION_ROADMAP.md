# Jarvis Implementation Roadmap

**Status:** Approved working order for future implementation

**Primary objective:** Stabilize and prove Jarvis's functional owners before changing the GUI presentation layer.

**Operating principle:** Make one boundary change at a time, preserve existing owners, measure before and after, and stop at the first failed gate.

---

## 1. Current starting point

The repository is not starting from a clean slate. The following constraints are active:

- Fase 35 is paused as **SEBAGIAN**.
- Latest measured raw Ruff state is **131 findings / 38 files / 108 S110 / 23 S112**.
- All remaining Fase 35 findings are inside explicit exclusions. Do not reopen that phase unless a concrete product need authorizes one specific boundary.
- The GUI evolution design is documented separately in [GUI_EVOLUTION_PLAN.md](GUI_EVOLUTION_PLAN.md).
- The repository contains user-dirty tracked files and untracked files. They are not part of this roadmap and must remain untouched.
- FROZEN integrity must continue to report:

  `FROZEN integrity: OK (10 files, baseline 094b696)`

- Offline tests must use a `--basetemp` directory outside the repository.
- No API key may be requested, printed, copied, logged, or persisted in source, tests, documentation, or command output.
- Provider, network, browser, keyring, microphone, speaker, audio session, camera, and hardware work require separate authorization when the phase calls for them.
- Offline evidence is limited to `focused-tested` and, where wiring is demonstrated, `runtime-wired`. It is never `live-proven`.

This roadmap intentionally does not claim that any previously suspected outage still exists. The first implementation phase verifies the current behavior rather than relying on historical reports.

---

## 2. The safe order at a glance

```text
P0  Preserve + establish evidence baseline
 ↓
P1  Executor/classifier acceptance
 ↓
P2  Document coordinator + DocumentExplanation wiring
 ↓
P3  Dedicated Chrome/CDP offline acceptance
 ↓
P4  GUI-0 read-only contract audit
 ↓
P5  GUI characterization tests
 ↓
P6  Presentation adapter with legacy shell
 ↓
P7  State projector + intent controller
 ↓
P8  Modern GUI shell behind feature flag
 ↓
P9  Dual-shell acceptance + opt-in operational check
 ↓
P10 Default promotion and long rollback window
 ↓
Optional: reopen one Fase 35 boundary only for a concrete product need
```

The dependency rule is strict:

> Do not implement a later phase when an earlier phase has an unresolved ownership, routing, persistence, or safety failure.

GUI-0 can be performed as a read-only preparation step at any time, but visual redesign and presentation-source changes wait until P1–P3 are accepted.

---

## 3. Cross-phase safety protocol

Every implementation phase follows the same sequence.

### 3.1 Before editing

1. Read the relevant source, tests, current configuration, and phase documentation.
2. Record the current Git status; treat all existing modifications and untracked paths as owned by the user.
3. Measure the relevant baseline: focused test result, raw lint where applicable, and any phase-specific health check.
4. Identify the exact boundary: file, symbol, behavior, event, and expected delta.
5. State what is explicitly out of scope.
6. If the boundary was previously excluded, obtain a separate explicit authorization before editing.

### 3.2 RED-first

1. Add one focused offline test or characterization assertion.
2. Run it before the source change.
3. Confirm that it fails for the intended missing behavior, not because of a broken fixture or environment.
4. Stop and repair the fixture if the failure is unrelated.
5. Do not continue when the RED result is ambiguous.

### 3.3 Implement minimally

- Change one owner or one adapter seam.
- Preserve return values, fallback behavior, callback order, thread ownership, and cancellation semantics.
- Add bounded telemetry only where the boundary explicitly permits it.
- Do not perform opportunistic cleanup in adjacent blocks.

### 3.4 Verify

Run, as applicable:

- focused GREEN test;
- focused regression tests;
- configured Ruff on the exact source/test targets;
- authoritative raw Ruff measurement for lint slices;
- compile check;
- `git diff --check`;
- FROZEN verifier;
- status and diff review showing only intended files.

### 3.5 Commit and handoff

- Stage paths explicitly; never use `git add .` or `git add -A`.
- Separate source/test and documentation commits.
- Never reset, checkout, restore, clean, stash, amend, or force cleanup.
- Record actual evidence labels and failures honestly.
- Write the next recommendation before closing the phase.

---

## 4. P0 — Preserve and establish the baseline

**Purpose:** Prevent unrelated work from being mixed into a functional stabilization phase.

### Read-only inventory

Capture:

- Git status and current branch;
- user-dirty tracked paths;
- untracked paths;
- FROZEN verifier result;
- relevant focused test baseline;
- current executor/classifier entry points;
- current document coordinator and explanation paths;
- current browser/CDP implementation and tests;
- current GUI composition root.

### Deliverables

- a phase note listing exact scope;
- a baseline command list;
- a stop list of excluded files and systems;
- no source edits.

### Gate P0

Proceed only if:

- existing user changes are identified;
- no dirty path will be staged by accident;
- FROZEN integrity passes;
- baseline commands are reproducible.

If P0 fails, stop and repair the evidence procedure only. Do not alter product code.

### Exit evidence

`measured`, plus the actual FROZEN verifier output. No claim of functional readiness is made at P0.

---

## 5. P1 — Executor and classifier acceptance

**Purpose:** Prove that text/task input reaches exactly one correct execution owner before any presentation redesign.

This phase addresses the most important product dependency: if routing is wrong, every UI shell will display misleading status or duplicate work.

### P1-A — Read-only route map

Trace the current path for:

```text
input → local action resolver → execution classifier → native agent/tool lane → result → task/UI output
```

Record:

- where local actions return early;
- where clarification is handled;
- where the native agent begins;
- where deterministic tools execute;
- where fallback chat begins;
- which owner writes the final result;
- which owner speaks the result;
- which task events are emitted.

Do not change routing during this substep.

### P1-B — Characterization matrix

Build offline fixtures for at least:

| Input class | Expected owner | Expected invariant |
|---|---|---|
| Deterministic local action | Local action executor | No second agent route |
| Clear native-agent task | Native agent executor | One task owner |
| Deterministic tool command | Registry/tool executor | One execution and one result |
| Clarification answer | Pending clarification owner | Not reclassified as new command |
| Ambiguous command | Existing fallback policy | Explicit result or bounded clarification |
| Unsupported command | Honest failure/fallback | No silent drop |
| Executor exception | Existing error owner | Error visible; worker cleanup preserved |
| Timeout/cancellation | Task owner | Terminal status recorded |
| Duplicate in-flight task | Existing dedup policy | No duplicate worker |

Use fake classifier, fake registry/tool, fake adapter, fake clock where needed. Do not instantiate real providers.

### P1-C — Candidate implementation rules

Only after a RED result identifies a real gap:

- change the smallest routing seam;
- preserve classifier injection seams used by tests;
- preserve `CommandRoutingMixin` behavior and callback order;
- keep UI output as a consumer of the result, not the executor owner;
- ensure failed presentation or speech cannot erase the task result;
- keep task ledger state authoritative.

### P1-D — Gates

Required before P1 acceptance:

- all new characterization tests pass;
- relevant executor/task regression passes;
- duplicate route or duplicate speech assertions pass;
- failure and cancellation paths are tested;
- no provider/network/keyring access occurred;
- no GUI redesign has begun.

### P1 exit condition

The input-to-owner contract is stable enough that a new GUI can submit an intent without knowing how execution works.

Evidence: `focused-tested`, and `runtime-wired` only where the tested wiring demonstrates it.

### Next recommendation after P1

Proceed to **P2 — document coordinator and `DocumentExplanation` wiring audit**, not GUI visual work.

---

## 6. P2 — Document coordinator and explanation wiring

**Purpose:** Make document operations and their user-facing explanation flow stable before a new shell renders them.

### P2-A — Read-only ownership map

Trace:

```text
text/agent tool → document coordinator → lifecycle/store → result → DocumentExplanation → UI/log/speech
```

Verify which component owns:

- create/read/update/delete;
- lifecycle transitions;
- file validation and limits;
- explanation construction;
- user-facing result delivery;
- speech notification.

The coordinator must be the single owner for document operations. The GUI must not become a second document owner.

### P2-B — Offline contract tests

Cover:

- create/read/update/delete with `tmp_path` or fake store;
- malformed or missing document;
- size/type rejection;
- coordinator success with explanation;
- coordinator failure with bounded error;
- explanation construction failure;
- UI/log sink failure;
- speech sink failure;
- cancellation and duplicate request;
- result remains available when notification fails.

No real provider, network, keyring, browser, microphone, or speaker.

### P2-C — Wiring correction, if required

If the audit proves that `DocumentExplanation` is not reaching the intended tool/speech/UI boundary:

- add only the missing adapter call;
- retain coordinator ownership;
- return the same domain result regardless of notification outcome;
- prevent double explanation and double speech;
- add a focused RED-first test.

Do not redesign document widgets in P2.

### P2 gates

- coordinator has one owner;
- explanation reaches the intended consumer in fake tests;
- no duplicate speech or result path;
- document lifecycle tests pass;
- user-dirty document files remain untouched unless explicitly scoped;
- FROZEN integrity passes.

### P2 exit condition

A future GUI only needs to render a document result/explanation model; it does not need to understand document storage or lifecycle internals.

### Next recommendation after P2

Proceed to **P3 — dedicated Chrome/CDP offline acceptance**, if that implementation is still incomplete. Otherwise proceed to P4.

---

## 7. P3 — Dedicated Chrome/CDP offline acceptance

**Purpose:** Prove the Jarvis-owned browser lifecycle without touching the user's everyday Chrome or mixing it with GUI work.

### P3-A — Separate the lanes

Maintain this strict split:

- Jarvis-owned dedicated profile: isolated directory, loopback CDP, default port 9333;
- user daily Chrome: attach-only lane, default port 9222;
- no copying of Profile 8 data;
- no sharing of browser owner or close path.

### P3-B — Fake/offline tests

Test:

- default profile path outside repository and user Chrome data;
- address and port validation;
- unsafe profile override rejected;
- exact launch argument contract;
- readiness success and bounded timeout;
- occupied port fails closed;
- concurrent `ensure` creates one owner/launch;
- repeated close is a safe no-op;
- blocked close reports survivor/timeout;
- no force-kill API;
- BrowserAgent bridge only manages the configured owned target;
- arbitrary CDP target remains attach-only;
- aggregate status contains no URLs, credentials, DOM, or raw command data.

No Chrome launch is part of offline implementation.

### P3-C — Operational approval boundary

After fake tests and regression are green, request a separate approval for exactly one empty dedicated-profile run. That run may observe only aggregate ownership/readiness/port/tab-count facts and bounded close behavior.

Do not:

- attach to Profile 8;
- navigate;
- inspect DOM;
- read tabs or credentials;
- force-kill Chrome;
- start audio or Gemini Live.

### P3 gates

- offline tests pass;
- user-browser tests remain unchanged;
- FROZEN verifier passes;
- no Profile 8 data is touched;
- operational result, if authorized, is labeled narrowly.

### Next recommendation after P3

Proceed to **P4 — GUI-0 read-only contract audit**.

---

## 8. P4 — GUI-0 read-only contract audit

**Purpose:** Establish the presentation boundary without changing appearance or behavior.

### Inventory

Document:

- public `JarvisUI` facade methods and properties;
- `MainWindow` signal/callback seams;
- mixin ownership map;
- `ContentStage` registrations and readiness transitions;
- `ActionPanel` signals and toggle state;
- `CommandBar` submission and predictive input behavior;
- `task_wiring` install/refresh/cancel/recovery path;
- `UIAdapter` calls and weak-reference behavior;
- BUS topics and UI subscribers;
- window hotkeys and close behavior;
- voice/audio/camera/browser/task owners;
- FROZEN and user-dirty file list.

### P4 deliverable

Create a contract matrix with columns:

```text
surface | producer | consumer | owner | thread | failure behavior | test | protected?
```

Choose exactly one future adapter seam. Do not create it yet unless separately authorized.

### P4 gate

- no source behavior changed;
- no widget moved;
- no provider/network/audio/browser/camera/hardware access;
- matrix identifies one owner for each critical behavior;
- modern shell has a rollback target.

### Next recommendation after P4

Proceed to **P5 — GUI characterization tests**, not visual redesign.

---

## 9. P5 — GUI characterization tests

**Purpose:** Freeze semantic behavior before changing visual composition.

### Test categories

#### Facade parity

- `write_log` reaches the same output seam;
- state updates map to the same semantic state;
- `show_content` preserves bounded title/text behavior;
- callbacks and properties retain compatibility;
- camera and API-key methods delegate to existing owners.

#### Input

- one submit emits one command;
- predictive `Tab` behavior remains intact;
- `Shift+Enter` behavior remains intact if retained;
- `Escape` preserves interrupt/clear/close order;
- typed commands do not enter the voice audio owner.

#### Stage

- `EMPTY → LOADING → ACTIVE` is preserved;
- failed readiness becomes `ERROR`;
- panel toggling remains single-owner;
- crossfade does not leave stale active content;
- rapid toggles do not leave stale animation state.

#### Task and approval

- task snapshot is rendered from the global registry;
- cancellation delegates to existing dispatch/registry owner;
- recovery records remain non-running;
- confirmation and cancellation resolve one pending request;
- no second task or speech owner is created.

#### Thread boundary

- BUS UI subscribers run through `drain_ui`;
- worker failures remain bounded;
- rendering failure does not terminate worker behavior.

### P5 gates

- pure tests pass;
- Qt offscreen tests pass where available;
- relevant existing UI tests pass;
- no new provider/network/audio/browser calls from view fixtures;
- FROZEN verifier passes.

### Next recommendation after P5

Proceed to **P6 — presentation adapter with the legacy shell**, preserving current visuals.

---

## 10. P6 — Presentation adapter with legacy shell

**Purpose:** Prove that semantic routing can be separated from visuals before introducing the modern skin.

### Implementation

Add the smallest possible presentation boundary from [GUI_EVOLUTION_PLAN.md](GUI_EVOLUTION_PLAN.md):

- semantic view port;
- intent objects or equivalent narrow callbacks;
- adapter around the current shell;
- no new business logic;
- no second BUS subscription set;
- no second task registry or stage.

The legacy shell remains the default and should look unchanged.

### P6 gates

- all P5 tests remain green;
- command route count is unchanged;
- task refresh count is unchanged;
- confirmation/cancel count is unchanged;
- old facade compatibility tests pass;
- source diff is limited to adapter/wiring/test files;
- rollback is removing the opt-in boundary, not reverting unrelated work.

### Next recommendation after P6

Proceed to **P7 — pure presentation state projector and intent controller**.

---

## 11. P7 — State projector and intent controller

**Purpose:** Give both legacy and modern shells the same bounded semantic input.

### State model

Keep only non-secret, presentation-relevant values:

- assistant state;
- stage name/status;
- task summaries and progress;
- recent bounded user-visible logs;
- boot health labels;
- notification data;
- focus/awareness flags;
- mute and approval state.

Exclude:

- API keys and tokens;
- cookies, URLs where not needed for display, DOM, raw command lines;
- secret paths;
- provider client objects;
- worker threads or task executors.

### Projector rules

- deterministic event-to-state mapping;
- bounded collections;
- safe redaction;
- no Qt dependency in the pure projector;
- replaying the same event sequence gives the same semantic state;
- stale events cannot overwrite newer terminal state without an explicit rule.

### Controller rules

- maps UI intents to existing owners;
- does not call providers directly;
- does not create tasks directly;
- does not own voice or browser lifecycle;
- returns explicit failure when an owner is unavailable.

### P7 gates

- pure projector tests pass;
- intent tests prove one delegation per intent;
- secret-redaction tests pass;
- legacy shell still passes P5 parity tests;
- no GUI widget imports business executors.

### Next recommendation after P7

Proceed to **P8 — modern shell behind a feature flag**.

---

## 12. P8 — Modern shell behind a feature flag

**Purpose:** Change visual identity without changing semantic ownership.

### First visual slice only

Implement only:

- shell geometry;
- header/status treatment;
- command rail;
- stage host;
- task summary;
- notification surface.

Do not migrate every panel at once. Reuse existing stage/panel widgets where safe.

### Feature flag

Use one explicit configuration switch with safe default:

```yaml
ui:
  shell: legacy
  modern_shell:
    enabled: false
    fallback_to_legacy: true
```

The exact key may follow repository convention, but there must be one source of truth.

### Rollback behavior

- modern construction failure logs a bounded diagnostic;
- Jarvis falls back to legacy shell;
- worker and voice initialization are not repeated;
- no second browser, task, or audio owner is created;
- changing the flag restores legacy operation.

### P8 visual acceptance

Check:

- empty/loading/active/error states are distinct;
- state is not color-only;
- reduced-motion mode is respected;
- accessibility names remain present;
- long text and error details remain readable;
- no secret material appears in labels or tooltips;
- resize and close paths remain bounded.

### Next recommendation after P8

Proceed to **P9 — dual-shell semantic acceptance and separately authorized operational check**.

---

## 13. P9 — Dual-shell acceptance and operational check

**Purpose:** Prove that legacy and modern shells consume the same semantics.

### Semantic parity run

Feed both shells the same fake sequence:

```text
boot.check
state LISTENING
SubmitText
intent
 task.submitted
 task.updated
 task.finished
 notify
 stage LOADING
 stage ACTIVE
 confirm
 cancel
 error
 close
```

Compare:

- emitted intents;
- command submission count;
- displayed semantic state;
- task cancellation calls;
- log entries;
- stage transitions;
- approval resolution;
- cleanup calls.

### Operational approval

After offline parity passes, request a separate approval for a narrow local GUI run. Do not combine it with Gemini Live, provider, browser, camera, or hardware validation unless separately approved.

Observe only:

- shell selected;
- boot completes or degrades honestly;
- one text command path;
- task status display;
- panel toggle;
- close and rollback behavior.

### P9 gates

- both shells pass semantic parity;
- legacy remains runnable;
- modern failure falls back;
- no ownership duplication;
- operational evidence is labeled narrowly;
- no `live-proven` claim from GUI observation.

### Next recommendation after P9

Proceed to **P10 — controlled default promotion** only if the user wants the modern shell to become default.

---

## 14. P10 — Default promotion and retirement policy

Promotion is not automatic.

### Promotion checklist

- focused and relevant regressions pass;
- no duplicate executor/task/speech/browser owner;
- startup fallback tested;
- rollback tested;
- legacy shell remains available;
- documentation updated;
- user approves changing the default flag.

### Retirement checklist

Do not remove the legacy shell until:

- an explicit retirement plan exists;
- an observation window has completed;
- no rollback dependency remains;
- FROZEN and compatibility boundaries are reviewed;
- the user separately authorizes deletion or retirement work.

### Next recommendation after P10

Run a final acceptance matrix across executor, documents, tasks, GUI, browser, and voice. Keep Fase 35 paused unless a concrete residual causes a product failure.

---

## 15. Optional Fase 35 reopening

Fase 35 is not a prerequisite for GUI redesign.

Reopen it only when a residual causes an observed product problem. The authorization request must name:

- exact file and line/block;
- Ruff code;
- user-visible failure;
- preserved fallback/control flow;
- telemetry event;
- offline test seam;
- expected raw delta;
- explicit exclusions that remain closed.

Do not reopen it merely to reduce the count from 131. Do not touch the `quiet.swallowed()` self-guard, FROZEN files, user-dirty paths, provider/browser/network/remote, credential/keyring, voice/audio, camera/hardware, GUI/system-control, Telegram/WhatsApp, or `game_updater.py` without separate authorization.

---

## 16. Phase handoff protocol

At the end of every completed task, write these five items:

1. **What changed** — exact files and symbols.
2. **What was measured** — tests, lint, compile, FROZEN, or runtime checks.
3. **What did not run** — provider, network, browser, audio, camera, hardware, or live evidence intentionally skipped.
4. **What remains unfinished** — residual failures, exclusions, or blocked gates.
5. **Next recommendation** — one concrete next phase, not a broad list.

The next recommendation must be dependency-aware:

- after P0 → P1;
- after P1 → P2;
- after P2 → P3 if incomplete, otherwise P4;
- after P3 → P4;
- after P4 → P5;
- after P5 → P6;
- after P6 → P7;
- after P7 → P8;
- after P8 → P9;
- after P9 → P10 only with explicit promotion intent;
- after P10 → final acceptance and optional Fase 35 review.

If a gate fails, the next recommendation is to diagnose and repair that gate—not to advance.

---

## 17. Immediate next step

Do not begin visual GUI implementation yet.

The next safe task is:

> **P1-A — read-only executor/classifier route audit and acceptance matrix.**

It should verify the current route behavior and identify one offline-testable seam, without changing source, invoking providers, reading credentials, or starting live sessions. After that audit, propose one exact RED-first boundary and wait for explicit authorization.
