# Jarvis Maturity, Multi-Provider, and Natural Voice Conversation Implementation Plan

> **For Hermes:** Implement sequentially with strict RED → GREEN → REFACTOR. Keep the active identity of Jarvis: voice-first, interactive, cinematic/orb-based, professional, concise, and context-aware.

**Goal:** Make Jarvis feel like a mature, natural conversational voice agent while hardening OpenAI ChatGPT/Codex OAuth and multi-provider agent routing—without replacing the Jarvis voice identity, wake flow, UI identity, or desktop-assistant behavior.

**Architecture:** Keep the existing `jarvis/agent` loop as the execution core and Gemini Live/Charon as the real-time voice transport. Add a response-composition layer between verified task results and each transport. It produces a short spoken brief, a full display report, and a deterministic fallback. Route its optional naturalizer through a dedicated multi-provider profile; never let it invent task facts. Harden the existing OAuth subsystem instead of creating a second auth stack.

**Tech Stack:** Python 3.11, PyQt6, Gemini Live, OpenAI Responses over existing OAuth PKCE, `openai` SDK, Anthropic SDK, secure `secrets_store`, SQLite/FTS5, pytest.

---

## Non-negotiable identity constraints

- Preserve voice-first interaction, wake/activation, interruption behavior, the Jarvis orb, desktop control, and the J.A.R.V.I.S. persona.
- Do **not** replace Gemini Live/Charon in the first milestone. The work changes what Jarvis says and how it coordinates response delivery—not the real-time audio engine.
- Do **not** collect, type, log, display, or commit OAuth tokens/API keys. Existing `secrets_store` remains the only token store.
- Do **not** silently downgrade a heavy agent task to Gemini/light chat. Heavy routing stays explicit and must degrade honestly when no heavy provider is ready.
- Keep safety prompts, destructive-action confirmations, and failures fact-first. Natural wording may wrap verified facts, never alter them.

## Current verified baseline

- Official boot path: `python -m jarvis.main`; it starts the modern UI/services and runs the legacy `main.JarvisLive` voice seam in a background thread.
- `jarvis/integrations/openai_oauth.py` already implements PKCE loopback, encrypted token storage, refresh, and Codex Responses normalization.
- `jarvis/agent/providers.py`, `llm_client.py`, and `model_routing.py` already implement provider metadata, OAuth selection, light/heavy routing, and fallback candidates.
- The monotony source is concrete: `main.py:_dispatch_native_agent()` sends ACK and completion through `_exact_instruction()` (“Ucapkan … PERSIS”), while `interaction.py` has short fixed ACK templates. Existing tests intentionally assert `PERSIS`.
- `core/prompt.txt` asks for conversational Jarvis behavior, but the fixed delivery seam overrides that goal for native-agent callbacks.

---

## Phase 0 — Freeze a safe baseline and define success metrics

**Objective:** Make the work measurable before changing behavior.

**Files:**
- Create: `docs/JARVIS_CONVERSATION_ACCEPTANCE.md`
- Modify: `MIGRATION_NOTES.md`
- Test: existing targeted tests listed below

### Tasks

1. Document the current voice/agent boundary: `jarvis/main.py` → `main.JarvisLive` → `jarvis.agent.dispatch` → `jarvis.agent.loop`.
2. Record the source-of-truth rule: `JARVIS_MK50_MASTER_SPEC.md` and the new acceptance document override older bridge-oriented parity notes when they conflict.
3. Define acceptance examples in Indonesian and English:
   - ACK names the action or intent instead of only saying “Saya kerjakan.”
   - spoken completion is at most two short sentences;
   - UI/Telegram retain the complete verified report;
   - repeated requests do not reuse the same ACK every time;
   - safety/failure claims remain grounded in evidence.
4. Add a “no secret exposure” acceptance criterion for OAuth/provider tests.

### Baseline validation

```bash
unset PYTHONPATH && python -m pytest -q \
  tests/test_openai_oauth.py tests/test_phase6_secrets_oauth.py \
  tests/test_providers.py tests/test_phase3_model_routing.py \
  tests/test_phase2_interactivity.py tests/test_phase2_ingress.py \
  tests/test_voice_routing_integration.py
```

