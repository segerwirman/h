# Phase 14 — Local-First Dashboard & Telegram Controlled Rollout Implementation Plan

> **For Hermes:** Use `test-driven-development` skill and execute this plan one vertical RED → GREEN → REFACTOR slice at a time. Do not commit, push, start a live Telegram poller, open a firewall rule, or change credentials unless Takeda explicitly asks for that side effect.

**Goal:** Make the existing dashboard fail closed to loopback by default, establish explicit release/rollback gates, and create a credential-safe, measurable Telegram rollout acceptance path before enabling any additional remote platform.

**Architecture:** Keep the current desktop application and manager-owned Telegram runtime intact. Add a small pure security-policy seam for dashboard exposure and rate limits; `dashboard/server.py` consumes that policy rather than deciding bind addresses, TLS, origin validation, or LAN mutation ad hoc. Keep Dashboard LAN in read-only mode during this phase; remote commands/audio/uploads and all Ops mutations remain desktop-local. Add a read-only Telegram rollout preflight/reporting seam and deterministic soak tests around the current `GatewayManager`/`GatewayRegistry` contracts.

**Tech Stack:** Python 3.11, FastAPI/Uvicorn, PyQt6 desktop control plane, SQLite/WAL gateway authz, asyncio, pytest, existing `jarvis.core.config`, release controls, and GatewayManager runtime.

---

## Current state and non-negotiable boundaries

| Area | Current evidence | Required outcome |
|---|---|---|
| Dashboard listener | `dashboard/server.py:774` and `:798` bind `0.0.0.0`; `:772`/`:788` can request firewall setup | Default bind is `127.0.0.1`; LAN can only be explicitly opted in with TLS and exact origins. No firewall action in default mode. |
| Dashboard auth | Bearer/QR token flow exists at `dashboard/server.py:492-575`; WebSockets accept a token but have no origin gate | Keep existing token semantics initially, add expiry/rate/origin protection without logging a token, PIN, or device key. |
| Dashboard mutations | `/api/command`, `/api/wake`, uploads, phone-audio and `/ws` command intake accept authenticated remote callers | In LAN read-only mode, return a safe denial. Approval/deny, pairing, revoke, lifecycle, OAuth, and provider configuration remain unavailable from every dashboard mode. |
| Release controls | `jarvis/core/release_controls.py:6-67` has flags, rings, and presets | Add a safe release state/status contract and enforce `gateway` before a Telegram rollout can advance. |
| Telegram ownership | `jarvis/gateway/runtime.py` owns lifecycle; `GatewayManager.receive()` authorizes + deduplicates | No change to ingress authority. Add readiness/reporting, stress coverage, and manual acceptance gates only. |
| External effects | Live credentials and desktop environment may exist but are private | Automated tests use fakes and temp SQLite only. Real polling, pairing, firewall and LAN exposure require an explicit, later user approval. |

### Out of scope

- No dashboard internet exposure, reverse proxy, public DNS, or production LAN enablement.
- No new dashboard admin mutation endpoint and no remote approval continuation.
- No automatic firewall/UAC prompt.
- No Discord/WhatsApp enablement.
- No token migration or reading/printing `.env`, secure-store entries, QR keys, session keys, or device tokens.
- No change to the voice pipeline, visual identity, root legacy entry point, or frozen files without a separately approved change.

---

## Target architecture

```text
config.yaml (non-secret dashboard + release controls)
                    │
                    ▼
 jarvis.core.dashboard_security (pure, fail-closed policy)
   ├─ DashboardExposure: loopback | lan-readonly
   ├─ exact allowed HTTP/WS origins
   ├─ TLS/LAN validation
   └─ bounded per-client rate limiter
                    │
                    ▼
             DashboardServer
   ├─ loopback: existing authenticated desktop companion behavior
   └─ LAN read-only: safe snapshots only; no command/audio/upload/download/WS command
                    │
                    ▼
       Desktop-local Gateway Operations / approvals
                    │
                    ▼
  TelegramGatewayRuntime → GatewayManager → GatewayAuthz + GatewayRegistry
                    │
                    ▼
      Telegram rollout preflight + deterministic soak evidence
```

