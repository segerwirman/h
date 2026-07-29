# JARVIS — Project & Session Handoff

> **Last updated:** 2026-07-25 09:59:36 SEAST
> **Purpose:** durable continuation context for JARVIS work. This is a concise engineering handoff, not a raw chat transcript. It intentionally contains **no credentials, tokens, raw gateway IDs, private payloads, or secret paths**.

## 1. Project identity

| Item | Value |
|---|---|
| Repository | `E:\jarvis agent\h` |
| Branch | `main` |
| Supported desktop entrypoint | `python -m jarvis.main` |
| Legacy entrypoints | Root `main.py` and `ui.py` are frozen compatibility dependencies; do not use them as the normal launch path. |
| Test command | `unset PYTHONPATH; python -m pytest -q` |
| Frozen verification | `python scripts/verify_frozen.py` |
| Main design goal | A native, self-contained JARVIS desktop agent—voice/vision-first—without Hermes CLI as a runtime dependency. |
| Current runtime metadata | `gpt-5.6-terra` via `openai-codex` |

## 2. User and engineering preferences

- Address the user as **Takeda**; assistant name is **Her** or **Mes**.
- Communicate primarily in Indonesian.
- Explain codebases using: architecture table → layer/folder breakdown → entrypoints → concise conclusions.
- For implementation: work phase-by-phase, TDD-first, with real verification.
- Do not commit, push, enable LAN/firewall/UAC, start voice/Gemini Live, run Telegram polling, or access credentials without explicit user authorization.
- Never expose/read/persist secrets in reports, tests, plans, or this handoff.
- Hermes is a **design and maturity reference**, never a JARVIS runtime dependency.

## 3. Canonical architecture

```text
python -m jarvis.main
  └─ jarvis.main.run()
      ├─ config + secret-store init/validation
      ├─ PyQt JarvisUI / Orb / BUS
      ├─ wake trigger, optional vision and relay
      ├─ optional manager-owned Telegram runtime
      ├─ CronScheduler
      └─ optional legacy Gemini Live voice thread through approved seam

UI typed/voice/Telegram/cron
  └─ router classification
      ├─ T0: local instant action
      ├─ T1: light/direct integration
      └─ T2/T3: dispatch async → session → agent loop
          ├─ heavy/light provider routing and failover
          ├─ prompt + memory + skills
          ├─ tool schema generation
          └─ registry execution → origin adapter delivery
```

### Runtime layers

| Layer | Primary paths | Role |
|---|---|---|
| Runtime/entry | `jarvis/main.py`, `jarvis/runtime/` | Canonical bootstrap, supervisor, evaluation. |
| Agent | `jarvis/agent/` | Router, providers, dispatch, loop, tools, memory, skills, cron, MCP. |
| Core | `jarvis/core/` | Config, settings, secret storage, release and dashboard policy. |
| UI | `jarvis/ui/` | PyQt window, Orb, panels, settings, operations surface. |
| Gateway | `jarvis/gateway/`, `jarvis/agent/adapters/telegram.py` | Telegram manager, pairing/authz, receipt dedup, rollout evidence. |
| Integrations | `jarvis/integrations/` | Google, OAuth, Telegram control, relay and optional integrations. |
| Plugins | `jarvis/plugins/` | Trusted-local plugin manifest/runtime. |
| Dashboard | `dashboard/` | Loopback-first management UI. |
| Legacy actions | `actions/`, root `main.py` | Compatibility helpers; modernize only through approved seams. |

## 4. Security and lifecycle decisions already implemented

### Desktop/dashboard

- Dashboard defaults to loopback (`127.0.0.1`).
- LAN is explicit opt-in, TLS-required, exact HTTPS origin only, and read-only.
- No automatic firewall or UAC action is authorized.
- Gateway operations, OAuth, provider configuration, approval decisions, and release controls remain desktop-local.
- Dashboard asset supply chain is local vendor-only with same-origin CSP.
- HTTP/WebSocket command ingress has bounded queues and rate limits.

### Telegram gateway

