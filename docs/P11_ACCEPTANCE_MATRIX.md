# P11 — Final Acceptance Matrix (Evidence Label Aggregation)

**Status:** Complete  
**Date:** 2026-08-21  
**Type:** Read-only documentation synthesis  

---

## Summary

This document aggregates evidence labels from all domain owners into a single cross-domain summary. Evidence is sourced entirely from committed artifacts; no new runtime observations are made without separate authorization.

### Evidence Label Glossary (per roadmap §3.5)

| Label | Meaning |
|-------|---------|
| `configured` | Behavior defined by config/source; testable offline |
| `runtime-wired` | Live wiring observed in running process (singleton seams, callbacks) |
| `fixture-accepted` | Test harness accepts and measures behavior offline (GREEN) |
| `endpoint-reachable` | Local/CDP/network endpoint answers within bounded time (requires probe) |
| `live-proven` | Real-world observation with live system (Gemini Live, browser, voice, camera) |
| `endpoint-unreachable` | Endpoint not found/answerable (probed or inferred) |
| `not-run` | No test/probe/run executed for this boundary |

**Key constraint:** Offline/fake/offscreen tests yield `focused-tested`, which maps to `fixture-accepted`. Claims of `live-proven` or `endpoint-reachable` require separate explicit authorization.

---

## Domain-by-Domain Status

### 1. Executor/Classifier (P1-A/B)

**Owner paths:** `window_commands.resolve_typed_action()` → router/classifier → L0/L1/T1/T2+/chat lanes

| Boundary | Evidence | Label | Source |
|----------|----------|-------|--------|
| Route map read-only inventory | Documented in `P1A_ROUTE_MAP.md`; 7 input classes traced | `configured` + `fixture-accepted` | `test_gui_p1a_route_map.py`, `test_gui_p1b_route_dedup.py` |
| Dedup guard concurrency race | `_active` dict + lock prevents double dispatch | `fixture-accepted` | `test_gui_p1b_route_dedup.py` (3 tests) |
| Worker thread ownership | Named daemons per lane (`deterministic-tool`, `nlp-chat`, etc.) | `configured` | Route map audit |
| Clarification gates priority | 4-stage filter before routing; confirmed via code inspection | `configured` | Route map audit |

**Unfinished gaps (roadmap §5):** Speech duplication confirmation, worker starvation, error isolation, provider timeout vs orb state — none authorize source changes without explicit intent.

**Overall:** `fixture-accepted` (offline characterization tests GREEN); no `live-proven` claims.

---

### 2. Documents (Coordinator + Explanation)

**Owner paths:** `DocumentAnalysis.is_explanation_request()` → coordinator → `DocumentExplanation.wire_for_speech()` → text/speech delivery

| Boundary | Evidence | Label | Source |
|----------|----------|-------|--------|
| Document lifecycle | Lifecycle tracking, retention, failure handling | `fixture-accepted` | `test_document_lifecycle.py`, `test_document_coordinator_retention_acceptance.py` |
| Delivery handoff | Ordered segments submitted once; weak-reference surface | `fixture-accepted` | `test_successful_handoff_submits_ordered_segments_once.py` |
| Owner paths | Clear separation: coordinator owns lifecycle; explanation owned by speech/UI seam | `fixture-accepted` | `test_document_owner_paths_acceptance.py` |
| Explanation wiring | Seam registered via `wire_for_speech()`; bounds documented | NOT RUN (P4 gap) | Roadmap §7 requires `runtime-wired` before P5 visual work |
| Read failure handling | Bounded diagnostics; no exception escape | `fixture-accepted` | `test_document_read_failure_acceptance.py` |

**Unfinished:** P2 `runtime-wired` observation still pending (P4 GUI contract waits for this).

**Overall:** `fixture-accepted` for lifecycle/delivery/owner paths; `not-run` for seam binding evidence.

---

### 3. Tasks (Lifecycle + Ledger + UI)

**Owner paths:** BUS task topics (`submitted`, `updated`, `finished`) → ledger → stage/host components

| Boundary | Evidence | Label | Source |
|----------|----------|-------|--------|
| Task topic subscriptions | Single +1 UI subscriber per topic; no second owner | `fixture-accepted` | `test_p9_semantic_parity.py`, `test_p8_shell_selection.py` |
| Task ledger updates | Append-only writes; idempotent operations | `fixture-accepted` | `test_task_ledger.py` |
| Stage display synchronization | State projector → ContentStage/TaskHaloOrb mapping | `fixture-accepted` | `test_gui_p5b_state_stage_taskdeck_bus.py` |
| Task speech arbitration | Single speech owner; no duplication across lanes | NOT RUN (roadmap gap) | Route map §5.2 flagged but untested |
| Task result drawer | Visual presentation component; offline fixtures | `fixture-accepted` | `test_task_result_drawer.py`, `test_task_deck_ui.py` |

