# Operations Runbook

## Safety boundaries

- **Dashboard default:** loopback only (`127.0.0.1`). It does not create a firewall rule.
- **LAN dashboard:** an explicit, TLS-backed, exact-origin configuration may expose only read-only API snapshots. Commands, QR/device login, uploads, phone audio, and WebSocket command intake are denied.
- **Desktop-local only:** Gateway Operations (pair/revoke/restart), approval decisions, OAuth, provider settings, and release-control changes are never dashboard actions.
- Never place a token, PIN, QR key, actor ID, device token, OAuth secret, or connection string in a runbook, test output, ticket, or chat transcript.

## Dashboard exposure

The checked-in default is intentionally safe:

```yaml
dashboard:
  lan_enabled: false
  bind_host: "127.0.0.1"
  lan_read_only: true
  require_tls_for_lan: true
  lan_allowed_origins: []
```

A LAN change is a separately approved deployment operation. Before it is considered:

1. Confirm a valid TLS certificate/key is already provisioned outside this repository and no credential needs to be printed or copied.
2. Keep `lan_read_only: true`.
3. Set one or more exact HTTPS origins, e.g. `https://host.example.test:8000`; do not use `*`, HTTP, paths, credentials, queries, or fragments.
4. Run the focused dashboard suite below. Invalid TLS/origin settings must fail before any listener/firewall side effect.
5. Verify the listener and firewall state locally through the desktop operator workflow. Do not enable a LAN listener merely for testing in an untrusted network.

To return to the default posture: set `lan_enabled: false`, stop the dashboard, and restart it through the local desktop application. Remove any separately approved firewall rule through the same local administration procedure.

## Safe mode and rollback

Apply `release_controls.preset(current, "safe-mode")`. This disables optional enhancements and restores deterministic delivery. It is a local control-plane operation, not a dashboard operation.

For a gateway-specific rollback, use `release_controls.preset(current, "gateway-off")`, then stop the affected transport using desktop-local Gateway Operations. Verify health reports `stopped` before any further investigation.

## Gateway incident

1. Stop the affected adapter through local Gateway Operations.
2. Revoke the affected platform/actor pairing through the same local UI; it displays only an actor hash.
3. Inspect only safe health, trace hash, and audit metadata.
4. Verify durable pairing, inbound deduplication, and remote policy denial before a local restart. Gateway receipts retain only hashed ingress keys with bounded TTL/capacity; a replay after restart is denied before dispatch.
5. If an approval was pending, treat it as expired after restart: continuations are process-local, TTL-bound, and intentionally unrecoverable.

## Dashboard asset and backpressure posture

- `dashboard/static/crypto-js.min.js` is a release-vendored asset. Dashboard startup never downloads scripts and `/static/crypto.js` never redirects to a CDN. A missing vendor asset returns `503`; repair the local release installation rather than bypassing this boundary.
- Dashboard responses set a same-origin CSP. Do not add third-party scripts without a reviewed local vendor/update process.
- Command ingress is bounded: HTTP returns `429` when the queue is full; WebSocket command ingress is rate-limited and closes the offending socket with code `4008`. Do not increase limits without load evidence.
- Telegram `/stop` is desktop-local when manager-bound. Remote actors receive a local-approval response; use Gateway Operations for cancellation.

## Trusted-local plugin activation

- Plugins are local manifests, not a marketplace: JARVIS never discovers, downloads, imports, or executes a plugin automatically from a network source.
- `PluginRuntime.activate()` validates every manifest before reserving a contributed tool or persisting it. Invalid manifests remain inactive and cannot block a tool name.
- On restart, saved manifests follow the same validation path. A stale or malformed record is ignored; valid independent records may still restore.
- Plugin activation, disablement, and release-control changes are desktop-local control-plane actions. Do not activate plugins through remote gateway commands or a LAN dashboard.
- Plugin records must never include credentials, tokens, raw remote identities, or task payloads. Repair a rejected local manifest rather than weakening validation.

## Controlled rollout rings

1. `local-developer`
2. `desktop-trusted`
3. `telegram-paired`
4. `discord-sandbox`
5. `whatsapp-sandbox`

Advance exactly one ring at a time. `release_controls.status_for_ring(...)` is a pure status check; it does not mutate configuration or start a transport. `can_advance_ring(...)` permits only the immediate next known ring. A rollback uses a preset rather than moving a ring backward.

### Telegram developer-ring acceptance

Do this only after explicit authorization to use the provisioned local transport; do not enter, print, or inspect credentials.

1. Run automated preflight with a manager-owned runtime. It must report all of: `gateway_enabled`, `manager_bound`, `transport_connected`, and `durable_pairing`.
2. Through desktop-local Gateway Operations, start the Telegram runtime and confirm safe health metadata only.
3. From an already paired trusted actor, send one harmless text request. Confirm one audit/trace outcome and a remote `ExecutionContext`; do not test desktop-control, browser-open, approval, or privileged tools remotely.
4. Repeat the same inbound message identifier only in a controlled test harness and confirm it is deduplicated.
5. Restart Telegram through Gateway Operations, re-check safe health and durable pairing, then stop it if the ring is not being actively supervised.
6. On any unexpected behavior, apply `gateway-off`, stop the adapter, and revoke the relevant pairing locally.

No Discord or WhatsApp rollout begins until this checklist is recorded as passed without raw identifiers or credentials.

## Backup and restore

1. Stop mutation sources first (gateway transports, jobs, and relevant desktop operations).
2. Back up SQLite database files as a consistent set, including WAL/SHM files when present.
3. Restore only into an isolated copy.
4. Run targeted integrity and pairing/authorization tests against the isolated copy before reconnecting any integration.
5. Never overwrite a live database during an incident without an approved local recovery action.

## Verification commands

Run from the repository root with the isolated project interpreter environment:

```bash
unset PYTHONPATH; python -m pytest -q tests/test_dashboard_security.py tests/test_release_controls.py tests/test_telegram_rollout.py
unset PYTHONPATH; python -m pytest -q
python scripts/verify_frozen.py
git diff --check
```

Benchmark summaries must contain counts, failure count, and latency aggregates only—never command text, message body, actor identifier, token, or payload.