Expected: current tests pass before any production code changes.

---

## Phase 1 — Harden OpenAI OAuth for agent-grade use

**Objective:** Turn the existing OAuth implementation into a reliable, observable, safe heavy-provider path for Jarvis Agent.

**Files:**
- Modify: `jarvis/integrations/openai_oauth.py`
- Modify: `jarvis/agent/providers.py`
- Modify: `jarvis/agent/llm_client.py`
- Modify: `jarvis/ui/settings_providers.py`
- Modify: `jarvis/ui/panels.py`
- Test: `tests/test_openai_oauth.py`
- Test: `tests/test_providers.py`
- Test: `tests/test_phase6_secrets_oauth.py`

### Tasks

1. **RED:** Add a failing test for a safe OAuth status object with only non-secret fields:
   - `connected`
   - `needs_reauth`
   - `token_refresh_due`
   - `last_error_code`
   - never `access_token`, `refresh_token`, JWT claims, or account identifier.
2. **GREEN:** Add `openai_oauth.status()` and an internal error classifier (`reauth_required`, `rate_limited`, `network`, `provider_rejected`, `unknown`). It must not mutate tokens.
3. **RED:** Add a failing test for one—and only one—forced refresh/retry when the Responses request returns HTTP 401.
4. **GREEN:** Refactor `openai_oauth.chat()` into a small request helper. On 401, force a refresh once, retry the identical request once, then return a typed OAuth error. Never loop indefinitely.
5. **RED:** Add tests that 429, malformed stream, `response.incomplete`, and failed refresh produce actionable non-secret errors.
6. **GREEN:** Normalize those failures in `openai_oauth.py`; `llm_client.LLMClient.chat()` continues returning `ChatResponse(error=...)`, never leaking exceptions to normal callers.
7. Add OAuth capability metadata for `chat`, `tools`, and `streaming` only after tests confirm those behaviors. Do not advertise image, vision, or embeddings through ChatGPT/Codex OAuth.
8. In `ProviderSettingsSheet`, disable API-key and base-URL editing for OAuth providers, show safe connection status, and direct sign-in/sign-out to the existing account panel. Keep model selection editable.
9. Ensure client cache reset happens after login/logout and after a 401 reauth outcome.

### Acceptance criteria

- A signed-in account can be selected as `routing.heavy.provider`.
- An expired token refreshes securely; a 401 retries exactly once.
- A failed reauth tells the user to sign in again without exposing token material.
- No secret appears in `providers.json`, logs, UI status text, or a test assertion.

---

## Phase 2 — Make multi-provider policy explicit and resilient

**Objective:** Give Jarvis a clear role-based provider policy: real-time voice, light conversation, heavy agent work, and auxiliary work.

**Files:**
- Modify: `jarvis/agent/providers.py`
- Modify: `jarvis/agent/model_routing.py`
- Modify: `jarvis/agent/auxiliary.py`
- Modify: `jarvis/agent/llm_client.py`
- Modify: `jarvis/core/settings_service.py`
- Modify: `jarvis/ui/settings_providers.py`
- Modify: `config.yaml` (only non-secret defaults)
- Test: `tests/test_providers.py`
- Test: `tests/test_phase3_model_routing.py`
- Create: `tests/test_provider_policy.py`

### Target role policy

```yaml
routing:
  light:
    provider: gemini
    model: ""
  heavy:
    provider: openai_oauth       # selected only after the user signs in
    model: ""                    # user-selected supported model
    fallback: [openai, anthropic, local]
  conversation:
    provider: auto               # low-latency naturalizer; defaults to light
    model: ""
auxiliary:
  response_composer:
    provider: auto
    model: ""
```

### Tasks