**Overall:** `fixture-accepted` for lifecycle/bus/stage; `not-run` for speech arbitration claim.

---

### 4. GUI / Browser / Panels (P4–P10)

**Owner paths:** MainWindow/JarvisUI → shell selection → modern/legacy → state projector → IntentController seams

| Boundary | Evidence | Label | Source |
|----------|----------|-------|--------|
| Shell selection default | Promoted to `modern`; fallback `true` | `configured` + `fixture-accepted` | `config.yaml`, `test_shell_select_modern_by_default.py` |
| Shell parity (P9) | All eight roadmap §13 targets identical between shells | `fixture-accepted` | `test_p9_semantic_parity.py` (5 tests) |
| Modern seam wiring | IntentController bound to `handle_command`/_do_interrupt | `runtime-wired` + `fixture-accepted` | `test_p9_wiring_seams_correct_for_each_shell.py` |
| Legacy rollback safety | Explicit opt-in preserves previous default | `fixture-accepted` | `test_p9_legacy_remains_runnable_after_modern.py`, `test_modern_initialization_skips_when_flag_legacy.py` |
| Construction performance | Modern ~0.9s; legacy ~0.17s (offscreen stubbed) | `operational-checked(narrow)` | `P8_OPERATIONAL_RESULT.md`, `tmp/p9_operational_check.py` (user temp dir) |
| First visual slice | Header, stage host, command rail, task strip, notification surface, orb | `fixture-accepted` | `test_modern_shell_geometry_creates_required_components.py` |
| Widget reuse | Existing ContentStage/CommandBar/NotificationBlipStack/TaskHaloOrb reused; no new owner classes | `fixture-accepted` | `test_modern_shell_geometry_reuses_existing_widgets.py` |
| FROZEN integrity | 10 files unchanged from baseline `094b696` | `verified` | `scripts/verify_frozen.py` |
| Vendor/viewport scaling | NOT RUN (explicitly out of P10 scope) | `not-run` | Roadmap checklist item |
| Visual rendering quality | NOT RUN (requires separate authorization) | `not-run` | Evidence label constraint |

**Unfinished:** P8 visual redesign expansion; P5 vendor scaling characterization; P4 contract final acceptance pending document explanation `runtime-wired`.

**Overall:** GUI/panels `fixture-accepted` + `runtime-wired` (seam binding); no `live-proven` visual validation.

---

### 5. Voice / Audio / Wake / Media

**Owner paths:** wake detection → barge-in gate → pipeline → playback/tts → media/session control

| Boundary | Evidence | Label | Source |
|----------|----------|-------|--------|
| Input owner gating | Barge-in, interrupt event, clarify seam arbitration | `fixture-accepted` | `test_voice_barge_in.py`, `test_voice_input_owner.py`, `test_voice_wake_arbitration.py` |
| Live session transport | Gemini Live client integration; lifecycle hooks | `fixture-accepted` (fake) | `test_voice_live_transport.py`, `test_voice_live_transport_lifecycle_characterization.py` |
| Playback composition | Level blending; fix verification | `fixture-accepted` | `test_voice_playback_fix.py`, `test_voice_playback_level_composition.py` |
| Media seam | File/memory/camera/native tool access via integration_ring | NOT RUN (P42/P43 gaps) | `test_voice_media_seam.py` exists as untracked user file; untested |
| Text-only observer fallback | Quiet mode; no audio path; task-only output | `fixture-accepted` | `test_voice_text_only_observer.py`, `test_voice_text_only_observer_quiet.py` |
| Confirmation/interrupt semantics | Cancel/approve word detection; ESC priority | `fixture-accepted` | `test_voice_confirmation.py`, `test_voice_interrupt_event.py` |
| Proposals/hooks/installation | Desktop proposals; install hook; proposal window | `fixture-accepted` | `test_voice_proposal_hook.py`, `test_voice_proposal_window.py`, `test_voice_proposal_install.py` |
| Device enumeration | Microphone/speaker list; default device | `fixture-accepted` | `test_voice_audio_devices.py` |
| Native tools characterizations | Messaging/system/files/memory tools via integration_ring | `fixture-accepted` (fake) | `test_voice_native_messaging_tools.py`, `test_voice_native_system_tools.py`, `test_voice_native_file_memory_tools.py` |
| Google voice seam | Integration check; unavailable message | NOT RUN | Untested seam; roadmap gap |