---

## Configuration contract to introduce

Add this non-secret section next to `release_controls` in `config.yaml` (all values are safe metadata):

```yaml
dashboard:
  lan_enabled: false
  bind_host: "127.0.0.1"       # only honored when lan_enabled is false
  port: 8000
  lan_allowed_origins: []       # exact https://host:port origins; required for LAN
  lan_read_only: true           # must remain true in this phase
  require_tls_for_lan: true
  auth_rate_limit_per_minute: 10
  command_rate_limit_per_minute: 30
```

Rules:

1. `lan_enabled: false` always resolves to loopback; `bind_host` cannot override it to a non-loopback address.
2. `lan_enabled: true` is valid only if TLS material is available, `require_tls_for_lan` is true, `lan_read_only` is true, and every configured origin is an exact `https://host[:port]` origin without paths, queries, fragments, wildcards, or credentials.
3. Invalid LAN configuration disables dashboard serving with a safe local error; it must never silently bind `0.0.0.0`.
4. Do not use CORS `*`; configure FastAPI middleware only for the exact effective origin set.
5. `DashboardServer.get_url()` shows `127.0.0.1` in default mode; it never auto-advertises a LAN IP.

---

## Task 1: Introduce pure dashboard exposure policy

**Objective:** Make listener/origin/mutation decisions independently testable before touching FastAPI lifecycle code.

**Files:**
- Create: `jarvis/core/dashboard_security.py`
- Create: `tests/test_dashboard_security.py`
- Modify: `config.yaml`

**Step 1 — RED: loopback default**

Write `test_default_dashboard_bind_ke_loopback_dan_tidak_perlu_firewall()` against the wished-for API:

```python
from jarvis.core.dashboard_security import exposure_from_config

policy = exposure_from_config({}, tls_available=False)
assert policy.host == "127.0.0.1"
assert policy.lan_enabled is False
assert policy.needs_firewall is False
assert policy.allows_remote_mutation is False
```

Run:

```bash
unset PYTHONPATH; python -m pytest -q tests/test_dashboard_security.py::test_default_dashboard_bind_ke_loopback_dan_tidak_perlu_firewall
```

Expected: FAIL because the module/function does not exist.

**Step 2 — GREEN: minimal immutable policy**

Create a frozen `DashboardExposure` dataclass with only:

```python
host: str
port: int
lan_enabled: bool
read_only: bool
origins: frozenset[str]
tls_required: bool
needs_firewall: bool
```

Implement `allows_remote_mutation` as `False` for the initial phase. Implement `exposure_from_config(raw, *, tls_available)` using only dictionaries and standard-library URL parsing. Do not import FastAPI or read config globally in this module.

**Step 3 — verify GREEN**

Run the focused test and refactor only if necessary.

**Step 4 — RED: LAN configuration fails closed**

Add separate tests for:

- LAN enabled with no TLS material raises `DashboardSecurityError`.
- LAN enabled with `lan_read_only: false` raises `DashboardSecurityError`.
- LAN enabled without an origin raises `DashboardSecurityError`.
- wildcard, `http://`, a path, or credentials in an origin raises `DashboardSecurityError`.
- a valid exact HTTPS origin yields `host == "0.0.0.0"`, `needs_firewall is True`, and read-only mode.

**Step 5 — GREEN**

Implement narrow validation helpers. Normalize only case/whitespace; do not broaden a host or origin. Keep origin matching exact.

**Step 6 — RED/GREEN: deterministic rate limiter**

Add a clock-injected, lock-protected fixed-window limiter in the same module:

```python
limiter = FixedWindowRateLimiter(limit=2, window_seconds=60, now=lambda: 100.0)
assert limiter.allow("127.0.0.1") is True
assert limiter.allow("127.0.0.1") is True
assert limiter.allow("127.0.0.1") is False
```