1. **RED:** Add tests for a provider-policy resolver that distinguishes `voice_transport`, `light`, `heavy`, `conversation`, and `auxiliary` roles.
2. **GREEN:** Add a `conversation` resolver to `model_routing.py`; it defaults to the light lane and may use an explicit configured provider/model.
3. Extend provider capability handling with normalized booleans/labels for `chat`, `tools`, `streaming`, `vision`, `image`, and `embeddings`. Unknown capability must be treated as unavailable, not assumed.
4. **RED:** Add tests for heavy fallback ordering: explicit heavy → active non-light provider → configured fallback list; unconfigured providers are skipped.
5. **GREEN:** Keep the existing `heavy_candidates()` semantics but expose the selected provider and failover reason in safe telemetry/events.
6. **RED:** Add a test that a provider failure matching quota/rate-limit/timeout causes one fallback attempt and that a semantic/tool-schema failure does **not** indiscriminately switch providers.
7. **GREEN:** Wire the policy into the existing agent loop failover path; preserve the current bounded retry/max-turn guards.
8. Add a Settings summary that states which provider currently serves each role. It must show “not configured” rather than implying readiness.

### Acceptance criteria

- Gemini Live remains the voice transport.
- OpenAI OAuth can be a heavy Agent provider after sign-in.
- OpenAI API key, Anthropic, OpenRouter, local, and custom providers can be fallbacks where their capability profile permits it.
- Heavy tasks never silently run on the light lane.

---

## Phase 3 — Create a response-composition layer instead of reading raw task results

**Objective:** Separate *verified execution result* from *how Jarvis speaks it*.

**Files:**
- Create: `jarvis/agent/conversation.py`
- Modify: `jarvis/agent/interaction.py`
- Modify: `jarvis/agent/interactive_dispatch.py`
- Test: `tests/test_phase2_interactivity.py`
- Create: `tests/test_conversation_delivery.py`

### Design

Introduce typed delivery objects:

```python
@dataclass(frozen=True)
class ConversationDelivery:
    event: Literal["ack", "success", "failure", "chat"]
    display_text: str       # full, user-visible verified report
    speech_text: str        # concise spoken brief, normally <= 2 sentences
    factual_anchors: tuple[str, ...]
    mode: Literal["deterministic", "natural"]
```

`interaction.py` remains the deterministic, never-failing fallback. `conversation.py` owns delivery composition and must be transport-agnostic.

### Tasks

1. **RED:** Test that a success result produces separate full display text and concise spoken text.
2. **GREEN:** Implement deterministic sentence extraction/sanitization. It keeps titles, named entities, paths, URLs, numbers, and explicit failure causes as factual anchors.
3. **RED:** Test repeated acknowledgements with the same task receive distinct variants without changing language or persona.
4. **GREEN:** Track a bounded in-memory recent-template history per session/conversation; avoid the last N templates, but always retain deterministic fallback when choices are exhausted.
5. **RED:** Test that a generic “Done” or empty result never becomes a false success claim.
6. **GREEN:** Reuse `render_success` / `render_failure` as factual fallback; make their spoken output concise rather than merely truncating raw text.
7. Keep full reports available to typed UI and Telegram; do not shorten task evidence just because speech is brief.

### Acceptance examples

- Old: “Baik, sir. Saya kerjakan.”
- Target ACK: “Tentu, sir. Saya cari video terbarunya dan saya putarkan setelah menemukan sumber yang tepat.”
- Old: raw multi-line tool result read aloud.
- Target completion: “Sudah, sir. Video terbaru Deddy Corbuzier dari channel resmi sedang diputar.”

---

## Phase 4 — Add an optional grounded naturalizer for conversational phrasing

**Objective:** Let Jarvis sound alive and context-aware without allowing invented results or slow voice interactions.

**Files:**
- Modify: `jarvis/agent/auxiliary.py`
- Modify: `jarvis/agent/conversation.py`
- Modify: `jarvis/agent/model_routing.py`
- Modify: `core/prompt.txt`
- Modify: `jarvis/core/settings_service.py`
- Test: `tests/test_conversation_delivery.py`
- Create: `tests/test_response_naturalizer.py`

### Tasks

