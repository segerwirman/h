# Jarvis Framework Maturity Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Evolve Jarvis into a native, voice-first but framework-like agent platform with broad tool capability, mature skills/MCP/plugins/cron/memory, secure multi-platform gateway, rich operations control plane, and aggressively optimized legacy helpers—without runtime dependency on Hermes.

**Architecture:** Preserve the existing voice/persona/UI identity and the current native agent seams. Build an additive control plane around a single capability registry: every tool, plugin, MCP tool, scheduled run, and gateway message must pass through shared identity, policy, approval, telemetry, lifecycle, and delivery boundaries. Hermes remains a read-only design reference; `jarvis/integrations/hermes/*` stays disabled by default.

**Tech Stack:** Python 3.11, PyQt6, SQLite/WAL, asyncio/threading boundary adapters, FastAPI dashboard, MCP JSON-RPC stdio then HTTP, platform SDKs/webhooks, pytest, optional Redis only after local SQLite limits are proven.

---

## Executive decision table

| User goal | Feasible? | Correct implementation choice |
|---|---:|---|
| Framework-like Jarvis | Yes | Native modular core; no Hermes runtime bridge |
| More toolsets/capabilities | Yes | Central capability registry + policy/approval gate |
| Mature skill hub | Yes | Local catalog first; signed/approved remote publishing later |
| MCP | Partly exists | Harden existing `jarvis/agent/mcp_client.py`, add lifecycle/policy/catalog |
| Cron | Partly exists | Upgrade existing `jarvis/agent/cron.py` to durable isolated-job model |
| Plugins | Partly exists | Harden `jarvis/plugins/{manifest,loader}.py`; trusted-local first |
| Discord/WhatsApp | Yes | Formal gateway adapters; Discord first, WhatsApp Cloud API second |
| Rich admin/ops plane | Yes | Expand read-only snapshot into RBAC/audited operations API/UI |
| Instant legacy helpers | Local actions: near-instant; network/LLM/browser: no | Persistent clients, caching, direct OS APIs, queues, readiness checks |

## Non-negotiable constraints

1. Keep voice pipeline, TTS/STT/wake-word, persona, orb, theme, and visual identity frozen unless an explicit separate approval says otherwise.
2. Jarvis remains standalone. Do not call `hermes send`, `hermes gateway`, or any Hermes CLI at runtime.
3. Additive seams only. Do not rewrite `jarvis/agent/dispatch.py`, `loop.py`, `router.py`, `registry.py`, existing memory store, or root legacy entry points in one migration.
4. New external actions require identity, allowlist/policy, approval class, timeout, cancellation, audit metadata, and redacted telemetry.
5. Secrets stay in the existing secure store/config references only. Never log plaintext credentials, tokens, webhook secrets, payloads, or browser cookies.
6. Each phase follows: discovery → failing focused test → minimal implementation → focused regression → ad-hoc verifier where needed → docs → approval gate.
7. Use `unset PYTHONPATH && python -m pytest ...`; never use `pytest -n 0` in this workspace.

---

## OpenAI OAuth and image-generation decision

### Current audited state

| Item | Current code | Status |
|---|---|---|
| OAuth login | `jarvis/integrations/openai_oauth.py::start_login()` | Implemented PKCE + loopback callback + encrypted token storage |
| Refresh/retry | `access_token()` and `chat()` | Implemented refresh and one retry on HTTP 401 |
| Agent provider lane | `jarvis/agent/providers.py`, `jarvis/agent/llm_client.py` | OAuth provider exists for chat/tools/streaming |
| Image tool | `jarvis/agent/tools/image_gen.py` | Implemented for Gemini or OpenAI-compatible API-key providers |
| OAuth image use | `tests/test_openai_oauth.py::test_image_oauth_tidak_diiklankan` | Explicitly prohibited by current safety/compatibility contract |

### Required product decision

Do **not** claim that ChatGPT/Codex OAuth automatically entitles Jarvis to call
OpenAI image-generation APIs. The current OAuth lane uses the ChatGPT Codex
backend for chat/tool calls; image generation is intentionally not advertised
there. Image generation must initially use a separate official OpenAI API key
or another image provider that explicitly grants image capability.