- Lifecycle authority is `TelegramGatewayRuntime`, bound to `GatewayManager`.
- Pairing is durable; ingress dedup uses a SQLite/WAL receipt ledger.
- Receipts hold hashed ingress identity only; no raw body, actor/chat/message ID, token, or tool args.
- `drop_pending_updates` remains `False`; replay must be denied by durable receipts.
- Remote Telegram `/stop` is rejected as desktop-local; it must not globally cancel desktop tasks.
- Release gate is currently intended to remain **off/stopped** unless Takeda explicitly authorizes a supervised live window.
- No live inbound production acceptance was performed during this session.

### Approval and runtime authority

- Approval continuation is process-local, in-memory, TTL-bound, one-shot, and not recoverable after restart.
- `RuntimeSupervisor` provides reverse-order cleanup, error isolation, and bounded joins.
- Legacy `JarvisLive` received cooperative stop handling through an approved compatibility seam.

### Evaluation and plugins

- Evaluation is deterministic and metadata-only: scenario ID, outcome, elapsed time, exception class.
- Plugin runtime validates every manifest before tool reservation or persistence.
- Plugin restore revalidates saved manifests; invalid records are ignored.
- Plugins are trusted-local only; no network marketplace, auto-download, remote activation, or automatic import/execution.

## 5. Completed phases in this session/history

| Phase | Status | Main output |
|---|---|---|
| 0–14 | Complete foundation | Agent/runtime policies, dashboard/gateway hardening, Ops/RBAC/audit, release controls, Skills/MCP/plugin/job/memory foundations. |
| 15A | Complete | Vendor-only dashboard assets/CSP, bounded backpressure, durable gateway receipts, remote `/stop` boundary. |
| 15B | Complete | Canonical `RuntimeSupervisor`, one shutdown authority, non-daemon voice registration. |
| 15B.2 | Complete | Cooperative legacy `JarvisLive.request_stop()` and stop watcher. |
| 16 | Complete | Local deterministic reliability/evaluation runner and safe benchmark summaries. |
| 17 | Complete | Credential-safe deterministic Telegram production-ring evidence reducer and acceptance protocol; no live transport auto-enabled. |
| 18 | Complete | Trusted-local plugin activation/restore validation before tool contribution/persistence. |

### Plans created

```text
.hermes/plans/2026-07-22_182154-phase14-local-first-dashboard-telegram-rollout.md
.hermes/plans/2026-07-22_222009-phase15a-critical-hardening.md
.hermes/plans/2026-07-22_222500-phase15b-runtime-authority.md
.hermes/plans/2026-07-22_225616-phase15b2-voice-cooperative-stop.md
.hermes/plans/2026-07-22_230000-phase16-reliability-evaluation.md
.hermes/plans/2026-07-22_231000-phase17-telegram-production-ring.md
.hermes/plans/2026-07-23_000000-phase18-ecosystem-extension-safety.md
```

## 6. Latest verification evidence

| Scope | Result |
|---|---|
| Phase 18 focused plugin/release suites | `14 passed` |
| Phase 18 full suite | `805 passed`, `4 existing Pillow warnings` |
| Current audit focused safety/runtime suite | `34 passed in 10.31s` |
| Frozen integrity | `OK (10 files, baseline 094b696)` |
| `git diff --check` | exit `0`; expected LF→CRLF warnings from dirty Windows working tree |

No live Telegram polling, gateway start, LAN bind, firewall change, voice session, Gemini Live connection, credential read, commit, or push was performed for these verifications.

## 7. Current repository state

- Working tree is intentionally **not clean**: the latest audit saw `129` changed/untracked entries.
- The tracked diff contained `43` changed files, `2,157` insertions, and `462` deletions; many maturity-phase modules are still untracked.
- Do not assume a clean release/commit baseline. Keep phase changes narrowly scoped and verify against the existing dirty tree.
- `setup.py` is stale: it tells users to run legacy `python main.py` / MARK XXV. Canonical docs correctly state `python -m jarvis.main`.

## 8. Audit findings — open work

