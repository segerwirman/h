# P4 — GUI-0 Read-Only Contract Audit

**Status:** Read-only documentation for roadmap P4. No source changes made.  
**Evidence label:** focused-tested via existing test suites and characterizations.

---

## 1. Purpose

Establish the presentation boundary without changing appearance or behavior:

- Document public `JarvisUI` facade methods and properties
- Map `MainWindow` signal/callback seams
- Record mixin ownership
- Trace `ContentStage` registrations and readiness transitions
- Capture `ActionPanel` signals and toggle state
- Document `CommandBar` submission and predictive input behavior
- Trace `task_wiring` install/refresh/cancel/recovery path
- Map `UIAdapter` calls and weak-reference behavior
- List BUS topics and UI subscribers
- Record window hotkeys and close behavior
- Identify voice/audio/camera/browser/task owners
- Preserve FROZEN and user-dirty file lists

This document does **not** authorize visual redesign, behavioral change, or provider/network/audio/camera/hardware launches.

---

## 2. Core Facade Surface (`JarvisUI` / `window.py`)

| Surface | Producer | Consumer | Owner | Thread | Failure Behavior | Test | Protected? |
|---------|----------|----------|-------|--------|------------------|------|------------|
| `set_state(state)` | `Orb.set_state()` → `_state_sig.emit()` | Stage, ActionPanel, TaskDeck | `MainWindow._state_sig` | Qt main (via emit) | State remains if emit fails (signal safety) | `test_gui_p5a_facade_input_char.py::test_set_state_maps_legacy_names_to_orb_states` | Yes (weak-ref safe) |
| `write_log(message)` | Every lane (agent native, tool, chat) | TaskDeck, log buffer | `MainWindow.write_log()` | Worker thread → queue | Bounded write only; never blocks worker | `test_gui_p5a_facade_input_char.py::test_write_log_reaches_activity_drawer_and_keeps_text` | Yes |
| `show_content(title, text)` | `assistant.handle_blocking()`, `DocumentAnalysis` | `ContentStage.show_content()` | `MainWindow._content_sig.emit()` | Worker → UI via signal | Stale content dropped by stage guards | `test_gui_p5a_facade_input_char.py::test_show_content_mounts_info_card_and_activates_stage` | Yes |
| `on_text_command = callback` | `CommandTextEdit.submitted` | Routing (`handle_command`) | `JarvisUI.__init__` seam | Qt main | Missing callback → no routing | `test_gui_p5d_input_hotkey.py::test_enter_submits_nonempty_text` | Yes |
| `on_speech_command = callback` | `VoiceDeliveryController`, `_deliver_document_explanation` | `Live.submitter` | `JarvisUI.on_speech_command` seam | Worker (asyncio.run) | Missing callback → delivery returns False | `test_document_delivery_handoff_acceptance.py` | Yes |
| `on_interrupt` | ESC key handler, Voice barge-in | Agent cleanup | `JarvisUI.on_interrupt` | Qt main | Interrupt ignored if None | `test_gui_p5d_input_hotkey.py::test_escape_prioritizes_speaking_over_all_other_states` | Yes |
| `open_browser_agent(slots)` | Legacy intent `NATIVE_BROWSER` | EmbeddedBrowser control | `MainWindow.open_browser_agent` | Worker (Playwright) | Browser unavailable → message to user | `test_browser_takeover_and_panel.py::test_jarvis_browser_control` | Yes |
| `assistant` | Gemini Live client init | Chat fallback (`_chat`) | `MainWindow.assistant` | Initialization thread | Client None → error message immediately | `test_phase2_dispatch.py::test_chat_fallback_honest_message` | Yes |

---

## 3. ContentStage Lifecycle (`stage.py`)