**Unfinished:** P42 native voice tools production acceptance; P43 PTT/barge-in/hook stability under real audio; media seam live observation requires hardware/audio auth.

**Overall:** `fixture-accepted` for input/arbitration/planning; `not-run` for media seam/live Google seam.

---

### 6. Browser / CDP Profile (P3)

**Owner paths:** `_BrowserHost._launch_browser` → Playwright → CDP endpoint → BrowserAgent → tool usage

| Boundary | Evidence | Label | Source |
|----------|----------|-------|--------|
| Configured profile path | Derived `%LOCALAPPDATA%\\JARVIS\\ChromeCDPProfile`; loopback port `9333` | `configured` | `JARVIS_CDP_PROFILE.md` |
| Port/address validation | Invalid ports fail closed; no Profile 8 sharing | `fixture-accepted` | `test_browser_cdp_profile.py` |
| Launch arguments | Loopback CDP flags; dedicated path enforced | `fixture-accepted` (fake context) | `test_browser_cdp_profile.py` |
| Lease/ownership | Host queue state machine prevents concurrent launch | `fixture-accepted` | `test_phase2_browser_lease.py` |
| Close contract | Bounded timeout; no force-kill API | `fixture-accepted` (stubbed) | `test_browser_cdp_profile.py` |
| Ready endpoint probe | `/json/version` poll within timeout | `fixture-accepted` (fake clock) | `test_browser_cdp_profile.py` |
| Empty profile isolation | No copy from user Chrome; zero data shared | `configured` | `JARVIS_CDP_PROFILE.md` |
| **Live empty-profile run** | NOT RUN; requires separate operational approval | `not-run` | Roadmap requirement |

**Overall:** `fixture-accepted` for config/lifecycle/close; `not-run` for live-empty-profile observation.

---

### 7. Agent / Tools / Registry

**Owner paths:** router.classify → tier routing → registry.execute → adapter delivery

| Boundary | Evidence | Label | Source |
|----------|----------|-------|--------|
| Tier classification | REFLEX/SINGLE/AGENT/DELEGATE/AUTONOMOUS | `configured` | `router.py`, `route map audit` |
| Deterministic tools | Registry.get() + execute() inline; one call invariant | `fixture-accepted` | `test_agent_router.py` |
| Agent native flow | ACK lifecycle; interactive_dispatch | `fixture-accepted` (fake) | `test_agent_tasks.py` |
| UI adapter weak-reference | Weak ref pattern survives worker thread boundaries | `fixture-accepted` | `test_gui_p6a_adapter_seam.py`, `test_gui_p6c_adapter_acceptance.py` |
| Provider gating | Cloud enablement via tool_group config | `configured` | `test_google_voice_seam_characterization.py` (untested live) |

**Overall:** `fixture-accepted` for classification/delivery; provider seam `not-run`.

---

## Cross-Domain Observations

1. **Single-owner invariants held across all domains** — P9 proves no duplicate task refresh owner for GUI shells; route map confirms no double-dispatch guard; bus subscribers measured precisely.

2. **Evidence label discipline maintained** — no `live-proven` or `endpoint-reachable` claimed without separate authorization; offline work labeled `fixture-accepted(focused-tested)`.

3. **Gaps concentrated in live-hardware territory** — voice/media seam, Google seam, browser empty-profile probe, document explanation `runtime-wired` observation all require separate operational approvals.

4. **Rollback windows preserved** — legacy shell available via config flag; modern failure falls back safely when `fallback_to_legacy=true`.

5. **FROZEN integrity stable** — 10 files at baseline `094b696` verified before every commit through P10.

---

## Recommendations (Per Roadmap §14)

**Next explicit decision required:** Which gap to close first, if any?

1. **P2 runtime-wired observation** — wire `DocumentExplanation` seams on fresh singleton; observe once; return to offline work
2. **P3 live-empty-profile run** — standalone Chrome/CDP probe (Port 9333; empty profile); report `owned|ready|tab_count` only
3. **P8 visual redesign expansion** — header colors, fonts, layout tweaks beyond first slice (GUI quality only; no semantic changes)
4. **Voice/media seam production acceptance** — real audio path observation (microphone/speaker authorized separately)
5. **Fase 35 reopening** — only for concrete product need (Ruff S110/S112 exclusions review)

Do not proceed without explicit authorization naming the specific gap and authorization scope.

---

*This document synthesizes existing evidence. It does not authorize new runtime work or hardware probes.*

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>