### P1 — Remote Telegram `/memory` can cross memory scopes

**Verified source evidence:**

- `jarvis/agent/adapters/telegram.py:319–332`: paired remote `/memory` calls `memory_store.search(query, None, 6)` without `scope`/`owner`.
- `jarvis/agent/memory_store.py:242–266`: missing scope/owner means query spans all non-expired memory rows.
- `jarvis/agent/memory_policy.py:24–34`: policy says `device-local`/`user` are local-only; remote should only access its own `platform-actor` scope.

**Required remediation:** construct/propagate remote `ExecutionContext`; force Telegram memory reads to `scope="platform-actor"`, `owner="telegram:<actor>"`; enforce `memory_policy.can_access()` for every memory read/write/delete/export path. Add cross-actor and device-local regression tests. Do not test against real memory data.

### P1 — Capability policy is not wired into production tool registration

**Runtime evidence from a fresh interpreter:**

```text
registered_capabilities= 0
registered_tools= []
```

**Verified source evidence:**

- `jarvis/agent/registry.py:110–140` only enforces capability policy when an `ExecutionContext` exists, and rejects contextual tools with no descriptor.
- UI, voice, and cron paths include calls to `registry.execute(...)`/agent loop without context (for example `jarvis/ui/window.py:735`, `jarvis/integrations/google_voice.py:82`, `jarvis/agent/dispatch.py:307–310`).
- Capability tests populate the registry manually rather than showing production registration.

**Required remediation:** create the production descriptor catalog, make context mandatory in dispatch/cron/UI/voice paths, and reject contextless production tool execution except explicit internal/test seams.

### P1 — Cron/job records violate the metadata-only privacy contract

**Verified source evidence:**

- `jarvis/agent/cron.py:33–45, 76–81`: persists raw cron task and `last_result`.
- `jarvis/agent/cron.py:204–210`: stores raw result text.
- `jarvis/agent/job_store.py:22–31, 68–75`: safe DTO exposes and SQLite stores raw result.
- `jarvis/agent/cron.py:214–227`: result can be sent to Telegram and event bus.
- `docs/SECURITY_MODEL.md:18` declares raw task output should not appear in safe operational DTOs.

**Required remediation:** durable job/audit records must be metadata-only; separate delivery from audit storage; make raw result delivery explicit/local/retention-bounded; test redaction across DTO, event bus, and notification defaults.

### P2 — Terminal/process/code execution needs a universal capability approval boundary

- `jarvis/agent/tools/terminal.py:42–58` relies on a destructive-command regex and uses `shell=True`.
- `jarvis/agent/tools/terminal.py:158–166` spawns background processes through a shell.
- `jarvis/agent/tools/code_exec.py:54–65` has a bounded sandbox/timeout but launches through a shell.

**Required remediation:** classify these as high/critical capability descriptors; require desktop-local approval via context; prefer structured argv rather than shell; retain bounded workspace/process lifecycle.

### P2 — MCP is not yet fail-closed and its read timeout can block

- `jarvis/agent/mcp_client.py:34–57`: empty allowlist preserves compatibility, so validation is skipped when no allowed command is configured.
- `jarvis/agent/mcp_client.py:95–111`: blocking `stdout.readline()` can outlive the logical deadline.

**Required remediation:** an empty MCP allowlist should start no server; implement nonblocking reader/queue or polling; kill process tree on timeout; add server/tool/response/restart budgets.

### P3 — Legacy dashboard firewall/UAC helper is dead but misleading

- `dashboard/server.py:103–311` contains `_ensure_network_access()` with firewall/UAC behavior.
- No caller was found; modern dashboard policy correctly forbids automatic firewall/UAC.

**Required remediation:** remove/archive the dead helper and add a regression assertion that dashboard startup never mutates firewall/UAC.

## 9. Hermes comparison snapshot

### Where JARVIS is close

- Native tool-calling agent loop, provider routing/fallback, sessions, skills, memory, cron, MCP foundation, plugins foundation, Telegram gateway, approval model, release rings, and dashboard/operations controls.
- JARVIS is especially strong as a **desktop/voice/vision-first** native application.
- Hermes bridge is disabled by default and must remain compatibility-only.