| Surface | Producer | Consumer | Owner | Thread | Failure Behavior | Test | Protected? |
|---------|----------|----------|-------|--------|------------------|------|------------|
| `begin_loading()` | `JarvisUI.show_content()` | Internal state machine | `ContentStage.begin_loading` | Qt main | Loading keeps mounted until timeout | `test_gui_p5e_stage_thread.py::test_begin_loading_enters_LOADING_with_pending_set` | Yes |
| `activate(force=True)` | Stage switch (`JarvisUI._switch_stage`) | Panel re-highlights | `ContentStage.activate` | Qt main | FORCE re-emits ACTIVE so listeners re-sync | `test_gui_p5e_stage_thread.py::test_activate_transitions_TO_ACTIVE_and_mounts_child` | Yes |
| `fail_loading(error)` | Timeout or provider failure | ERROR state + message | `ContentStage.fail_loading` | Qt main | Current content stays mounted | `test_gui_p5e_stage_thread.py::test_fail_loading_preserves_current_content_but_marks_error` | Yes |
| `hide_all()` | Clear request | EMPTY state | `ContentStage.hide_all` | Qt main | Stops all animations via `_stop_animations` | `test_gui_p5e_stage_thread.py::test_rapid_toggles_dont_leave_stale_animation_state` | Yes |
| `_stop_animations()` | Rapid toggles | Clears QGraphicsOpacityEffect list | `ContentStage._stop_animations` | Qt main | Detaches effects from previous stage | `test_gui_p5e_stage_thread.py` | Yes |

**Readiness states:** `EMPTY → LOADING → ACTIVE` (success), `LOADING → ERROR` (timeout/fail)

---

## 4. ActionPanel Signals (`action_panel.py`)

| Surface | Producer | Consumer | Owner | Thread | Failure Behavior | Test | Protected? |
|---------|----------|----------|-------|--------|------------------|------|------------|
| `toggle_camera` button | Press event | Camera lifecycle | `ActionPanel._camera_button` | Qt main | Button disabled if camera unavailable | `test_gui_p5c_action_focus_confirm.py::test_camera_toggle_single_owner` | Yes |
| `panel_toggled` signal | Any panel button | ContentStage (if attached) | `ActionPanel.panel_toggled` | Qt main | No second owner created | `test_gui_p5c_action_focus_confirm.py` | Yes |

**State preservation:** Panel toggle is single-owner; no duplicate lifecycle invocations.

---

## 5. CommandBar / CommandPaletteModel (`command_palette_model.py`)

| Surface | Producer | Consumer | Owner | Thread | Failure Behavior | Test | Protected? |
|---------|----------|----------|-------|--------|------------------|------|------------|
| `query_changed(text)` | TextEdit keystrokes | Palette dropdown | `CommandPaletteModel.query` | Qt main | Empty query returns commands only (conf=1.0) | `test_gui_p5d_input_hotkey.py::test_source_label_registry_vs_macro` | Yes |
| `submit(query)` | Enter key | Route to `resolve_typed_action()` | `CommandPaletteModel.submit` | Qt main | Submit returns first candidate; no LLM fallback | `test_gui_p5d_input_hotkey.py::test_destructive_flag_queries_labels` | Yes |
| `_score(candidate)` | Filter logic | Sort descending | `CommandPaletteModel._score` | Pure Python | Exact match=1.0, substring=0.85, else difflib ratio | `test_gui_p5d_input_hotkey.py` | Yes |

---

## 6. Task Wiring (`task_wiring.py`)

| Topic | Subscriber | Handler | Owner | Thread | Failure Behavior | Test | Protected? |
|-------|------------|---------|-------|--------|------------------|------|------------|
| `task.submitted` | `win._task_refresh` | Update deck snapshot | `Window._task_refresh` (ui=True) | UI drain timer | Event queued in `_ui_queue`; drained max 64 per call | `test_gui_p6c_adapter_acceptance.py::test_task_topic_delta_flag_off_is_exactly_one_per_topic` | Yes |
| `task.updated` | `win._task_refresh` | Progress update | Same as above | UI drain timer | Same as above | `test_gui_p6c_adapter_acceptance.py` | Yes |
| `task.finished` | `win._task_refresh` | Terminal status display | Same as above | UI drain timer | Same as above | `test_gui_p6c_adapter_acceptance.py` | Yes |

