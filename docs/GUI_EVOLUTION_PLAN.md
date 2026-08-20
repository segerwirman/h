# Jarvis GUI Evolution Plan

**Status:** Prepared for future implementation; no GUI redesign is implemented by this document.

**Purpose:** Allow Jarvis's visual interface to change substantially without changing command execution, task ownership, document behavior, voice/audio ownership, browser lifecycle, persistence, or safety boundaries.

**Scope:** Future presentation-layer work in the PyQt6 Mark XLIX lane. The existing legacy `ui.py` / `main.py` lane remains a separate compatibility boundary.

---

## 1. Design intent

The future work is a **GUI skin migration, not a GUI rewrite**.

The new visual identity may change:

- composition and spacing;
- typography;
- colors and theme presets;
- panel arrangement;
- visual density;
- motion language;
- status presentation;
- navigation affordances.

It must not change the owners of:

- typed-command routing;
- native-agent execution;
- task registry and task ledger;
- document coordination;
- voice input, speech queue, or barge-in;
- browser/CDP lifecycle;
- provider and credential access;
- vision process ownership;
- event publication contracts;
- shutdown and recovery behavior.

The central rule is:

> A view may render state and emit user intent; it may not become the owner of the work that follows.

---

## 2. Existing architecture to preserve

The current Mark XLIX UI is PyQt6-based. The main composition root is `jarvis/ui/window.py`, where `MainWindow` combines these responsibilities through mixins:

- `WindowLayoutMixin` — geometry, stage synchronization, hotkeys, overlays;
- `WindowPanelsMixin` — content panels, sheets, approvals, remote proposals;
- `WindowVoiceMixin` — speech, interruption, voice state;
- `CommandRoutingMixin` — typed command routing and executor selection;
- `CommandActionsMixin` — action workers and user-visible results;
- `WindowPanelsMixin` / `WindowVoiceMixin` — existing integration seams.

Important existing seams:

- `jarvis/ui/stage.py` — `ContentStage` owns one active visual payload and readiness states: `EMPTY`, `LOADING`, `ACTIVE`, `ERROR`.
- `jarvis/ui/task_wiring.py` — attaches task deck, task strip, progress arc, recovery hydration, and BUS refreshes.
- `jarvis/ui/actionpanel.py` — existing action buttons and signals. Treat it as a compatibility surface; avoid structural rewrites.
- `jarvis/ui/window_widgets.py` — `CommandBar`, text input, typed-action helpers, API-key sheet, and widget-level contracts.
- `jarvis/agent/adapters/ui.py` — agent-to-UI bridge. It uses weak references, `write_log`, BUS confirmation/cancellation, progress narration, image presentation, and native actions.
- `jarvis/core/bus.py` — thread-safe event transport; UI subscribers are marshalled through `BUS.drain_ui()` on the Qt thread.
- `jarvis/ui/theme.py` — palette and font token loader with runtime theme support.
- `config.yaml` — window dimensions, zones, motion, themes, action icons, hotkeys, overlays, and task-deck behavior.

The design plan must preserve these contracts even if their visuals are replaced.

---

## 3. Contract inventory

Before implementation, create a versioned contract inventory. It should document the following without changing behavior.

### 3.1 Window facade contract

The facade used by legacy and agent code must continue to provide or delegate:

- `write_log(text)`;
- `set_state(state)` or equivalent state seam;
- `show_content(title, text)`;
- `show_camera_frame(...)`;
- `start_camera_stream()` / `stop_camera_stream()`;
- `get_camera_snapshot(...)`;
- `start_speaking()` / `stop_speaking()`;
- `wait_for_api_key(...)`;
- `prompt_reconfig()`;
- `on_text_command`, `on_remote_clicked`, and `on_interrupt` callback properties;
- mute and current-file compatibility properties where still consumed.

The modern shell must receive an adapter implementing the same semantic port. It must not force callers to know whether the active shell is legacy or modern.

### 3.2 Input contract

The command input view may change appearance, but it must preserve:

- one submitted text value per user submission;
- `Shift+Enter` multiline behavior if retained by the current input contract;
- predictive ghost acceptance through `Tab` if enabled;
- `Escape` semantics: interrupt first, then clear/close according to the existing contract;
- no direct provider/network call from a widget;
- no second route into the voice pipeline.

