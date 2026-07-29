# Telegram GatewayManager Lifecycle Implementation Plan

> **For Hermes:** Execute task-by-task with TDD; keep all privileged controls desktop-local.

**Goal:** Make the live Telegram polling service use the real `GatewayManager` ingress and lifecycle boundary, so pairing, deduplication, scoped execution context, health, and restart controls have one authority.

**Architecture:** Keep `TelegramService` as the transport/runtime owner for python-telegram-bot polling. Register a thin runtime adapter with one application-owned `GatewayManager`; every Telegram inbound update is normalized and sent to `GatewayManager.receive()`. The manager invokes a dispatch callback only after durable pairing and deduplication have passed. Do not use `jarvis.gateway.manager.MANAGER`, because it is a no-op singleton.

**Tech Stack:** Python 3.11, python-telegram-bot, SQLite/WAL gateway authz, PyQt6 desktop operations panel, pytest.

---

## Current evidence

- `jarvis/gateway/manager.py:39-50` owns pairing and deduplication but `MANAGER` at line 63 uses a no-op callback.
- `jarvis/agent/adapters/telegram.py:62-63` creates a separate `GatewayRegistry`; its `_authorized()` at lines 143-150 uses the legacy Telegram allowlist instead of durable gateway pairing.
- `tests/test_gateway_telegram_migration.py` covers only the platform adapter, not the live `TelegramService` path.
- The desktop Gateway Operations panel is already the local-only place for gateway health/restart/revoke/approval.

## Non-negotiable security rules

- No token, chat ID, raw sender ID, raw callback payload, or tool arguments in logs/audit/UI DTOs.
- Unauthorized or unpaired inbound requests must produce no reply.
- `GatewayManager.receive()` is the only final ingress gate.
- Pairing uses `GatewayAuthz` durable state; do not maintain a second security decision in Telegram handlers.
- Preserve existing Telegram runtime availability checks (`telegram_control`) as configuration/lifecycle readiness, not as an authorization substitute.
- Dashboard remains read-only/local-first; do not add remote gateway mutations.

## Task 1: Add red runtime-ingress tests

**Objective:** Prove live Telegram normalization delegates to the application-owned manager instead of invoking dispatch directly.

**Files:**
- Modify: `tests/test_gateway_telegram_migration.py`
- Inspect/modify later: `jarvis/agent/adapters/telegram.py`

1. Create a fake manager capturing `receive(platform, message_id, conversation_id, actor_id, text)`.
2. Build a minimal fake Telegram update/message and exercise the real text handler seam.
3. Assert the manager receives `platform="telegram"` and normalized message/conversation/actor values.
4. Assert an unpaired manager result produces no `reply_text` call.
5. Run:
   ```bash
   unset PYTHONPATH; python -m pytest -q tests/test_gateway_telegram_migration.py
   ```
   Expected initially: failure because the live service uses its own registry/legacy allowlist.

## Task 2: Build an application-owned Telegram gateway runtime

**Objective:** Connect one `GatewayManager` to the actual Telegram service without using the no-op singleton.

**Files:**
- Modify: `jarvis/agent/adapters/telegram.py`
- Modify or create: `jarvis/gateway/runtime.py`
- Test: `tests/test_gateway_telegram_migration.py`

1. Create an explicit application runtime factory receiving a dispatch callback.
2. Register the real Telegram lifecycle adapter with that manager; adapter `start`, `stop`, and `health` must delegate to the current `TelegramService` instance.
3. Keep service construction lazy so disabled Telegram does not initialize python-telegram-bot.
4. Do not import credentials or call the network during construction.
5. Add a test that manager health reflects the live adapter state and manager `start/stop` calls the runtime owner.

## Task 3: Move inbound authorization to durable pairing

**Objective:** Eliminate the duplicated final authorization gate in `TelegramService`.

**Files:**
- Modify: `jarvis/agent/adapters/telegram.py`
- Modify: `jarvis/gateway/authz.py` only if a safe migration helper is necessary
- Test: `tests/test_gateway_authz.py`, `tests/test_gateway_telegram_migration.py`