1. Add the wired auxiliary slot `response_composer` to `auxiliary.SLOTS`. It inherits the new conversation route when set to `auto`.
2. **RED:** Test that the naturalizer receives only: task intent, language, persona style, verified result, factual anchors, and bounded recent dialogue—not raw secrets/tool payloads.
3. **GREEN:** Create a small JSON-only naturalizer call using `LLMClient.chat(..., json_mode=True)` with a strict prompt:
   - Indonesian/English matching user input;
   - maximum two sentences for speech;
   - preserve each factual anchor exactly;
   - never claim an action absent from the verified result;
   - do not say “sir” more than once per delivery;
   - use dry Jarvis wit only when it does not obscure information.
4. **RED:** Test malformed JSON, excessive length, changed entity/number, missing factual anchor, or provider timeout.
5. **GREEN:** Validate all naturalizer output. On any invalid/slow/error result, use deterministic `ConversationDelivery`; the user must still receive one answer.
6. Update `core/prompt.txt` with a short delivery policy: internal verified-delivery payloads are spoken naturally, no tag read aloud, facts preserved, concise voice output, no repeated boilerplate.
7. Do not change identity wording globally to mimic Hermes. Jarvis remains formal, responsive, subtly witty, and voice-first.

### Acceptance criteria

- Naturalization is optional and configurable; it does not block a task completion.
- Fallback is deterministic, factual, and immediate.
- The model cannot turn “file not found” into “file fixed,” or omit the actual title/path/number that matters.

---

## Phase 5 — Integrate one delivery lifecycle across voice, desktop, and Telegram

**Objective:** Remove per-transport ad-hoc report rendering and eliminate the monotonic exact-speech seam for ordinary task feedback.

**Files:**
- Modify: `main.py` (`JarvisLive._dispatch_native_agent` only; no broad legacy rewrite)
- Modify: `jarvis/agent/interactive_dispatch.py`
- Modify: `jarvis/ui/window.py`
- Modify: `jarvis/agent/adapters/telegram.py`
- Modify: `jarvis/agent/adapters/ui.py` if typed delivery needs an adapter method
- Modify: `tests/test_phase2_ingress.py`
- Modify: `tests/test_phase2_interactivity.py`
- Modify: `tests/test_voice_routing_integration.py`
- Create: `tests/test_delivery_transports.py`

### Tasks

1. Refactor `interactive_dispatch.start()` to generate one `ConversationDelivery` per ACK/terminal event and dispatch the same object to each transport.
2. Keep callback ordering invariant: one ACK before work, exactly one terminal success/failure, no false ACK if dispatch refuses.
3. Replace `main.py`’s ordinary `_exact_instruction()` calls with an additive `JarvisLive._deliver_agent_feedback()` seam.
4. For ordinary ACK/success, send a `[JARVIS_DELIVERY]` internal payload to Gemini Live containing the already-composed `speech_text`; Gemini Live must speak it naturally and not read the tag.
5. For safety confirmation, destructive action, and error detail requiring exact wording, retain deterministic/verbatim delivery mode.
6. Desktop UI renders `display_text` and stores raw/full result in the activity log; the audio path uses `speech_text`.
7. Telegram uses `display_text` only; it must not be artificially constrained to speech length.
8. Remove tests that assert the literal `PERSIS` instruction for normal Agent ACK/success. Replace them with behavior tests:
   - one reply only;
   - action/result anchors present;
   - natural spoken text is bounded;
   - no internal tag leaked;
   - false success never emitted.

### Acceptance criteria

- Voice no longer repeatedly reads “Baik, sir. Saya kerjakan.” followed by raw output.
- UI, Telegram, and voice agree on facts but are optimized for their medium.
- Existing voice interruption and turn-boundary protections still pass.

---

## Phase 6 — Add real conversational continuity without making Jarvis verbose

**Objective:** Make follow-up dialogue feel connected, not like independent result announcements.

**Files:**
- Modify: `jarvis/agent/session.py`
- Modify: `jarvis/agent/conversation.py`
- Modify: `jarvis/agent/memory_store.py` (only explicit, high-value durable memories)
- Modify: `jarvis/agent/loop.py`
- Test: `tests/test_conversation_delivery.py`
- Create: `tests/test_conversation_context.py`