The input view emits an intent such as `SubmitText(text)`. The existing command owner performs routing.

### 3.3 Event contract

Treat existing BUS topics as compatibility interfaces. At minimum, inventory handlers for:

- `log`;
- `boot.check` and `boot.done`;
- `vision.frame`, `vision.object`, `vision.gesture`, `vision.status`;
- `notify`;
- `intent`;
- `confirm` and `cancel`;
- `sentiment.updated`;
- `remote_setup.pending`, `remote_proposal.pending`, `voice_proposal.pending`;
- task topics: `task.submitted`, `task.updated`, `task.finished`;
- focus and awareness topics where enabled.

Do not rename, repurpose, or duplicate topics merely to suit a new layout. If a new presentation event is needed, add a narrow adapter-level event rather than changing the producer contract.

### 3.4 ContentStage contract

`ContentStage` remains the single visual payload owner for stage content:

- `register(name, widget)`;
- `begin_loading(name)`;
- `activate(name)`;
- `toggle(name)`;
- `fail_loading(message)`;
- `hide_all()`;
- `current`, `status`, `is_loading(name)`, and `registered_names`;
- `status_changed`.

A new shell may wrap or compose the stage, but it must not create a second stage with independent readiness state.

### 3.5 Task contract

`task_wiring.install()` remains the only UI wiring owner for task strip/deck/progress presentation. The GUI must not create a second task registry, ledger, worker, cancellation path, or recovery path.

The visual layer may render:

- queued/running/completed/failed/cancelled state;
- progress and active count;
- recovery records;
- task history.

It must call existing cancellation and navigation seams rather than implementing task control itself.

### 3.6 Voice and safety contract

The GUI must not own:

- microphone capture;
- TTS playback;
- speech queue;
- barge-in detection;
- voice reconnect/recovery;
- camera capture;
- emergency stop.

The GUI can display their state and emit a bounded intent to the existing owner. Any visual interruption button must delegate to the current `on_interrupt` / interrupt seam.

---

## 4. Target architecture

Introduce a presentation boundary around the existing window incrementally. Do not move all code at once.

```text
+---------------------------+
| Legacy shell / New shell  |
|   widgets and layout      |
+-------------+-------------+
              |
       JarvisViewPort
              |
+-------------v-------------+
| Presentation controller   |
| state projection + intents|
+-------------+-------------+
              |
       existing owners
              |
+-------------v-------------+
| router / dispatch / tasks |
| docs / voice / browser    |
| BUS / persistence         |
+---------------------------+
```

### 4.1 Proposed modules

Add these only when implementation begins and only after the contract inventory is approved:

```text
jarvis/ui/presentation/
    __init__.py
    ports.py              # semantic view/input/output protocols
    models.py             # immutable presentation state snapshots
    intents.py            # UI intents, no business execution
    projector.py          # BUS/domain events -> UiState
    controller.py         # delegates intents to existing owners
    shell_registry.py     # explicit legacy/modern shell selection

jarvis/ui/skins/
    __init__.py
    legacy_shell.py       # adapter around current MainWindow composition
    modern_shell.py       # future visual implementation
```

Names are provisional. Do not create these files during the planning stage.

### 4.2 `JarvisViewPort`

Define a small semantic port, preferably as `Protocol` or a narrow adapter class. Example responsibilities:

```python
class JarvisViewPort(Protocol):
    def write_log(self, text: str) -> None: ...
    def set_status(self, state: str) -> None: ...
    def show_content(self, title: str, text: str) -> None: ...
    def show_notification(self, title: str, body: str) -> None: ...
    def show_task_snapshot(self, snapshot) -> None: ...
    def request_confirmation(self, question: str, options=None) -> None: ...
    def close_content(self) -> None: ...
```

The exact methods must be derived from the contract inventory. Avoid putting provider, filesystem, browser, or audio methods into the port. Those belong to existing services.

### 4.3 Immutable presentation state

Create a state model for rendering only. It should contain bounded, non-secret values such as:

- assistant state (`IDLE`, `LISTENING`, `THINKING`, `SPEAKING`, `EXECUTING`, `ERROR`);
- content stage name/status;
- active task summaries and aggregate progress;
- latest user-visible log entries;
- boot subsystem statuses;
- notification queue;
- focus/awareness flags;
- mute state;
- connection/degraded labels;
- active approval request metadata without credentials.

Do not place API keys, OAuth tokens, cookies, DOM content, raw subprocess arguments, or full sensitive paths in presentation state.

The projector should be deterministic and unit-testable without Qt. The shell subscribes to state snapshots and renders them.

### 4.4 Intent model

User actions become explicit intents, for example:

- `SubmitText(text)`;
- `Interrupt()`;
- `TogglePanel(name)`;
- `OpenTask(task_id=None)`;
- `CancelTask(task_id)`;
- `Confirm()` / `Cancel()`;
- `ToggleMute()`;
- `UploadFile(path)`;
- `OpenSettings()`;
- `SetFocusMode(active)`.

The controller maps each intent to an existing owner. The renderer never imports provider clients or calls network/browser/audio APIs.

---

## 5. Visual direction for the future redesign

The current identity is minimal-cinematic: a dark base, cyan/gold-capable theme presets, a central orb, monospaced utility text, a single ContentStage, and edge drawers. Preserve the recognizable behavioral hierarchy while allowing a new visual treatment.

### Design plan

**Palette — “instrument panel at night”**

- `#071018` — deep blue-black ground; softer than pure black for long sessions.
- `#101D28` — raised panel surface; enough separation without card-heavy UI.
- `#D7F3F7` — primary text; cool, high-contrast reading color.
- `#2FD5D0` — active signal accent; reserved for interaction and live state.
- `#D9A85C` — deliberate secondary marker for provenance, attention, and completed work.
- `#E56B6F` — semantic alert only; never use the accent to mean danger.

**Type**

- Display/status: existing `Rajdhani` token or a future approved condensed display face, used only for short labels and state words.
- Body/UI: a readable system sans fallback stack (`Segoe UI`, `Arial`, sans-serif) for settings, explanations, and longer messages.
- Utility/data: existing `JetBrains Mono` / `Consolas` fallback for timestamps, task IDs, event labels, and telemetry-like values.

Do not replace typefaces globally in the first GUI slice. Add tokens and apply them to the new shell only, then compare against the legacy shell.

**Layout**

Use a calm instrument-panel composition: one dominant operational surface, a compact command/input rail, a persistent but quiet status spine, and drawers that open only when detail is requested. Prefer a 12-column or two-region grid inside the new shell; avoid duplicating every function as a card. The central stage remains the single payload surface, while task progress and alerts use bounded peripheral regions.

The visual risk should be spent on one place: the status/orb treatment or equivalent primary signal, not on gradients, rounded cards, or animation everywhere. Motion remains subordinate to readiness and task state.

### Visual rules

- Semantic colors (`success`, `warning`, `alert`) remain separate from the identity accent.
- State must be visible through label, shape, or icon treatment, not color alone.
- Loading must not look like active/ready content.
- Empty, loading, active, and error stage states remain visually distinct.
- Reduced-motion mode must disable or simplify decorative animation.
- The modern shell must not hide errors behind visual polish.
- No widget should expose secret material in labels, tooltips, logs, screenshots, or accessibility text.

---

## 6. Feature flag and rollback

Do not make the new shell the default on its first implementation.

Proposed configuration, to be added only during implementation:

```yaml
ui:
  shell: legacy
  modern_shell:
    enabled: false
    fallback_to_legacy: true
```

Rules:

1. `legacy` remains the default until the modern shell passes offline and operational acceptance.
2. Shell selection occurs once at startup; it does not alter executor/provider configuration.
3. If modern shell construction fails, log a bounded event and construct the legacy shell.
4. A rendering exception must not terminate the worker or voice pipeline.
5. The rollback path is changing the shell flag, not deleting the old implementation.
6. The modern shell may be enabled in a separate profile or command-line opt-in before becoming default.

The final configuration keys may use a different name if the existing config conventions require it. Do not add a second competing flag system.

---

## 7. Phased implementation plan

### GUI-0 — Read-only contract audit

Deliverables:

- public `JarvisUI` and `MainWindow` facade inventory;
- mixin ownership map;
- BUS topic and UI subscriber matrix;
- ContentStage registered panel matrix;
- task wiring and cancellation map;
- voice/audio/camera/browser ownership map;
- FROZEN and user-dirty exclusion list;
- characterization test list;
- proposed adapter boundary.

No source edits except an approved plan artifact.

### GUI-1 — Characterization tests

Add offline tests around existing seams before visual changes:

- `JarvisUI` facade parity;
- command submission and callback forwarding;
- state mapping and log delivery;
- ContentStage readiness transitions;
- action-panel signal contracts;
- task deck install, refresh, cancellation, and recovery display;
- BUS UI-thread delivery;
- confirmation/cancellation flow;
- Escape/mute/fullscreen behavior;
- no direct provider/network/audio invocation from presentation fixtures.

Use fake services, fake BUS payloads, Qt offscreen mode where needed, and `--basetemp` outside the repository.

### GUI-2 — Presentation adapter with legacy shell

Introduce the semantic port/controller while keeping the current visuals. The adapter should delegate to the existing `MainWindow` and mixins. This proves the boundary without changing the appearance.

Acceptance:

- existing UI tests remain green;
- no duplicate BUS subscribers;
- no duplicate task refresh callbacks;
- no change in command routing or callback count;
- FROZEN verifier remains unchanged.

### GUI-3 — State projector and intent controller

Move only presentation projection into pure, testable modules. Keep domain owners in place. Verify that replaying the same event sequence yields the same bounded `UiState` snapshot.

Do not move voice, browser, document, provider, or task ownership into the projector.

### GUI-4 — Modern shell, feature-flagged

Implement the new layout as another shell consuming the same port/state/controller. Reuse `ContentStage`, task registry snapshots, and existing overlays where practical. Do not copy business logic from `MainWindow` into the new shell.

First visual slice should include only:

- shell geometry;
- header/status treatment;
- command rail;
- stage host;
- task summary;
- notification surface.

Add secondary panels one at a time.

### GUI-5 — Dual-shell offline acceptance

Run the same scripted fake interactions through both shells and compare semantic results:

- submitted commands;
- emitted intents;
- displayed task states;
- log entries;
- confirmation requests;
- content-stage transitions;
- close/interrupt behavior.

Pixel-level comparison is optional and must not replace semantic comparison.

### GUI-6 — Operational opt-in

Only after offline acceptance:

- start the modern shell in an explicitly approved opt-in mode;
- observe boot, text command, task status, panel navigation, close, and recovery;
- do not combine this with Gemini Live, provider, camera, browser, or credential validation unless separately authorized;
- record only the evidence actually observed;
- keep legacy rollback immediately available.

### GUI-7 — Default promotion

Promote the modern shell only after a defined observation window with no ownership regressions. Keep the legacy shell available for rollback until a later, separately approved retirement decision.

---

## 8. Test strategy

### Pure tests — no Qt required

- event-to-state projection;
- state bounding/redaction;
- intent validation;
- shell selection and fallback policy;
- semantic parity fixtures;
- stage state transitions as model behavior;
- task snapshot aggregation.

### Qt offscreen tests

- shell construction;
- signal wiring count;
- command submission exactly once;
- action buttons emit the intended intent;
- status and error rendering;
- resize and reduced-motion behavior;
- close cleanup;
- modern-shell construction failure falls back to legacy.

Use `QT_QPA_PLATFORM=offscreen` where compatible and an external pytest `--basetemp`.

### Regression suites

Retain and run relevant existing tests, including:

- `tests/test_ui_facade_parity.py`;
- `tests/test_ui_facade_wiring.py`;
- `tests/test_window_integration.py`;
- `tests/test_stage_toggle.py`;
- `tests/test_task_deck_ui.py`;
- `tests/test_bus_ui_delivery.py`;
- `tests/test_actionpanel_toggle.py`;
- `tests/test_action_hint_and_back.py`;
- `tests/test_voice_input_owner.py`;
- `tests/test_voice_interrupt_event.py`;
- `tests/test_task_speech_ownership_characterization.py`;
- document lifecycle and executor acceptance tests.

Evidence labels:

- Offline fake/Qt tests: `focused-tested`.
- Wiring proven by tests: `runtime-wired`.
- A real GUI process observation: `endpoint-reachable` or a narrowly named operational label as appropriate.
- Never claim `live-proven` for a visual test or a fake provider.

---

## 9. Boundaries and prohibited shortcuts

Do not use a GUI redesign to:

- modify FROZEN `main.py`, `ui.py`, `jarvis/core/wake.py`, `jarvis/ui/theme.py`, or `jarvis/ui/orb.py` without a separate decision;
- rewrite `MainWindow` and all mixins in one commit;
- duplicate command routing or executor calls in new widgets;
- create a second task registry, task ledger, worker, or cancellation path;
- create a second voice/audio/input owner;
- create a second browser/CDP owner;
- bypass `BUS` and call worker objects directly from widgets;
- read provider credentials in presentation modules;
- store secrets in UI state or config;
- call network/provider/browser/audio/camera/hardware from offline GUI tests;
- use screenshots or pixel similarity as the only proof of behavior;
- delete the legacy shell before a rollback window and explicit retirement decision.

Treat [jarvis/agent/adapters/ui.py](../jarvis/agent/adapters/ui.py) as a compatibility boundary. The new shell should consume the adapter contract; it should not change agent ownership or confirmation semantics.

---

## 10. File strategy

### Likely additions during implementation

- `jarvis/ui/presentation/ports.py`;
- `jarvis/ui/presentation/models.py`;
- `jarvis/ui/presentation/intents.py`;
- `jarvis/ui/presentation/projector.py`;
- `jarvis/ui/presentation/controller.py`;
- `jarvis/ui/presentation/shell_registry.py`;
- `jarvis/ui/skins/legacy_shell.py`;
- `jarvis/ui/skins/modern_shell.py`;
- focused tests under `tests/test_gui_presentation_*.py`;
- a focused visual acceptance document after implementation.

### Existing files likely to be touched narrowly

- `jarvis/ui/window.py` — shell selection/wiring only;
- `jarvis/ui/window_layout.py` — only if layout adapter requires a seam;
- `jarvis/ui/task_wiring.py` — only to expose an existing semantic callback, never to duplicate ownership;
- `jarvis/ui/theme.py` — token additions only, with FROZEN policy respected;
- `config.yaml` — one feature flag and modern-shell tokens;
- tests that characterize current facade behavior.

### Files to treat as protected

- `main.py`, `ui.py`, `jarvis/core/wake.py`, `jarvis/ui/theme.py`, and `jarvis/ui/orb.py` are FROZEN or protected by the current integrity boundary.
- `jarvisfix.md` is user-dirty and must not be overwritten during implementation.
- All currently user-dirty and untracked paths remain preserved and must never be blanket-staged.

If the current FROZEN policy prevents a required token or shell seam, add the seam outside the protected file or request a separate approval. Do not silently modify the manifest or baseline.

---

## 11. Definition of done

The GUI redesign is complete only when:

- modern and legacy shells use the same executor/task/document/voice/browser owners;
- semantic facade tests pass for both shells;
- command submission occurs exactly once;
- task state and cancellation remain correct;
- ContentStage readiness states remain correct;
- confirmation and cancellation remain bounded and single-owner;
- voice/audio, browser/CDP, vision, and provider code are not duplicated in the shell;
- modern-shell construction failure rolls back to legacy;
- reduced motion and accessibility names are present;
- no secrets appear in UI state or logs;
- FROZEN integrity passes;
- focused and relevant regression tests pass with external basetemp;
- operational evidence is reported narrowly and honestly;
- legacy rollback remains available until separately retired.

---

## 12. Recommended first implementation task

When the GUI redesign begins, do **GUI-0 only**:

1. read the current window, mixins, stage, action panel, task wiring, UI adapter, BUS, theme, config, and relevant tests;
2. produce the contract matrix;
3. identify one adapter seam that can be tested without changing the visual output;
4. propose the exact files and expected test delta;
5. wait for explicit authorization before adding the first source/test change.

Do not begin by changing colors, moving widgets, or replacing the window composition. Establish the semantic boundary first; then the visual redesign becomes a controlled skin migration instead of a system-wide refactor.