### Where Hermes remains ahead

- Profile isolation: Hermes profiles separate config, memories, sessions, skills, cron, and state databases.
- Breadth/maturity of multi-platform gateway, CLI/TUI operations, generic extension ecosystem, job/event infrastructure, provider/platform lifecycle, and delegation workflow.
- Consistent policy/storage enforcement as production runtime contracts.

### Strategic decision

Do **not** chase more messaging platforms or plugin breadth until the three P1 boundaries above are fixed. The next high-value work should stabilize policy authority and privacy-safe persistence first.

## 10. Suggested next phase (not started)

### Phase 19A — Policy & Memory Authority

1. TDD: remote Telegram memory request cannot return local/user/other-actor memory.
2. Introduce a single context-aware memory access facade.
3. TDD: production capability catalog registers every exposed tool.
4. Require `ExecutionContext` across native dispatch, cron, UI agent, voice, and gateway paths.
5. Classify high-risk tools and route approval consistently.
6. Run focused → full suite → frozen → `git diff --check`.

### Phase 19B — Privacy-Safe Durable Jobs

1. TDD: task/output/secret-like content never appears in job safe DTO, durable audit record, or default notification.
2. Replace result persistence with metadata-only fields and retention/capacity policy.
3. Make output delivery explicit and source-bound.
4. Verify all existing cron behavior without live Telegram.

## 11. Operational constraints for continuation

- Continue using `unset PYTHONPATH` before Python tests to avoid environment shadowing.
- Do not use `pytest -n 0`.
- Run `git diff --check` before any requested commit.
- Never commit/push unless explicitly requested.
- Keep Telegram disabled/stopped by default. Any supervised live window needs a new explicit user authorization.
- Avoid reading `.env`, secret stores, credential files, or live SQLite data unless the user explicitly asks and the action is necessary.
- Preserve local-first dashboard posture and do not enable LAN/firewall/UAC automatically.

## 12. Provider and UI remediation (2026-07-25)

### User-reported symptoms

- `openai_oauth` login completed, but the first LLM request returned HTTP `404`.
- `anthropic_oauth` had no browser-login control in the provider settings surface.
- Capabilities sheet had no obvious close button.
- The persistent `JARVIS` title in the upper-left could be visually covered/darkened.

### Verified diagnosis and implemented guardrails

1. The OpenAI ChatGPT/Codex endpoint is correctly configured as
   `https://chatgpt.com/backend-api/codex/responses`. Public Codex issue reports
   show the same route can return HTTP `404` specifically for a model unavailable
   to an account/rollout. JARVIS previously supplied the static default
   `gpt-5.2`, so a successful login could still fail on the first prompt.
2. `openai_oauth` now classifies a safe `model_not_found` response separately,
   never retains provider response bodies, and exposes `available_models()` via
   the authenticated Codex model catalog. New OpenAI OAuth configurations begin
   with no selected model rather than sending a stale hard-coded model.
3. The provider sheet now exposes both OpenAI OAuth and Anthropic OAuth login
   controls. Anthropic OAuth has the same token-safe status contract as OpenAI;
   the official fallback remains the separate `anthropic` API-key provider.
4. After OpenAI OAuth connects, JARVIS automatically starts account-catalog
   detection and exposes **DETEKSI MODEL PROVIDER** for a manual refresh. Pick a
   detected model, save it, then make the provider active and run **TEST**.
   Detection does not send a chat prompt.
5. `CapabilitiesPanel` now has a **TUTUP** button. `OrbRenderer` is scoped to
   `ContentStage` and uses a translucent background so it no longer overlays the
   persistent header/title.

### Evidence

- Red tests were captured for unavailable OpenAI model mapping, missing model
  catalog, missing Anthropic OAuth status/UI, missing Capabilities close button,
  and orb parent scope.
- Focused verification after repair:
  `68 passed in 8.51s` across OAuth, provider, settings, panels, window, policy,
  and secrets/OAuth suites.