### Tasks

1. Add a bounded per-session dialogue buffer separate from durable memory: last user intent, last action/result, last spoken delivery, and recent template IDs.
2. **RED:** Test that “lanjutkan”, “yang tadi”, and “buka hasilnya” resolve against the current session context only when unambiguous.
3. **GREEN:** Inject a small conversation context block into light chat and the naturalizer. It must not include raw sensitive tool output by default.
4. **RED:** Test that repeated completion notifications do not repeat the same phrasing or title unnecessarily.
5. **GREEN:** Add concise reference resolution and a “do you want me to continue?” follow-up only when the task naturally has an unfinished next action; never append a question to every response.
6. Write to durable memory only through existing explicit preference/important-context rules; do not store every spoken turn.

### Acceptance criteria

- Jarvis can handle natural follow-ups without becoming chatty.
- It remembers immediate context, but respects privacy and avoids noisy long-term memory.

---

## Phase 7 — Mature the voice experience while preserving the existing audio identity

**Objective:** Make delivery feel like dialogue: short, interruptible, paced, and synchronized with the orb/UI.

**Files:**
- Modify: `main.py` (delivery state hooks only)
- Modify: `core/tts.py` only if the legacy non-Live TTS queue is used by a transport
- Modify: `jarvis/ui/window.py`
- Modify: `jarvis/core/bus.py` only if new events are required
- Test: `tests/test_voice_routing_integration.py`
- Test: `tests/test_phase2_ingress.py`
- Create: `tests/test_voice_delivery_state.py`

### Tasks

1. Emit explicit delivery events: `conversation.delivery_started`, `conversation.delivery_finished`, `conversation.delivery_interrupted`.
2. **RED:** Test barge-in/interrupt cancels the current spoken delivery and prevents a queued completion from speaking afterward.
3. **GREEN:** Bind the new events to existing speaking/listening state and orb transitions; do not update PyQt widgets from worker threads.
4. Split long spoken content at sentence boundaries before delivery; retain a maximum voice budget set in config.
5. Add a user-visible configuration option for response style: `concise`, `balanced`, `briefing`. Do not expose low-level voice-engine changes in this phase.
6. Test that `concise` never drops required factual anchors and that `briefing` leaves the complete detail in the UI.

---

## Phase 8 — Toolsets, capability groups, and a real Tools Browser

**Objective:** Make every capability explicit, inspectable, permission-aware, and safely selectable by surface.

**Files:**
- Create: `jarvis/agent/toolsets.py`
- Modify: `jarvis/agent/registry.py`
- Modify: `jarvis/agent/router.py`
- Modify: `jarvis/agent/dispatch.py`
- Modify: `jarvis/agent/tool_usage.py`
- Create: `jarvis/ui/tools_browser_panel.py`
- Modify: `jarvis/ui/window.py`
- Modify: `jarvis/ui/stage.py`
- Test: `tests/test_toolsets.py`
- Test: `tests/test_tools_browser.py`

### Tasks

1. Define named toolsets: `voice-safe`, `desktop-control`, `research`, `developer`, `messaging`, `automation`, and `admin`.
2. **RED:** Test a tool is visible/executable only when its toolset is enabled for the active surface.
3. **GREEN:** Extend the registry with toolset membership, availability state, confirmation requirement, read-only state, and capability tags. Preserve the current `available()` gate.
4. Wire deterministic defaults: voice uses `voice-safe`; Telegram/gateway uses `messaging`; agent tasks request an explicit allowlist from routing/dispatch.
5. **RED:** Test that a tool can be disabled globally, per toolset, or per ingress surface without deleting it.
6. **GREEN:** Add configuration-backed enable/disable state and audit logs for denied/confirmed calls.
7. Build a read-only-first `ToolsBrowserPanel`: search, category, toolset, availability reason, permission/confirmation badge, usage count, last-used time, parameter schema, and a safe test action only for explicitly testable/read-only tools.
8. Register the panel through `ContentStage`/`window.py` and Command Palette first. Do not refactor the frozen legacy `ui.py`; do not require editing `actionpanel.py` unless an existing additive seam is verified.