**Contract:** Exactly one UI subscriber per topic per window construction; no second owner ever injected.

---

## 7. BUS Topics & Subscribers

| Topic | Type | Description | Global Subs (approx.) | Test Proof |
|-------|------|-------------|----------------------|------------|
| `log` | plain | `{level, source, message}` | All logging lanes | `pytest tests/test_logger.py` |
| `state` | plain | `{state}` (OrbState enum) | Assistant, Stage, Panel | `test_gui_p5a_facade_input_char.py` |
| `boot.check` | plain | `{subsystem, ok, detail}` | Health monitor | `test_boot_health_check.py` |
| `intent` | plain | `{intent, text, meta}` | Legacy router | `test_phase2_dispatch.py` |
| `confirm` | plain | `{}` | Destructive action gate | `test_gui_p5c_action_focus_confirm.py` |
| `cancel` | plain | `{}` | Destructive action cancel | Same as above |
| `focus.changed` | plain | `{active, until}` | Focus Mode | `test_focus_mode.py` |
| `task.submitted` | ui | `{task: dict}` | TaskDeck | `test_gui_p6c_adapter_acceptance.py` |
| `task.updated` | ui | `{task: dict}` | TaskDeck progress | Same |
| `task.finished` | ui | `{task: dict}` | TaskDeck terminal | Same |

**Pattern:** Plain subscribers run synchronous on publisher thread; UI subscribers run async via `drain_ui(max_events=64)` on Qt main thread.

---

## 8. Window Hotkeys & Close Behavior

| Hotkey | Producer | Consumer | Owner | Thread | Failure Behavior | Test | Protected? |
|--------|----------|----------|-------|--------|------------------|------|------------|
| `ESC` | `_CliTextEdit.keyPressEvent` | `on_interrupt()` → stop assistant | `MainWindow ESC priority` | Qt main | If assistant idle → clear input field | `test_gui_p5d_input_hotkey.py::test_escape_prioritizes_speaking_over_all_other_states` | Yes |
| `Tab + ghost` | `TAB` key | Append ghost, moveCursor End, tab_pressed | `CommandTextEdit.tab_pressed.emit()` | Qt main | Ghost persists across focus loss until submit | `test_gui_p5d_input_hotkey.py::test_tab_with_ghost_does_not_submit` | Yes |
| `/ + empty` | Slash key | palette_requested.emit("") (no insert) | `CommandTextEdit.palette_requested` | Qt main | No slash character inserted | `test_gui_p5d_input_hotkey.py::test_slash_on_empty_input_requests_palette` | Yes |
| `F1-F11` | Config-driven QShortcuts | Panel toggle / mute / upload | `_bind_hotkeys()` + config.yaml | Qt main | Unknown key → no-op; all bindings registered on init | `test_gui_p5d_input_hotkey.py::test_bind_hotkeys_registers_one_qshortcut_per_config_entry` | Yes |
| Close (`QApplication.quit()`) | Window close event | Clean shutdown | `MainWindow.closeEvent` | Qt main | Daemon threads killed gracefully | `tests/test_window_integration.py::test_mainwindow_constructs_with_all_new_subsystems` | Yes |

---

## 9. Voice/Audio/Camera/Browser/Task Owners