1. Let the service perform only structural update validation and normalization.
2. Invoke `manager.receive(...)`; its boolean result is the only decision whether dispatch proceeds.
3. Preserve silent rejection (`False` means no reply).
4. If legacy `telegram_control.allowed_ids()` must remain temporarily for migration, treat it as bootstrap provisioning only and document/remove the final gate. Do not intersect two hidden allowlists indefinitely.
5. Add tests for unpaired denial, durable pair success after service recreation, and duplicate message rejection.

## Task 4: Create scoped remote dispatch context

**Objective:** Ensure accepted Telegram messages enter the agent with a remote actor/session scope and restricted toolsets.

**Files:**
- Modify: `jarvis/agent/adapters/telegram.py`
- Inspect/modify: `jarvis/agent/dispatch.py`, `jarvis/agent/execution_context.py`
- Test: `tests/test_execution_context.py`, `tests/test_gateway_telegram_migration.py`

1. In the manager callback, derive a stable session key from normalized Telegram conversation identity without exposing it in logs.
2. Create `ExecutionContext(source="telegram", surface="remote", ...)` using only the intended remote toolsets.
3. Route the callback to existing dispatch/agent-loop entry points; do not call tools directly from adapter handlers.
4. Verify remote actors never inherit local desktop memory or local-admin capability.
5. Add a test proving context source/surface/toolsets and actor scoping are correct.

## Task 5: Rewire local operational lifecycle controls

**Objective:** Make the desktop Gateway Operations UI report and restart the real manager-bound Telegram runtime.

**Files:**
- Modify: `jarvis/ops/api.py`
- Modify: `jarvis/ui/gateway_operations.py`
- Modify: `jarvis/ui/settings_messaging.py`
- Test: `tests/test_gateway_operations.py`, `tests/test_phase8_telegram_control.py`

1. Inject the application-owned runtime manager into `OpsAPI`; never default lifecycle mutation to the global no-op manager.
2. Have Restart Telegram execute manager `stop("telegram")` then `start("telegram")` in a worker after RBAC/audit succeeds.
3. Preserve existing `telegram_control.apply_runtime()` only for applying configuration, with its UI label scoped accordingly.
4. Render safe health state only; no exception text, token, chat ID, or sender ID.
5. Test that desktop restart reaches the real lifecycle owner and unauthorized role cannot trigger it.

## Task 6: Regression, credential-free verification, and staged smoke test

**Objective:** Verify behavior without consuming or revealing Telegram credentials, then define the opt-in live smoke test.

**Files:**
- Modify as needed: `docs/OPERATIONS_RUNBOOK.md`
- Test: gateway, policy, operations, Telegram, UI suites

1. Run focused suites:
   ```bash
   unset PYTHONPATH; python -m pytest -q \
     tests/test_gateway_manager.py tests/test_gateway_authz.py \
     tests/test_gateway_telegram_migration.py tests/test_phase8_telegram_control.py \
     tests/test_gateway_operations.py tests/test_execution_context.py
   ```
2. Run canonical verification:
   ```bash
   unset PYTHONPATH; python -m pytest -q
   python scripts/verify_frozen.py
   git diff --check
   ```
3. Only if the user explicitly opts in and Telegram credentials/pairing are already provisioned outside chat: start locally, send one paired sandbox text, verify exactly one response, send duplicate update fixture/no-op equivalent, then stop it.
4. Record only outcome/status in the runbook; never record secrets or raw message contents.

## Risks and tradeoffs

- A central manager migration must not accidentally break existing `/confirm`, voice, or callback-query paths; normalize each ingress type deliberately.
- It is safer to keep a short compatibility bridge for provisioning than to remove all legacy configuration at once, but authorization must have one final authority from the first migration release.
- In-memory approval continuations remain process-local; a Telegram message approval does not create a remote admin action because approval mutation stays desktop-local.

## Definition of done

- Actual Telegram polling ingress reaches `GatewayManager.receive()`.
- Pairing, dedup, and remote execution context are enforced centrally.
- Gateway Operations restart/health targets the runtime owner rather than a no-op manager.
- All targeted and full tests pass, frozen integrity passes, and `git diff --check` is clean.