### OAuth/Image Phase O — make the login usable and integrate it safely

**Objective:** Ship reliable OpenAI OAuth sign-in for chat/tools, and a separate
provider-verified image lane without mixing credentials or misrepresenting
entitlements.

**Files:**
- Create: `jarvis/integrations/openai_oauth_service.py`
- Create: `tests/test_openai_oauth_service.py`
- Modify: `jarvis/integrations/openai_oauth.py`
- Modify: `jarvis/agent/providers.py`
- Modify: `jarvis/agent/tools/image_gen.py`
- Modify: `jarvis/core/settings_service.py`
- Modify: `jarvis/ui/settings_providers.py`
- Modify: `jarvis/ui/window.py`
- Modify: `config.yaml`

**Tasks:**
1. Write failing tests for sign-in state transitions: idle, browser-open, callback-pending, connected, refresh-due, reauth-required, failed; test safe status never serializes token data.
2. Wrap `start_login()` in a worker-service API so the PyQt UI never blocks while the loopback server waits.
3. Add desktop controls: Sign in, Cancel, Refresh status, Sign out; wire progress/errors through a safe Qt signal. Do not log authorization URL query parameters or callback code.
4. On successful OAuth callback, call `providers.reset_clients()`, reload the provider status, and verify a minimal chat-only health request with a bounded timeout and no tools.
5. Keep OAuth provider capabilities as `chat`, `tools`, and `streaming` until OpenAI documents a supported image endpoint/entitlement for this exact OAuth flow and an integration test proves it.
6. Add a distinct image-provider configuration path: `openai` API-key provider, Gemini image provider, or approved OpenAI-compatible endpoint. `image_generate.available()` must require explicit `image` capability plus matching credential kind.
7. Add a Settings hint that distinguishes **ChatGPT OAuth for agent chat** from **API-key image billing/entitlement**. Never copy OAuth access tokens into `OPENAI_API_KEY` fields.
8. Add a manual acceptance checklist: local callback works, token survives restart in encrypted store, expiry refresh works, logout clears only OAuth store key, chat test succeeds, image test succeeds only with separately configured image provider.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_openai_oauth.py tests/test_openai_oauth_service.py tests/test_providers.py tests/test_image_gen_path.py
```

**Exit gate:** OAuth chat login can be completed from the Jarvis UI without a blocking UI thread; image tool remains unavailable until a provider with explicit image entitlement is configured.

---

## Target architecture

```text
Voice / Desktop / Dashboard / Telegram / Discord / WhatsApp / Webhook
                              │
                     Ingress Adapter Contract
                              │
                    Identity + Session Resolver
                              │
                Capability Policy + Approval Gate
                              │
          Router → Dispatch → Agent Loop / Direct Executor
                              │
 ┌───────────────┬────────────┼─────────────┬────────────────┐
 │ Native tools  │ MCP tools  │ Plugins     │ Schedules/jobs │
 └───────────────┴────────────┴─────────────┴────────────────┘
                              │
      ConversationDelivery + lifecycle + memory + telemetry
                              │
          UI / platform reply / dashboard task trace