### Acceptance criteria

- User can see *why* a tool is unavailable instead of guessing.
- Voice and remote surfaces cannot receive dangerous tools merely because the tool exists.
- Toolsets become the shared contract used later by plugins and platform adapters.

---

## Phase 9 — Skills Browser, Skill Hub, provenance, usage, and curator lifecycle

**Objective:** Finish the Jarvis-native procedural-learning system as a managed, inspectable lifecycle—not just a folder of markdown files.

**Files:**
- Modify: `jarvis/agent/skills.py`
- Modify: `jarvis/agent/skill_usage.py`
- Modify: `jarvis/agent/skill_hub.py`
- Modify: `jarvis/agent/skill_tools.py`
- Create: `jarvis/agent/curator.py`
- Create: `jarvis/ui/skills_browser_panel.py`
- Modify: `jarvis/ui/window.py`
- Modify: `jarvis/ui/stage.py`
- Test: `tests/test_skill_lifecycle.py`
- Test: `tests/test_skill_hub.py`
- Test: `tests/test_skills_browser.py`

### Tasks

1. Make provenance a first-class, validated enum: `bundled`, `hub`, `agent-created`; never infer it from a file path or timestamp.
2. **RED:** Test usage increments only after successful `skill_view`, use, create, update/patch, or install; failed attempts must not inflate usage.
3. **GREEN:** Preserve the existing `.usage.json` sidecar pattern with atomic writes and enrich it with `last_used`, `is_agent_created`, `is_hub_installed`, `pinned`, and lifecycle state.
4. Add an explicit local hub-source registry. Install copies a selected skill into Jarvis skills storage, records source/provenance, validates frontmatter, and never imports `hermes-agent-main` at runtime.
5. **RED:** Test lifecycle transitions: active → stale → archived, with pinned skills bypassing automatic transition and archive never silently deleting source content.
6. **GREEN:** Implement the curator as a scheduled/best-effort review job with dry-run/report mode before enabling automatic archive.
7. Build `SkillsBrowserPanel`: search/filter by category/provenance/lifecycle, inspect frontmatter/body safely, usage counter, pin/disable/archive controls, install/update status, and a clear “agent-created/learned” badge.
8. Ensure disabled/archived skills do not enter the default agent prompt, but remain discoverable through explicit management/search views.

### Acceptance criteria

- The user can distinguish bundled, hub-installed, and Jarvis-learned skills.
- Skills can be safely installed, updated, disabled, pinned, archived, and restored.
- The curator preserves user ownership; it reports before it changes lifecycle.

---

## Phase 10 — Surface management: panels, dashboard, and Session Browser

**Objective:** Add Hermes-grade management surfaces around the orb experience without turning Jarvis into a generic admin app.

**Files:**
- Create: `jarvis/ui/capabilities_panel.py`
- Create: `jarvis/ui/sessions_panel.py`
- Create: `jarvis/ui/provider_health_panel.py`
- Modify: `jarvis/ui/window.py`
- Modify: `jarvis/ui/stage.py`
- Modify: `jarvis/core/command_palette.py`
- Modify: `dashboard/server.py`
- Modify: `dashboard/static/app.html`
- Test: `tests/test_sessions_panel.py`
- Test: `tests/test_capabilities_panel.py`
- Test: `tests/test_dashboard_control_plane.py`

### Tasks

1. Define a small surface registry in `window.py`/`stage.py`: panel id, title, required capability, visibility policy, and event source.
2. **RED:** Test a disabled capability never creates an active panel or a broken command-palette entry.
3. **GREEN:** Register the Tools Browser, Skills Browser, Sessions Browser, Provider Health, and optional Messaging surface through the registry.
4. Implement `SessionsPanel` over existing session/memory/telemetry storage: recent tasks, status, model/provider used, tool-call count, compact result, failure reason, and safe search. Never expose tool secrets or raw auth headers.
5. Implement capability/provider health cards: configured/not configured, active role, fallback order, safe OAuth state, enabled toolsets, and recent failure counts.
6. Evolve the existing web dashboard from remote-control-only toward a **read-only control plane** first: session list, provider health, active toolsets, cron status, and gateway adapter status. Mutating actions remain confirmation-gated.
7. Keep all UI updates thread-safe through the existing EventBus/QTimer or PyQt signal boundary; panels must not import/call blocking agent code from the UI thread.