Test client isolation and expiry at the window boundary. Implement no background thread and retain only bounded buckets. Use IP/safe client key only; never store headers or request payloads.

**Step 7 — config documentation**

Add the configuration block above with default loopback values. Do not add addresses, credentials, or actual LAN origins.

**Verification:**

```bash
unset PYTHONPATH; python -m pytest -q tests/test_dashboard_security.py
```

---

## Task 2: Make DashboardServer consume the exposure policy

**Objective:** Replace hard-coded public bind/firewall behavior while preserving desktop loopback behavior.

**Files:**
- Modify: `dashboard/server.py:368-805`
- Modify: `tests/test_dashboard_security.py`

**Step 1 — RED: server defaults to safe bind**

Construct a `DashboardServer` with an injected `DashboardExposure` or a testable config resolver. Assert the generated Uvicorn configuration uses `127.0.0.1`, port `8000`, and firewall scheduling is not called.

Do not start Uvicorn in the test. Extract a small `server_config()`/`serve_settings()` helper that returns plain values and can be asserted without networking.

**Step 2 — GREEN: dependency injection and safe URL**

- Resolve dashboard config through `jarvis.core.config.section("dashboard")` only at `DashboardServer` construction.
- Keep an optional explicit exposure argument for tests.
- Update `get_url()` and `get_manual_url()` to use the effective host, never `_local_ip()` in loopback mode.
- In `serve()`, call `_ensure_network_access()` only when `exposure.needs_firewall` is true.
- Build `uvicorn.Config` using `exposure.host` rather than hard-coded `0.0.0.0`.
- Do not create the TLS alias listener in loopback mode. In LAN mode, only create it after exposure validation succeeds.

**Step 3 — RED: invalid LAN never invokes Uvicorn or firewall**

Inject invalid LAN config/TLS unavailable and assert the server returns a safe failure status/log line, without a bind attempt and without `_ensure_network_access()`.

**Step 4 — GREEN: fail before side effects**

Catch only `DashboardSecurityError` at the outer `serve()` boundary, print a credential-free error such as `Dashboard LAN disabled: TLS/origin policy incomplete.`, and return. Do not fall back to a broader public bind.

**Step 5 — RED/GREEN: exact CORS policy**

For valid LAN-read-only config, verify FastAPI's CORS middleware is configured from exact origins only and does not allow credentials/methods/headers indiscriminately. For loopback, do not add permissive CORS. Keep static content same-origin.

**Verification:**

```bash
unset PYTHONPATH; python -m pytest -q tests/test_dashboard_security.py
```

---

## Task 3: Enforce origin, rate, and LAN read-only endpoint policy

**Objective:** Prevent a valid token from becoming a blanket remote-control grant when LAN mode is enabled.

**Files:**
- Modify: `dashboard/server.py:450-760`
- Modify: `tests/test_dashboard_security.py`

**Step 1 — RED: reject bad/missing WebSocket origin**

Test a pure `DashboardExposure.allows_origin(origin)` helper first:

```python
assert policy.allows_origin("https://panel.example.test:8000") is True
assert policy.allows_origin("https://evil.example.test") is False
assert policy.allows_origin("") is False
```

Then add an endpoint-level test using FastAPI `TestClient` only when dependencies are installed. For a LAN policy, a token plus non-allowed/missing `Origin` must be closed before `accept()`.

**Step 2 — GREEN: shared request guard**

Add small local helpers in `_build_app()` that:

1. derive a bounded client key from `req.client.host` (or WebSocket client host),
2. apply the route's rate limiter before body parsing/decryption,
3. check bearer token,
4. require exact origin for LAN WebSocket/HTTP mutation paths,
5. return/close with safe `401`, `403`, or `429` responses.

Never put the bearer token, PIN, encrypted input, device token, or decoded command in an exception/log/audit string.

**Step 3 — RED: LAN read-only is enforced on every mutation path**

