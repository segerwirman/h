# Telegram Controlled-Rollout Acceptance Record

> **Status: NOT EXECUTED.** This is a credential-safe template. Completing it requires an explicit approval to use the local, provisioned Telegram transport. Do not paste secrets, raw actor/chat IDs, message bodies, tokens, PINs, QR/device keys, or screenshots containing them.

## Record metadata

| Field | Value |
|---|---|
| Date/time | _not executed_ |
| Operator | _desktop-local operator_ |
| Candidate ring | `telegram-paired` |
| Build/revision | _record local revision without credentials_ |
| Decision | `pending` / `advance` / `rollback` |

## Preconditions

- [ ] Dashboard remains loopback-only, or any separately approved LAN mode is TLS-backed and read-only.
- [ ] Release status reports the immediate target ring only; no ring is skipped.
- [ ] `gateway` release flag is enabled through desktop-local controls.
- [ ] Telegram runtime is manager-owned (`TelegramGatewayRuntime`).
- [ ] At least one trusted actor has an active durable pair; record only the fact/count or safe actor hash locally.
- [ ] `telegram_preflight(...)` reports all checks true: gateway enabled, manager bound, transport connected, durable pairing.

## Controlled checks

- [ ] Start via desktop-local Gateway Operations and observe safe health `connected`.
- [ ] Deliver one harmless paired **plain-text** inbound request (not `/status` or another slash command, which uses a dedicated command handler outside manager ingress).
- [ ] Confirm the audit/trace contains safe metadata only and the execution context is remote-scoped.
- [ ] Confirm a duplicate inbound identifier is deduplicated in the deterministic test harness.
- [ ] Restart through Gateway Operations; verify safe health and durable pairing again.
- [ ] Record only `GatewayManager.recent_events()` metadata: `lifecycle.started`, `ingress.accepted`, `ingress.deduplicated`, `lifecycle.stopped`, plus trace hashes. It is bounded in-memory rollout evidence; it contains no message body, raw actor ID, conversation ID, or message ID.
- [ ] Confirm remote policy denies desktop-control/browser-open/approval paths in automated tests; do not probe privileged tools on the live transport.
- [ ] Stop runtime at the end of an unsupervised validation session.

## Outcome

| Check | Result | Safe reference / note |
|---|---|---|
| Preflight | pending | _safe health/check booleans only_ |
| Paired inbound | pending | _trace hash only_ |
| Dedup/restart | pending | _test/run reference only_ |
| Rollback drill | pending | _preset/action status only_ |

## Live operator protocol

1. Obtain explicit authorization for one supervised live window; keep dashboard loopback-only and do not open firewall access.
2. Enable `release_controls.gateway` locally, start the manager-owned transport, then confirm `telegram_preflight(...)` using safe booleans only.
3. Send one harmless **plain-text** message from an existing paired actor. Do not use slash commands or privileged controls. Record only `ingress.accepted` plus its trace hash from `recent_events()`.
4. Prove duplicate update handling only with the deterministic test harness. A second visible Telegram message has a new message ID and is not a replay test.
5. Restart only through desktop-local Gateway Operations. Confirm `lifecycle.stopped`, `lifecycle.started`, health, and durable-pair count.
6. End the window: apply `gateway-off`, stop runtime, and record only `acceptance_evidence(...)` metadata. Any mismatch triggers rollback; never troubleshoot by exposing secrets or retrying privileged remote actions.

## Rollback

If any check fails: apply desktop-local `gateway-off`, stop Telegram, revoke the affected durable pairing locally if needed, and mark this record **rollback**. A process restart intentionally expires any pending approval continuation; do not attempt to reconstruct it from durable storage.