### Acceptance criteria

- The orb remains the primary home view; management is opt-in via ContentStage/Command Palette.
- Browser panels have a clear ownership boundary: inspect/manage, not silently execute unsafe actions.
- Desktop and web dashboard read the same safe state model.

---

## Phase 11 — Plugin ecosystem and formal multi-platform ingress

**Objective:** Make Jarvis extensible and message-platform-ready without tightly coupling optional integrations to the voice core.

### Workstream A: Trusted local plugin runtime

**Files:**
- Create: `jarvis/plugins/__init__.py`
- Create: `jarvis/plugins/manifest.py`
- Create: `jarvis/plugins/api.py`
- Create: `jarvis/plugins/registry.py`
- Create: `jarvis/plugins/loader.py`
- Create: `jarvis/plugins/builtin/`
- Modify: `jarvis/agent/registry.py`
- Modify: `jarvis/core/command_palette.py`
- Modify: `jarvis/ui/window.py`
- Modify: `config.yaml`
- Test: `tests/test_plugins.py`
- Test: `tests/test_plugin_permissions.py`

#### Tasks

1. Start with **trusted local Python plugins only**. No network marketplace, arbitrary download, or auto-update in the first version.
2. Define a versioned manifest: id, name, version, entrypoint, declared contributions (`tools`, `skill_sources`, `panels`, `commands`, `adapters`), required toolsets, and permissions.
3. **RED:** Test invalid manifests, duplicate ids, disabled plugins, missing entrypoints, and plugins declaring a tool outside their allowed toolset.
4. **GREEN:** Implement a loader that discovers configured local plugin directories, validates the manifest before import, records load errors safely, and supports enable/disable without deleting files.
5. Expose a narrow Plugin API—registration only. Plugins cannot mutate core config/secrets, bypass confirmations, or inject arbitrary UI-thread work.
6. Add a Plugin Manager surface: list, provenance/path, enabled status, declared permissions, load error, and restart/reload requirement.

### Workstream B: Formal platform adapter / ingress architecture

**Files:**
- Create: `jarvis/gateway/__init__.py`
- Create: `jarvis/gateway/base.py`
- Create: `jarvis/gateway/registry.py`
- Create: `jarvis/gateway/service.py`
- Create: `jarvis/gateway/delivery.py`
- Create: `jarvis/gateway/platforms/telegram.py`
- Modify: `jarvis/agent/adapters/telegram.py`
- Modify: `jarvis/agent/dispatch.py`
- Modify: `jarvis/agent/toolsets.py`
- Modify: `jarvis/agent/conversation.py`
- Modify: `config.yaml`
- Test: `tests/test_gateway_registry.py`
- Test: `tests/test_gateway_telegram_migration.py`
- Test: `tests/test_gateway_delivery.py`

#### Tasks

1. Define one transport-neutral inbound/outbound contract: message id, platform, conversation id, sender policy, text/media payload, reply target, delivery result, and idempotency key.
2. **RED:** Test duplicate inbound events are deduplicated and a failed outbound delivery is retried only according to bounded policy.
3. **GREEN:** Migrate the existing Telegram adapter behind `gateway.platforms.telegram` without changing user-visible behavior.
4. Bind each platform to an explicit default toolset and allowed capabilities. A remote ingress must never inherit unrestricted desktop tools.
5. Route all platform responses through `ConversationDelivery`: compact display text for messaging, no voice-only formatting, and consistent factual results.
6. Add gateway status/health events to the dashboard and desktop Messaging surface.
7. Add a second platform only after Telegram migration tests pass and the user selects the priority platform. Do not try to clone every Hermes adapter at once.
8. Allow a plugin to contribute a platform adapter only after the plugin permission model and adapter tests are stable.