Add parameterized endpoint tests covering:

- `POST /api/command`
- `POST /api/wake`
- `POST /api/upload`
- `POST /api/device-login`
- `POST /api/revoke-devices`
- `/ws` message `{"type": "command"}`
- `/ws/phone-audio`
- `/uploads/{filename}` download

For an authenticated LAN-read-only policy, each must receive a safe denial and must not enqueue a command, wake the app, create a file, issue a session, invalidate sessions, or accept audio. `GET /api/control-plane` remains available only after auth and continues to return its existing safe snapshot.

**Step 4 — GREEN: centralize read-only check**

Implement one `remote_mutation_allowed` guard that is always false for LAN in this phase. Do not scatter conditionals per route; each mutation route calls the same helper. Keep loopback behavior unchanged except rate limiting and no new public bind.

**Step 5 — RED/GREEN: rate limits**

Test login/device-login and command paths independently: the Nth request from one client returns `429`; another client remains eligible; window expiry restores access. Run body decoding only after the limiter allows the request.

**Step 6 — static scan regression guard**

Add a source-level or configuration-level test that prevents `host="0.0.0.0"` literals and unconditional `_ensure_network_access(...)` calls in `DashboardServer.serve()`/`_serve_alias()` from returning. Prefer testing behavior over AST details where practical.

**Verification:**

```bash
unset PYTHONPATH; python -m pytest -q tests/test_dashboard_security.py tests/test_security_invariants.py
```

---

## Task 4: Make release-ring state explicit and fail-safe

**Objective:** Allow a desktop-local operator to know whether a rollout is eligible without using dashboard mutation or silently enabling a platform.

**Files:**
- Modify: `jarvis/core/release_controls.py`
- Modify: `tests/test_release_controls.py`
- Modify: `tests/test_security_invariants.py`
- Modify: `config.yaml`

**Step 1 — RED: release status exposes no unknown flags**

Add a `status_for_ring(current_flags, ring)` contract:

```python
status = status_for_ring(
    {"gateway": False, "discord": False, "whatsapp": False,
     "deterministic_delivery": True},
    "telegram-paired",
)
assert status["eligible"] is False
assert status["required"] == {"gateway": True, "discord": False, "whatsapp": False}
assert status["missing"] == {"gateway": True}
```

Test unknown ring is denied with a safe reason and test `deterministic_delivery=False` always makes a rollout ineligible.

**Step 2 — GREEN: pure status function**

Keep `rollout_for_ring()`, `preset()`, and `apply()` backward compatible. Add a pure status return containing only ring name, known required flags, current known flags, missing flags, and a safe reason. Do not write config from this function.

**Step 3 — RED/GREEN: one-ring-at-a-time guard**

Add an explicit ordered ring tuple and `can_advance(from_ring, to_ring, current_flags)` that allows only adjacent forward movement and rejects skipping from local developer to Discord/WhatsApp. It must also reject a target whose prerequisite flags are disabled.

**Step 4 — release config**

Extend `release_controls` defaults to include `discord: false` and `whatsapp: false`, matching `current()`. Add a non-secret `active_ring: "local-developer"` only if an existing desktop-local settings service can write it safely and with audit. Otherwise retain ring selection as runtime/manual state for this phase; do not introduce unaudited config writes.

**Verification:**

```bash
unset PYTHONPATH; python -m pytest -q tests/test_release_controls.py tests/test_security_invariants.py
```

---

## Task 5: Add Telegram rollout preflight and deterministic soak coverage

**Objective:** Produce safe evidence that manager-owned Telegram can advance from local developer to paired sandbox without exposing credentials or invoking a real poller in CI.

**Files:**
- Create: `jarvis/gateway/rollout.py`
- Create: `tests/test_gateway_rollout.py`
- Modify: `tests/test_gateway_manager.py`
- Modify: `tests/test_gateway_registry.py`
- Modify: `docs/OPERATIONS_RUNBOOK.md`