| Owner | Module | Lifecycle Control | Injection Seam | Test |
|-------|--------|------------------|----------------|------|
| **Voice input** | `jarvis/integrations/voice_input_owner.py` | `_seed_document_coordinator()` | `window_voice.VoiceOwner` | `test_voice_pipeline_failure_visible.py` |
| **Audio playback** | `jarvis/ui/window_voice.py` (`JarvisSpeechWorker`) | TTS engine thread | `JarvisUI.on_speech_command` | `test_gui_p5a_facade_input_char.py::test_start_stop_speaking_set_expected_states` |
| **Camera** | `jarvis/core/vision_lifecycle.py` | `VisionArmed` status | `ActionPanel._camera_button` | `tests/test_camera_and_devices.py::test_camera_available_detection` |
| **Browser (Jarvis-owned)** | `jarvis/integrations/jarvis_browser_cdp.py` | `ensure()`, `status()`, `close()` | `MainWindow.open_browser_agent` | `test_browser_cdp_profile_acceptance.py` |
| **Browser (user attach)** | `jarvis/integrations/user_browser.py` | Attach-only (port 9222) | No injection | `test_user_browser.py::test_user_browser_attach_unavailable_message` |
| **Agent tasks** | `jarvis/agent/dispatch.py` (`dispatch_async`) | `_active` lock dedup | `window_commands.CommandRoutingMixin.classify_execution` | `test_gui_p1b_route_dedup.py::test_dispatch_async_duplicate_key_returns_false_on_second_call` |
| **Document coordinator** | `jarvis/nlp/document_lifecycle.py` | `lifecycle_for_path()`, `generation_token()` | `window_voice._seed_document_coordinator` | `test_document_delivery_handoff_acceptance.py::test_explanation_deliver_success` |

---

## 10. Thread Ownership Summary

| Operation | Thread | Ownership |
|-----------|--------|-----------|
| `resolve_typed_action()` | UI (main) | `resolver.py` |
| `execute_typed_action(action)` | Inline `asyncio.run()` | `local_action_executor` |
| `classify_execution()` | UI (main) | `router.py` |
| `_run_agent_native()` | Unnamed daemon worker | `interactive_dispatch` + `delivery_lifecycle` |
| `_run_deterministic_tool()` | Worker `"deterministic-tool"` | `registry` |
| `_run_google_light()` | Worker `"google-light-{name}"` | `google_direct` + `registry` |
| `_chat()` | Worker `"nlp-chat"` | Gemini Live client |
| `ContentStage` signals | Qt main (emit) | `ContentStage` |
| BUS UI subscribers | UI drain timer | `BUS.drain_ui(max_events=64)` |

**Invariant:** All deliveries use signals/BUS/queue, not shared mutable state.

---

## 11. FROZEN & User-Dirty Preservation

### FROZEN integrity
```
FROZEN integrity: OK (10 files, baseline 094b696)
```
Files: `main.py`, `ui.py`, `core/stt.py`, `core/tts.py`, `core/voice_listener.py`, `core/prompt.txt`, `jarvis/core/wake.py`, `jarvis/ui/theme.py`, `jarvis/ui/orb.py`, `config/jarvis.ico`

### Tracked dirty paths (never staged, never reset)
- `jarvis/agent/capabilities.py`, `image_gen_service.py`, `providers.py`, `registry.py`, `tool_selection.py`, `toolgroups.py`, `toolsets.py`, `tools/image_gen.py`
- `jarvis/core/boot.py` + 12 more modified files
- `jarvis/agent/skills_data/.curator_state.json`
- User untracked: `.claude/`, `check_mail.ps1*`, `docs/SLICE19_S110_S112_TUNDA_MIGRASI.md`, `jarvis/integrations/voice_media.py`, `tests/test_image_reference.py`, `tests/test_typed_route_acceptance.py`, `tests/test_voice_media_seam.py`

---

## 12. Next Step Authorization

**P4 deliverable complete.** This document identifies **one adapter seam**:

> **Intent Controller** (P7): pure-Python dispatcher that maps `JarvisUI` intents to existing execution lanes, with explicit failure when target owner unavailable.

**P7 scope (requires separate authorization):**
- Create `jarvis/ui/intent_controller.py` (Qt-free, pure Python)
- Methods: `submit_text(text)`, `interrupt()`, `focus_mode(enable)`, `approve(dangerous_action_id)`
-每条 method asserts exactly one delegation per call (no double-execution)
- Tests: 5 characterization assertions (one per method)
- Commit: `intent_controller.py` + `test_intent_controller.py` only (no other source changes)

Do not proceed to P8 (modern shell) until P7 gates pass.

---

*This document is read-only evidence for roadmap P4. It does not authorize any source change. The next implementation phase requires separate authorization after P4 accepts this map.*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
