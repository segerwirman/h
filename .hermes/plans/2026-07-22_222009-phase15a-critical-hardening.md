# Phase 15A Critical Hardening Implementation Plan

> **For Hermes:** Execute task-by-task with strict RED → GREEN TDD. Do not enable LAN, firewall, live Telegram polling, read credentials, commit, or push.

**Goal:** Remove dashboard runtime CDN fallback, bound dashboard WebSocket commands, make Telegram ingress dedup durable with bounded retention, and route remote Telegram controls through manager policy/audit seams.

**Architecture:** Dashboard hardening stays in `dashboard/server.py` and static assets. Gateway dedup moves from process-local `GatewayRegistry` to a payload-free SQLite receipt store that marks a hashed ingress key before dispatch. Telegram command controls become declared remote capabilities enforced through `GatewayManager`/policy rather than direct adapter mutation.

**Tech Stack:** Python 3.11, FastAPI/WebSocket, SQLite/WAL, pytest.

---

## Scope order

1. Vendor-only dashboard CryptoJS and CSP.
2. Dashboard WebSocket queue/rate/message bounds.
3. Durable Telegram receipt ledger with TTL/capacity cleanup.
4. Manager-owned remote command/callback control policy and safe audit.
5. Focused/full/frozen/diff verification.

## Task 1: Vendor-only dashboard asset

**Files:**
- Modify: `dashboard/server.py:1-110,514-521`
- Test: `tests/test_dashboard_security.py`

1. Add a red test: `/static/crypto.js` serves only local vendor file; missing vendor returns 503 and never redirect/downloads.
2. Run focused test; expect failure due CDN redirect/import-time download.
3. Remove `_CRYPTOJS_CDN`, `_ensure_crypto_js()`, import-time call, redirect fallback.
4. Add strict baseline CSP to HTML responses compatible with existing inline dashboard scripts/styles; no external script source.
5. Re-run focused test green.

## Task 2: WebSocket command backpressure

**Files:**
- Modify: `dashboard/server.py:377-400,806-839`
- Test: `tests/test_dashboard_security.py`

1. Add red tests: bounded command queue rejects overload before enqueue; authenticated local WebSocket command rate is limited.
2. Run focused tests; expect failure.
3. Use `asyncio.Queue(maxsize=<bounded config/default>)`, reuse bounded payload-free limiter keyed by safe client identity/token hash, reject oversized text/encrypted frames, close/throttle violating connection.
4. Preserve LAN read-only rejection.
5. Re-run focused tests green.

## Task 3: Durable inbound receipt ledger

**Files:**
- Create: `jarvis/gateway/receipts.py`
- Modify: `jarvis/gateway/registry.py`, `jarvis/gateway/runtime.py` if injection needed
- Test: `tests/test_gateway_registry.py`, `tests/test_gateway_manager.py`

1. Add red test: accepted Telegram message ID stays rejected after a new registry process instance using same temporary SQLite path.
2. Add red test: receipt stores no raw platform/conversation/message text and TTL/capacity cleanup remains bounded.
3. Run tests; expect failure.
4. Implement SQLite WAL receipt store with hashed ingress key, atomic `INSERT OR IGNORE`, TTL expiry cleanup, bounded row count, no payload/raw actor values.
5. Keep ephemeral fallback only when no durable path explicitly injected for isolated compatibility tests.
6. Re-run focused tests green.

## Task 4: Remote Telegram controls

**Files:**
- Modify: `jarvis/agent/adapters/telegram.py`, `jarvis/gateway/manager.py`, possibly `jarvis/ops/audit_log.py`
- Test: `tests/test_gateway_telegram_migration.py`, `tests/test_phase8_telegram_control.py`

1. Add red tests proving `/stop` and cron callback are denied/approval-gated under remote context unless declared remote-safe; verify safe audit metadata only.
2. Run focused test; expect failure because controls call dispatch/cron directly.
3. Introduce manager-owned control request seam with declared capability/risk; deny high-risk controls or request desktop-local approval. Keep safe read-only status commands explicitly allowed if desired.
4. Re-run focused tests green.

## Task 5: Documentation and validation

**Files:**
- Modify: `docs/OPERATIONS_RUNBOOK.md`, `docs/TELEGRAM_ROLLOUT_ACCEPTANCE.md`

1. Document vendor-only dashboard asset, WS limits, durable receipt semantics, and command-control restrictions.
2. Run:

```bash
unset PYTHONPATH; python -m pytest -q tests/test_dashboard_security.py tests/test_gateway_registry.py tests/test_gateway_manager.py tests/test_gateway_telegram_migration.py tests/test_phase8_telegram_control.py
unset PYTHONPATH; python -m pytest -q
python scripts/verify_frozen.py
git diff --check
```

3. Do not commit until user explicitly requests and dirty-workspace ownership is separated.

## Acceptance criteria

- No import-time dashboard network download and no CDN redirect/fallback.
- WS command path has queue, message, and request-rate bounds.
- Replayed inbound Telegram ID is rejected after process restart without retaining raw inbound data.
- Remote Telegram controls do not bypass policy/approval/audit.
- All focused/full/frozen/diff checks exit 0.

## Risks

- Existing dashboard uses inline scripts/styles; CSP must be introduced without breaking local dashboard flow.
- Durable receipt insert-before-dispatch yields at-most-once behavior; a crash after receipt insertion can drop a request. This is safer than replaying remote side effects and should be documented.
- Telegram `/stop` semantics need an explicit remote capability policy; no silent behavior change.