**Step 1 — RED: safe preflight report**

Create a pure/injected function such as:

```python
report = telegram_preflight(
    release_flags={"gateway": True, "deterministic_delivery": True},
    runtime_health={"telegram": {"state": "connected"}},
    paired_count=1,
)
assert report == {
    "ready": True,
    "checks": {"gateway_enabled": True, "deterministic_delivery": True,
               "adapter_connected": True, "paired_actor_present": True},
}
```

Test reports contain booleans/enums/counts only—never actor IDs, actor hashes, chat IDs, tokens, message text, database path, or raw health exception details.

**Step 2 — GREEN: injected, credential-free preflight**

Implement `telegram_preflight()` using supplied safe values. Add a narrow adapter function only if needed to obtain `telegram_runtime().manager.health()` and paired count from `GatewayAuthz`; never fetch/print service configuration or credentials.

**Step 3 — RED/GREEN: release gate integration**

Test that `gateway=False`, deterministic delivery disabled, non-connected health, or zero durable pairs makes `ready=False` with an allowed safe failure code. Test a connected/paired state is ready. This remains reporting only; it must not call start/stop/pair/revoke.

**Step 4 — RED/GREEN: deterministic ingress soak**

Using the real `GatewayManager`, `GatewayRegistry(seen_limit=small)`, temporary `GatewayAuthz`, and a fake adapter:

1. Pair an actor durably.
2. Send a bounded burst of unique messages and assert exactly one callback per unique `(platform, conversation, message)`.
3. Replay each message and assert zero additional callbacks.
4. Exceed a small dedup capacity and assert the registry remains bounded and newest keys retain replay protection.
5. Use several threads only after the single-thread behavior is green; assert callback count remains exactly one per duplicate key.
6. Assert an unpaired actor never invokes the callback, even under the same burst.

Do not sleep, poll a network, or assert raw registry internals beyond the current bounded public behavior/controlled test seam.

**Step 5 — RED/GREEN: restart idempotency regression**

Extend manager/runtime tests so consecutive `restart()` calls yield the expected stop/start sequence, never create a second adapter registration, and preserve durable pairing in temp SQLite. This tests lifecycle only; no Bot API request.

**Step 6 — add a developer-safe reporting command (optional only after tests)**

If a manual operator needs CLI output, add `scripts/verify_telegram_rollout.py` that imports the safe preflight adapter, prints JSON-safe booleans/check names only, and exits non-zero when not ready. It must never call `start_runtime()`, `apply_runtime()`, `restart()`, read token values, or print actor metadata.

**Verification:**

```bash
unset PYTHONPATH; python -m pytest -q tests/test_gateway_rollout.py tests/test_gateway_manager.py tests/test_gateway_registry.py tests/test_gateway_telegram_migration.py tests/test_phase8_telegram_control.py
```

---

## Task 6: Update runbook, benchmarks, and manual acceptance gates

**Objective:** Make controlled rollout repeatable, reversible, and explicit about external side effects.

**Files:**
- Modify: `docs/OPERATIONS_RUNBOOK.md`
- Modify: `docs/SECURITY_MODEL.md`
- Modify: `docs/PERFORMANCE_BASELINE.md`
- Modify: `scripts/benchmark_helpers.py`
- Modify: `tests/test_benchmark_helpers.py`
- Modify: `docs/PHASE12_VERIFICATION.md`

**Step 1 — RED/GREEN: benchmark summary safety**

Add tests that `summarize()` handles a bounded timestamp-free list, reports samples/failures/p50/p95, and never accepts/serializes a message payload or actor field. Add only deterministic local benchmark helpers—no CI latency thresholds yet.

**Step 2 — document dashboard operation**

Add a runbook section with:

- default URL `http://127.0.0.1:8000`;
- LAN mode remains disabled by default and cannot be enabled without explicit TLS/origin review;
- default mode never requests a firewall exception;
- dashboard is not an approval, pairing, revoke, OAuth, provider-setting, or gateway lifecycle control plane;
- immediate rollback: set dashboard LAN disabled, apply `gateway-off`/`safe-mode` desktop-locally, then restart only from desktop.