- Full verification after frozen-manifest update:
  `811 passed, 4 existing Pillow deprecation warnings in 29.91s`.
- Frozen integrity: `OK (10 files, baseline 094b696)`; `git diff --check` exits
  successfully (only pre-existing CRLF normalization warnings are emitted).
- No credentials, token values, browser login, live provider request, or model
  catalog request against a real account was performed during this repair.

## 13. Orb first-boot, detected-model selector, and image boundary (2026-07-25)

1. **First-boot Orb geometry:** `MainWindow` now listens directly to
   `ContentStage` resize/show events and schedules one post-layout geometry sync.
   This eliminates the `100×30` default canvas that could be visible before the
   first top-level resize; the Orb canvas always matches `stage.rect()`.
2. **Selectable account models:** `jarvis.agent.model_catalog` adds opt-in,
   privacy-safe discovery. It uses the signed-in Codex catalog for
   `openai_oauth`, `/models` for OpenAI-compatible providers, and Gemini's
   documented model listing filtered to `generateContent` models. Results are
   selector-only: not persisted or logged until the user explicitly chooses one
   and clicks **SIMPAN**. Anthropic remains manual because it does not expose a
   general account model-list endpoint.
3. **GPT Image 2:** the existing `image_generate` tool supports configurable
   `gpt-image-2` through the OpenAI API-key (`openai_compat`) provider. It must
   remain separate from ChatGPT/Codex OAuth: OAuth advertises chat/tools/
   streaming only and is not falsely given image capability. Remote OpenAI image
   generation is now disabled until an API key is actually configured; an
   explicitly unauthenticated local OpenAI-compatible endpoint remains allowed.
4. Verification: focused regression `45 passed`; full suite `819 passed, 4
   existing Pillow deprecation warnings`; frozen integrity `OK (10 files,
   baseline 094b696)`; `git diff --check` succeeds (only CRLF normalization
   warnings from the already-dirty workspace). No account OAuth, live catalog,
   or paid image generation request was performed.

## 14. Telegram remote agent readiness and bounded capability surface (2026-07-25)

1. **Root cause of generic readiness refusal:** gateway `InboundMessage`
   created a remote context with only `messaging` and `agent`, while the global
   capability registry had no remote descriptors. Further, `agent.dispatch`
   was always high-risk, so policy required a local approval before the remote
   agent could start. The generic Telegram message masked this structural gate.
2. **Safe repair:** paired Telegram contexts now permit only `agent`, `web`,
   `image`, and `messaging`. Explicit descriptors expose web search/extract,
   public YouTube metadata search/info/trending, and `image_generate`; desktop
   control, browser control, terminal, file writes, secrets, and account
   actions are still absent and fail closed. Remote dispatch is medium-risk
   only because the agent schema is bounded to those descriptors; each tool is
   still policy-gated.
3. **Simple request delivery:** one-image requests are deterministic T1 calls
   to `image_generate`, never require a heavy LLM, and generated `.png/.jpg/
   .jpeg/.webp` paths are sent back as Telegram photos. YouTube/video search
   remains T1 web search and does not enter the heavy lane.
4. **Slash menu:** `command_menu()` is registered with Telegram's Bot API via
   `post_init`, so typing `/` exposes `/help`, `/tools`, `/status`, `/todo`,
   `/memory`, `/cron`, `/screen`, `/skills`, `/session`, `/confirm`, and
   `/stop`. `/help` and `/tools` state the real bounded remote surface instead
   of claiming unsafe desktop/Hermes-equivalent authority.
5. **Test isolation:** `tests/test_capabilities.py` now restores the global
   capability registry after tests that replace it, preventing order-dependent
   remote capability failures.
6. Verification: Telegram/policy focused regression `102 passed`; full suite
   `827 passed, 4 existing Pillow deprecation warnings`; frozen integrity
   `OK (10 files, baseline 094b696)`; `py_compile` and `git diff --check`
   pass. No polling restart, Telegram credential access, provider request, or
   paid image generation was performed.