```

### Core contracts to introduce

| Contract | Purpose | Likely path |
|---|---|---|
| `ExecutionContext` | source, actor, session, surface, toolsets, approval state, trace ID | `jarvis/agent/execution_context.py` |
| `CapabilityDescriptor` | tool/plugin/MCP metadata, permission, risk, timeout | `jarvis/agent/capabilities.py` |
| `PolicyDecision` | allow/deny/needs-approval plus safe reason | `jarvis/agent/policy.py` |
| `TaskRecord` | immutable safe task trace/status | `jarvis/agent/task_store.py` |
| `GatewayAdapter` | platform-neutral inbound/outbound lifecycle | extend `jarvis/gateway/base.py` |
| `PluginManifest v2` | identity, version, permissions, contribution points | extend `jarvis/plugins/manifest.py` |

---

# Phase 0 — Baseline repair and architecture inventory

**Objective:** Establish a reliable test baseline and a current dependency/reachability map before adding capabilities.

**Files:**
- Create: `docs/ARCHITECTURE_INVENTORY.md`
- Create: `tests/test_architecture_inventory.py`
- Modify: `docs/PHASE12_VERIFICATION.md`
- Inspect: `main.py`, `ui.py`, `jarvis/agent/*`, `jarvis/gateway/*`, `jarvis/plugins/*`, `actions/*`

### Tasks
1. Write a test that asserts declared frozen files and native-only integration flags.
2. Run the test red before inventory/config guard exists.
3. Generate a static import/reachability report for `actions/`, `jarvis/agent/`, `jarvis/gateway/`, `jarvis/integrations/`.
4. Classify every legacy helper: active, lazy-active, compatibility-only, candidate-retire; record owner, caller, latency class, and safety class.
5. Resolve the suite blockers deliberately:
   - update curator legacy expectations to the adopted review-first contract, or explicitly split legacy behavior tests;
   - decide whether Fase 3–6 `main.py` changes are approved frozen-baseline changes; only then update frozen manifest in a dedicated approval commit.
6. Add a canonical scoped suite command that excludes nested `hermes-agent-main/tests` collection.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_architecture_inventory.py
unset PYTHONPATH && python -m pytest -q tests
python scripts/verify_frozen.py
```

**Exit gate:** No unexplained test failures. Frozen manifest either passes or has an approved documented exception.

---

# Phase 1 — Execution context, identity, and unified policy

**Objective:** Make every execution path use one bounded context and policy decision.

**Files:**
- Create: `jarvis/agent/execution_context.py`
- Create: `jarvis/agent/policy.py`
- Create: `tests/test_execution_context.py`
- Create: `tests/test_policy.py`
- Modify: `jarvis/agent/dispatch.py`
- Modify: `jarvis/agent/adapters/telegram.py`
- Modify: `jarvis/ui/window.py`
- Modify: `jarvis/gateway/base.py`

### Tasks
1. Add failing tests for source, actor ID hash, session ID, trace ID, toolset set, and no raw secret fields in `ExecutionContext` serialization.
2. Implement immutable `ExecutionContext` with `for_child()` and redacted `safe_metadata()`.
3. Add failing tests for policy outcomes: allow, deny, approval-required, disabled capability, remote-surface restriction.
4. Implement policy lookup based on capability risk class, ingress source, actor authorization, and release flags.
5. Thread context through desktop, voice, Telegram, dispatch, cron, and future gateway adapter seams.
6. Ensure `ConversationDelivery` only receives safe context metadata.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_execution_context.py tests/test_policy.py tests/test_phase2_ingress.py
```

---

# Phase 2 — Capability registry and full toolset model

**Objective:** Replace ad-hoc tool exposure with a single discovery, availability, policy, and surface-aware capability catalog.

**Files:**
- Create: `jarvis/agent/capabilities.py`
- Create: `jarvis/agent/approval.py`
- Create: `tests/test_capabilities.py`
- Create: `tests/test_approval.py`
- Modify: `jarvis/agent/registry.py`
- Modify: `jarvis/agent/toolsets.py`
- Modify: `jarvis/agent/toolgroups.py`
- Modify: `jarvis/agent/capability_service.py`

### Capability groups

| Group | Default surfaces | Approval |
|---|---|---|
| `safe` | all | none |
| `desktop` | desktop/voice only | smart/manual |
| `files_read` | all authorized | none |
| `files_write` | desktop + paired remote | smart/manual |
| `browser` | desktop/voice | smart for external state changes |
| `web` | all authorized | none |
| `messaging` | authorized platform only | smart/manual |
| `code` | desktop + approved remote | smart/manual |
| `vision` | desktop/voice | explicit camera consent |
| `automation` | desktop/cron | approval by risk |
| `admin` | local admin only | always manual |

### Tasks
1. Write red tests that tool schemas cannot appear without an enabled group and policy approval.
2. Create descriptor fields: ID, group, risk, executor, requirements check, timeout, cancellation support, secret fields, audit category.
3. Register existing native helpers behind descriptors without changing their public behavior yet.
4. Add approval request persistence and surface-specific renderers: desktop dialog, voice confirmation, platform command confirmation.
5. Add tool health/status to management snapshot.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_capabilities.py tests/test_approval.py tests/test_toolsets.py tests/test_capability_service.py
```

---

# Phase 3 — Legacy helper acceleration foundation

**Objective:** Make local helpers feel immediate while preserving behavior and safety.

**Files:**
- Create: `jarvis/runtime/resource_pool.py`
- Create: `jarvis/runtime/cache.py`
- Create: `jarvis/runtime/metrics.py`
- Create: `tests/test_resource_pool.py`
- Create: `tests/test_legacy_helper_perf_contracts.py`
- Modify: `actions/dev_agent.py`
- Modify: `actions/browser_control.py`
- Modify: `actions/computer_settings.py`
- Modify: `actions/file_controller.py`
- Modify: `actions/weather_report.py`
- Modify: `actions/youtube_video.py`
- Modify: `actions/screen_processor.py`

### Performance contracts

| Helper | Target design | Realistic latency goal |
|---|---|---:|
| File ops | cached safe roots, paged listing, direct pathlib | <100 ms typical local op |
| Desktop controls | cached capability probe, direct OS API / reusable driver | <150 ms typical command |
| Weather | normalized query + 5–15 min TTL result cache | cache hit <50 ms |
| Browser | persistent Playwright/browser context and profile cache | existing session action <300 ms; cold start remains seconds |
| YouTube | cached search/info/transcript TTL + reuse tab | cache hit <100 ms; network remains variable |
| Screen | frame-change detector, JPEG budget, debounce | no repeated model call for unchanged frames |
| Messaging | persistent HTTP client, retry queue | enqueue <50 ms; network variable |
| Dev agent | current caches + command parser + persistent model/client | orchestration faster; LLM/install remain non-instant |

### Tasks
1. Add monotonic timing metrics and a histogram/rolling summary, without contents of requests or responses.
2. Define cache keys, TTLs, invalidation, max entries, and memory budgets per helper.
3. Convert helper availability probes from repeated shell calls to cached probes.
4. Reuse HTTP sessions, Playwright contexts, editor executable lookup, and platform clients.
5. Replace blind sleeps with readiness predicates/backoff only after actual rate-limit events.
6. Add queue/backpressure for screen frames, messaging sends, and long helper tasks.
7. Add benchmarks using fake network/process clients; do not make brittle wall-clock CI assertions.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_resource_pool.py tests/test_legacy_helper_perf_contracts.py
```

---

# Phase 4 — Browser and desktop automation maturity

**Objective:** Convert legacy browser/computer helpers into a reliable, cancellable automation service.

**Files:**
- Create: `jarvis/automation/browser_service.py`
- Create: `jarvis/automation/desktop_service.py`
- Create: `jarvis/automation/leases.py`
- Create: `tests/test_browser_service.py`
- Create: `tests/test_desktop_service.py`
- Modify: `actions/browser_control.py`
- Modify: `actions/computer_control.py`
- Modify: `actions/open_app.py`
- Modify: `jarvis/agent/registry.py`

### Tasks
1. Add browser lease ownership per task/session: only one high-risk writer owns a profile/tab action at once.
2. Reuse persistent browser context; never reuse user credentials across actors/surfaces.
3. Add idempotent navigation/open-tab actions and safe cancellation.
4. Use accessibility/structured automation APIs where available; use pixel automation only as fallback.
5. Add screenshot/redaction policy before dashboard or remote return.
6. Route destructive desktop/browser operations through approval gate.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_browser_service.py tests/test_desktop_service.py tests/test_phase2_browser_lease.py
```

---

# Phase 5 — Skills Hub v2

**Objective:** Turn the existing skills/usage/curator foundations into a safe local-first Skill Hub with browse, publish, update, provenance, and rollback.

**Files:**
- Create: `jarvis/agent/skill_catalog.py`
- Create: `jarvis/agent/skill_publisher.py`
- Create: `jarvis/agent/skill_signing.py`
- Create: `tests/test_skill_catalog.py`
- Create: `tests/test_skill_publish.py`
- Modify: `jarvis/agent/skills.py`
- Modify: `jarvis/agent/skill_hub.py`
- Modify: `jarvis/agent/skill_usage.py`
- Modify: `jarvis/agent/curator.py`
- Modify: `jarvis/agent/capability_service.py`
- Modify: `jarvis/ui/panels.py`

### Staged trust model

| Stage | Allowed |
|---|---|
| 5A | browse installed/local catalog, preview, enable/disable, pin/archive/restore |
| 5B | publish to a local filesystem catalog with immutable version archive |
| 5C | import from explicit URL/Git repository after checksum/signature and manual approval |
| 5D | remote registry only if signed manifests, review workflow, quarantine, and rollback exist |

### Tasks
1. Add versioned skill manifest: ID, version, provenance, checksum, permissions, compatibility, signing metadata.
2. Build catalog index in SQLite/JSON sidecar; support search/filter/browse without loading bodies.
3. Add preview-before-install and explicit permission diff.
4. Add local publish with version archive; never overwrite prior version.
5. Add update check, staged update, rollback to prior version.
6. Preserve Fase 9 review-first curator policy; no automatic delete.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_skill_catalog.py tests/test_skill_publish.py tests/test_skill_usage.py tests/test_skill_lifecycle.py
```

---

# Phase 6 — MCP maturity

**Objective:** Upgrade existing minimal stdio MCP client into a governed MCP integration layer.

**Files:**
- Create: `jarvis/agent/mcp_catalog.py`
- Create: `jarvis/agent/mcp_policy.py`
- Create: `tests/test_mcp_catalog.py`
- Create: `tests/test_mcp_policy.py`
- Modify: `jarvis/agent/mcp_client.py`
- Modify: `jarvis/agent/tools/mcp_tools.py`
- Modify: `jarvis/agent/capabilities.py`
- Modify: `jarvis/agent/management_surface.py`

### Tasks
1. Add MCP server descriptor: stdio/HTTP transport, allowed command/path, environment allowlist, tool allowlist, timeout/concurrency, trust state.
2. Validate server executable/path before spawn; prohibit `shell=True`; restrict inherited environment.
3. Map each discovered MCP tool to a `CapabilityDescriptor`; no automatic unrestricted exposure.
4. Add restart/health/backoff/circuit breaker and shutdown lifecycle.
5. Add per-server audit metadata and UI status, not raw server output.
6. Add catalog installation only for explicitly approved, signed/pinned MCP specs.
7. Add HTTP MCP transport after stdio lifecycle is stable.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_mcp_hub.py tests/test_mcp_catalog.py tests/test_mcp_policy.py
```

---

# Phase 7 — Plugin ecosystem v2

**Objective:** Make plugins extensible but locally trusted, permission-bounded, versioned, and independently disableable.

**Files:**
- Create: `jarvis/plugins/runtime.py`
- Create: `jarvis/plugins/permissions.py`
- Create: `jarvis/plugins/registry.py`
- Create: `tests/test_plugin_runtime.py`
- Create: `tests/test_plugin_permissions_v2.py`
- Modify: `jarvis/plugins/manifest.py`
- Modify: `jarvis/plugins/loader.py`
- Modify: `jarvis/agent/capabilities.py`
- Modify: `config.yaml`

### Tasks
1. Extend manifest with plugin version, API version, declared capability groups, tool names, UI contributions, migrations, checksum, author/provenance.
2. Validate before import; invalid/disabled plugin never imports code.
3. Create a separate plugin process boundary for untrusted-but-approved plugins later; Phase 7A remains trusted-local in-process only.
4. Add enable/disable/update/rollback and a plugin health record.
5. Add plugin tool schema namespace, collision rejection, execution timeout, and audit tag.
6. Add plugin UI contributions through a controlled panel API rather than direct `window.py` patching.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_plugins.py tests/test_plugin_permissions.py tests/test_plugin_runtime.py tests/test_plugin_permissions_v2.py
```

---

# Phase 8 — Cron and durable automation v2

**Objective:** Upgrade existing cron into a reliable job platform with explicit delivery, isolation, retry, observability, and kill controls.

**Files:**
- Create: `jarvis/agent/job_store.py`
- Create: `jarvis/agent/job_runner.py`
- Create: `tests/test_job_runner.py`
- Create: `tests/test_cron_delivery.py`
- Modify: `jarvis/agent/cron.py`
- Modify: `jarvis/agent/tools/cron_tools.py`
- Modify: `jarvis/agent/management_surface.py`
- Modify: `jarvis/gateway/delivery.py`

### Tasks
1. Add job run table: run ID, context, start/end, state, bounded redacted result, attempts, delivery status.
2. Add idempotency key and per-job concurrency policy; no duplicate simultaneous runs.
3. Add timeout/cancel/stop support and exponential retry policy by error class.
4. Add `no_agent` deterministic script jobs separately from agent jobs.
5. Add isolated workdir/context/toolsets/model selection to each job.
6. Make delivery destination explicit; platform send failure does not silently erase job result.
7. Add pause/resume/run-now/task trace/admin controls.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_agent_cron.py tests/test_job_runner.py tests/test_cron_delivery.py
```

---

# Phase 9 — Memory and session platform v2

**Objective:** Mature existing memory/context into explicit scoped, searchable, auditable long-term memory.

**Files:**
- Create: `jarvis/agent/memory_policy.py`
- Create: `jarvis/agent/session_store.py`
- Create: `tests/test_memory_policy.py`
- Create: `tests/test_session_store.py`
- Modify: `jarvis/agent/memory_store.py`
- Modify: `jarvis/agent/conversation_context.py`
- Modify: `core/memory_manager.py`
- Modify: `jarvis/agent/management_surface.py`

### Tasks
1. Define memory scopes: device-local, user, platform-actor, project/workspace, ephemeral task.
2. Add consent/policy tags and retention windows; remote gateway actors never automatically inherit local personal memory.
3. Add FTS/hybrid session search with safe excerpts and redaction.
4. Add memory inspect/edit/delete/export UI/API with audit event.
5. Add summarization/consolidation jobs only under explicit policy and budget.
6. Add profile/workspace isolation before multi-user platforms expand.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_agent_memory.py tests/test_conversation_context.py tests/test_memory_policy.py tests/test_session_store.py
```

---

# Phase 10 — Native gateway core

**Objective:** Turn current Telegram foundation into a formal multi-platform gateway independent from Hermes.

**Files:**
- Create: `jarvis/gateway/manager.py`
- Create: `jarvis/gateway/authz.py`
- Create: `jarvis/gateway/session_router.py`
- Create: `jarvis/gateway/webhooks.py`
- Create: `tests/test_gateway_manager.py`
- Create: `tests/test_gateway_authz.py`
- Modify: `jarvis/gateway/base.py`
- Modify: `jarvis/gateway/registry.py`
- Modify: `jarvis/gateway/delivery.py`
- Modify: `jarvis/gateway/platforms/telegram.py`
- Modify: `jarvis/agent/adapters/telegram.py`

### Tasks
1. Define `GatewayAdapter` contract: start/stop/health, normalize inbound, idempotency, authorization, typing/progress, send/edit/delete/cancel capability.
2. Persist gateway session map separately by platform/actor/thread/topic, bounded and redacted.
3. Add pairing flow and admin allowlist; no open DM command execution by default.
4. Add inbound rate limit, replay protection, webhook signature verification, attachment size/type policy.
5. Add delivery queue with bounded retries and dead-letter/audit state.
6. Migrate Telegram to manager-owned adapter while retaining current service as compatibility wrapper until verified.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_gateway_registry.py tests/test_gateway_delivery.py tests/test_gateway_telegram_migration.py tests/test_gateway_manager.py tests/test_gateway_authz.py
```

---

# Phase 11 — Discord adapter

**Objective:** Add Discord as the first second-platform proof that gateway contracts work.

**Files:**
- Create: `jarvis/gateway/platforms/discord.py`
- Create: `jarvis/gateway/platforms/discord_config.py`
- Create: `tests/test_gateway_discord.py`
- Modify: `jarvis/gateway/manager.py`
- Modify: `config.yaml`
- Modify: `jarvis/ui/settings_messaging.py`

### Tasks
1. Choose Gateway Events/WebSocket adapter library with pinned version; document required Message Content intent.
2. Implement signed/configured startup and health without exposing token.
3. Normalize DM/channel/thread identity, attachment metadata, slash commands, and message edit delivery.
4. Enforce allowlist/pairing and per-guild/channel policy.
5. Add event dedup, rate-limit backoff, reconnect, and safe shutdown.
6. Test with fake adapter first; live sandbox test only after user supplies non-production bot credentials.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_gateway_discord.py tests/test_gateway_manager.py
```

---

# Phase 12 — WhatsApp adapter

**Objective:** Add WhatsApp through the official Meta WhatsApp Business Cloud API, not consumer-web scraping.

**Files:**
- Create: `jarvis/gateway/platforms/whatsapp_cloud.py`
- Create: `jarvis/gateway/platforms/whatsapp_config.py`
- Create: `tests/test_gateway_whatsapp.py`
- Modify: `jarvis/gateway/webhooks.py`
- Modify: `jarvis/gateway/manager.py`
- Modify: `config.yaml`
- Modify: `jarvis/ui/settings_messaging.py`

### Tasks
1. Implement webhook verification handshake and HMAC/signature validation before parsing payload.
2. Normalize WhatsApp message IDs, sender IDs, conversation window policy, media metadata, and delivery statuses.
3. Encrypt/store references only; do not retain raw media by default.
4. Enforce pairing/allowlist, opt-in outbound policy, rate limit, retry, and message-template constraints.
5. Use an adapter interface so an alternate self-hosted bridge can later exist as a separate optional plugin—not as a replacement for official API.
6. Test with official payload fixtures; live test only after user provisions a Meta sandbox/phone number.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_gateway_whatsapp.py tests/test_gateway_authz.py tests/test_gateway_delivery.py
```

---

# Phase 13 — Rich admin/ops control plane

**Objective:** Expand current read-only management snapshot into secure operations management without exposing secrets or raw private content.

**Files:**
- Create: `jarvis/ops/api.py`
- Create: `jarvis/ops/audit_log.py`
- Create: `jarvis/ops/rbac.py`
- Create: `jarvis/ops/task_trace.py`
- Create: `tests/test_ops_api.py`
- Create: `tests/test_ops_rbac.py`
- Modify: `dashboard/server.py`
- Modify: `jarvis/agent/management_surface.py`
- Modify: `jarvis/ui/sessions_panel.py`
- Modify: `jarvis/ui/provider_health_panel.py`
- Modify: `jarvis/ui/panels.py`

### Admin surface matrix

| Surface | Read | Mutate | Controls |
|---|---|---|---|
| Sessions | metadata/trace | archive/delete/export | local admin only |
| Providers | health/model/quota-safe state | enable/select/test | local admin + manual approval |
| Tools/plugins/MCP | status/permissions | enable/disable/restart | local admin |
| Gateway | health/paired users/queue | connect/disconnect/pair/revoke | local admin |
| Cron | job/run state | create/pause/run/cancel | authorized admin |
| Memory | metadata/search-safe excerpt | edit/delete/export | scoped policy + audit |
| Approvals | pending request | approve/deny | authorized actor only |

### Tasks
1. Add authenticated local-first API token/OAuth boundary and RBAC roles.
2. Add immutable redacted audit events for config changes, approvals, plugin/MCP actions, gateway pairing, memory deletion, and job execution.
3. Add task trace timeline: routing decision, capabilities, approvals, tool timings, final delivery status.
4. Add live health with polling budget and no raw logs by default.
5. Add emergency stop: cancel tasks, pause jobs, disable plugins/MCP/gateway adapters, restore release defaults.
6. Build desktop panels and dashboard pages from the same API-safe snapshot.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_management_surface.py tests/test_management_panels.py tests/test_ops_api.py tests/test_ops_rbac.py
```

---

# Phase 14 — Reliability, performance, security, rollout

**Objective:** Make the new framework operationally safe and measurable before broad enablement.

**Files:**
- Create: `docs/OPERATIONS_RUNBOOK.md`
- Create: `docs/SECURITY_MODEL.md`
- Create: `docs/PERFORMANCE_BASELINE.md`
- Create: `scripts/benchmark_helpers.py`
- Create: `tests/test_security_invariants.py`
- Modify: `config.yaml`
- Modify: `jarvis/core/release_controls.py`
- Modify: `docs/PHASE12_VERIFICATION.md`

### Tasks
1. Add feature flags for every new subsystem, default off except safety/reporting.
2. Add rollback presets: `minimal`, `desktop-only`, `gateway-off`, `plugins-off`, `safe-mode`.
3. Add load/soak tests for gateway dedup, cron concurrency, task cancellation, browser lease, MCP restart, and memory search.
4. Add performance baseline table for cold/warm helper action p50/p95.
5. Add security invariant tests: secret redaction, actor isolation, no tool without policy, no remote desktop control without approval, webhook signatures required.
6. Publish operational runbook: pairing, platform setup, incident response, queue backlog, plugin/MCP rollback, database backup/restore.
7. Enable features in rings: local developer → desktop trusted user → Telegram paired user → Discord sandbox → WhatsApp sandbox → production allowlist.

**Verification:**
```bash
unset PYTHONPATH && python -m pytest -q tests/test_security_invariants.py tests/test_release_controls.py
unset PYTHONPATH && python -m pytest -q tests
python scripts/verify_frozen.py
```

---

## Dependency order

| Order | Phases | Why |
|---:|---|---|
| 1 | 0–2 | Reliable baseline, identity/policy, capability catalog first |
| 2 | 3–4 | Performance and automation use policy contracts |
| 3 | 5–9 | Skills/MCP/plugins/cron/memory become managed capability providers |
| 4 | 10–12 | Gateway core first, then Discord, then WhatsApp |
| 5 | 13–14 | Admin plane after real systems expose safe status/control contracts |

## Recommended first implementation slice

Do not begin all work at once. Start with **Phase 0, then Phase 1, then Phase 3**:

1. Fix baseline/manifest ambiguity.
2. Add execution context + policy before exposing new remote capabilities.
3. Finish measurable legacy-helper performance layer.

This yields immediate speed gains while creating the security foundation required for Discord, WhatsApp, MCP catalog, plugin updates, and rich admin controls.

## Risks and mitigations

| Risk | Mitigation |
|---|---|
| Scope turns into Hermes clone | Preserve voice-first product decisions; reuse patterns, not runtime/code |
| Messaging exposes local computer | Pairing, allowlists, approval classes, per-platform toolset defaults |
| Plugin/MCP supply-chain risk | local-only first; manifest validation, permission diff, checksum/signature, rollback |
| WhatsApp compliance/reliability | Official Cloud API only; webhook signatures; sandbox first |
| Helper optimization causes stale state | bounded TTL, explicit invalidation, per-resource lease/health checks |
| UI thread blocking | worker services; Qt signal bridge only for render updates |
| SQLite concurrency limits | WAL, bounded queues; introduce external queue only after observed contention |
| Secret leakage in admin plane | safe DTOs, structural redaction, audit only metadata, tests |

## Completion definition

Jarvis is materially closer to Hermes when it has, natively and with no Hermes runtime bridge:

- policy-gated unified capability registry;
- approved toolsets across local/remote surfaces;
- versioned Skills Hub browse/publish/update/rollback;
- governed MCP catalog and plugin lifecycle;
- durable cron/jobs with trace/cancel/retry;
- scoped memory/session search and deletion/export controls;
- Telegram + Discord + WhatsApp Cloud adapters behind one gateway contract;
- rich local-admin operations plane with task trace/audit/health/approvals;
- measured warm-path acceleration for legacy helpers; and
- documented rollout/rollback plus clean full test baseline.