**Step 3 — document Telegram developer-ring acceptance checklist**

Mark every external step as **manual and requires Takeda approval**:

1. Confirm release preflight reports gateway enabled, deterministic delivery, one paired actor, and connected adapter using safe metadata only.
2. Start the application from the desktop-local path.
3. From the already paired sandbox actor, send one safe text query.
4. Verify one reply, one safe audit/trace, remote context, and no desktop/browser capability execution.
5. Replay the same platform message only in a sandbox harness, not against a live client; verify dedup.
6. Stop/restart from Gateway Operations; verify pairing remains durable.
7. Apply `gateway-off` and verify inbound is denied.
8. Record only result/check status and timestamps—never copy message content, IDs, token data, QR URLs, or screen captures containing them.

**Step 4 — document incident and rollback**

Update the existing gateway incident section with exact desktop-local actions, safe health checks, durable pair revoke, and conditions for not restarting. Include SQLite backup/restore preconditions; do not add a raw database-copy command that risks live WAL corruption.

**Verification:**

```bash
unset PYTHONPATH; python -m pytest -q tests/test_benchmark_helpers.py tests/test_security_invariants.py
```

---

## Final verification and acceptance

Run only after every vertical slice is green:

```bash
unset PYTHONPATH; python -m pytest -q tests/test_dashboard_security.py tests/test_release_controls.py tests/test_security_invariants.py tests/test_gateway_rollout.py tests/test_gateway_manager.py tests/test_gateway_registry.py tests/test_gateway_telegram_migration.py tests/test_phase8_telegram_control.py tests/test_benchmark_helpers.py
unset PYTHONPATH; python -m pytest -q
python scripts/verify_frozen.py
git diff --check
git status --short
```

### Completion criteria

- [ ] Dashboard binds loopback by default and does not schedule firewall changes in that mode.
- [ ] Invalid LAN config fails closed before any listener or firewall side effect.
- [ ] LAN mode requires TLS + exact allowlisted origins and remains read-only.
- [ ] Dashboard Ops/admin mutation remains unavailable from LAN and no permissive CORS/origin rule exists.
- [ ] Rate limiting protects auth and command paths without storing sensitive request data.
- [ ] Release status/advance logic is pure, known-flag-only, ordered, and deterministic-delivery-safe.
- [ ] Telegram preflight is credential-free and side-effect-free.
- [ ] Soak tests prove paired ingress, dedup, bounded registry, unpaired denial, and restart idempotency.
- [ ] Runbook gives developer-ring manual acceptance and rollback steps.
- [ ] Focused suite, full suite, frozen verifier, and `git diff --check` pass.
- [ ] No live Telegram polling, credential readout, firewall/UAC action, LAN exposure, commit, or push occurred unless explicitly authorized by Takeda.

## Risks and decisions captured

| Risk | Decision |
|---|---|
| Existing dashboard is designed for phone/LAN control | Preserve its loopback desktop companion behavior; introduce LAN as explicit TLS-only **read-only** mode first, then design remote command context/policy separately. |
| Existing QR/device tokens may be incompatible with new LAN restrictions | Do not migrate or inspect token values in this phase. Reject/disable LAN mutation rather than weakening exposure policy. |
| Uvicorn/FastAPI may be optional locally | Keep security policy pure and fully unit-testable; endpoint tests skip only when dependencies are genuinely absent. |
| Firewall code has OS side effects | Encapsulate invocation behind exposure policy and mock it; default loopback never invokes it. |
| Telegram live smoke could consume private credentials or interfere with polling | CI covers lifecycle with fakes/temp SQLite. Manual live acceptance is explicitly gated by user approval. |
| Workspace is already heavily dirty | Touch only files listed above; do not normalize unrelated line endings, update frozen manifest, or commit unrelated changes. |