### Acceptance criteria

- Plugins are opt-in, manifest-validated, disableable, and capability-bounded.
- Telegram works through the formal adapter contract before any second platform is added.
- Platform ingress is a surface around Jarvis Agent, not a replacement for voice-first Jarvis.

---

## Phase 12 — Final verification, rollout, and rollback

**Objective:** Ship incrementally with measurable quality and immediate rollback switches.

### Validation commands

Run targeted tests after each small RED → GREEN cycle:

```bash
unset PYTHONPATH && python -m pytest -q tests/test_openai_oauth.py tests/test_providers.py tests/test_phase6_secrets_oauth.py
unset PYTHONPATH && python -m pytest -q tests/test_phase3_model_routing.py tests/test_provider_policy.py
unset PYTHONPATH && python -m pytest -q tests/test_phase2_interactivity.py tests/test_conversation_delivery.py tests/test_response_naturalizer.py
unset PYTHONPATH && python -m pytest -q tests/test_phase2_ingress.py tests/test_voice_routing_integration.py tests/test_delivery_transports.py tests/test_voice_delivery_state.py
unset PYTHONPATH && python -m pytest -q tests/test_toolsets.py tests/test_tools_browser.py tests/test_skill_lifecycle.py tests/test_skill_hub.py tests/test_skills_browser.py
unset PYTHONPATH && python -m pytest -q tests/test_sessions_panel.py tests/test_capabilities_panel.py tests/test_dashboard_control_plane.py
unset PYTHONPATH && python -m pytest -q tests/test_plugins.py tests/test_plugin_permissions.py tests/test_gateway_registry.py tests/test_gateway_telegram_migration.py tests/test_gateway_delivery.py
unset PYTHONPATH && python -m pytest -q
```

### Manual acceptance script

1. Sign in through the existing OpenAI OAuth browser flow; confirm no token appears in Settings or logs.
2. Select OAuth as heavy provider and configure a valid heavy model.
3. Give a multi-step voice task. Confirm: concise varied ACK → work continues in background → short natural spoken summary → full UI result.
4. Repeat the same task three times; ACK wording should vary while result facts remain correct.
5. Interrupt Jarvis while speaking; it returns to listening without completing stale speech.
6. Simulate OAuth expiry/401; confirm one refresh/retry and then honest re-login guidance if it fails.
7. Disable the naturalizer; confirm deterministic concise fallback still works.

### Feature flags / rollback

Use non-secret config toggles:

```yaml
conversation:
  naturalizer_enabled: false
  style: balanced
  max_spoken_sentences: 2
  max_spoken_chars: 260
routing:
  conversation:
    provider: auto
    model: ""
```

Rollback order:
1. Disable `conversation.naturalizer_enabled`.
2. Keep the deterministic `ConversationDelivery` layer active.
3. If needed, re-enable legacy exact delivery only for safety/diagnostic purposes—not as normal UX.
4. OAuth failure never blocks use of explicitly configured fallback providers.

---

## Definition of done

- Jarvis remains recognizably Jarvis: voice-first, interactive, professional, succinct, and slightly witty.
- Native Agent tasks no longer force a repetitive exact ACK/raw-result reading pattern.
- Spoken output is short and natural; full verified output remains visible in UI/Telegram.
- OpenAI OAuth is securely stored, safely retryable, observable without secrets, and usable as a heavy Agent provider.
- Multi-provider roles and fallback behavior are explicit, testable, and honest.
- Toolsets govern every surface, and Tools Browser/Skills Browser/Session Browser explain capability state without exposing secrets.
- Skills carry validated provenance (`bundled` / `hub` / `agent-created`), usage telemetry, and curator lifecycle with user-controlled pin/archive behavior.
- Plugins are manifest-validated, opt-in, capability-bounded, and cannot bypass core safety boundaries.
- Telegram is migrated to the formal gateway adapter contract before any additional platform is introduced.
- Every new behavior is implemented test-first and the full regression suite passes.
