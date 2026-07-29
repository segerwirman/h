# Phase 17 Telegram Production-Ring Plan

**Goal:** Produce durable, credential-safe evidence for Telegram developer-ring promotion without enabling a live transport until explicit authorization.

**Architecture:** Keep deterministic proof in temporary SQLite/fake transport tests. Persist only hashed ingress receipts; acceptance records contain health booleans, safe trace hashes, lifecycle actions, and revision metadata. The live stage is separately authorized and always rolls back to `gateway-off`.

## Steps

1. Add deterministic acceptance recorder returning payload-free evidence for preflight, lifecycle, inbound acceptance, dedup, restart, and rollback.
2. Test incomplete acceptance cannot advance; full deterministic record can mark `telegram-paired` eligible only when immediate ring/prerequisites are true.
3. Add durable receipt TTL/row-capacity tests and manager restart safety coverage.
4. Update `TELEGRAM_ROLLOUT_ACCEPTANCE.md` and operations runbook with exact live operator protocol: plain text only, no privileged commands, rollback first on mismatch.
5. Run focused/full/frozen/diff verification.
6. Only after explicit new authorization: enable gateway release flag, run limited window, send one harmless paired plain-text message, inspect safe events, restart via Gateway Operations, stop and disable gate, fill acceptance record.

## Constraints

- No Telegram polling, credential read, pairing mutation, LAN/firewall, commit, or push in deterministic implementation.
- No raw actor/chat/message IDs, payloads, tokens, or screenshots in records.
- Dedup live replay is not required: prove it deterministically with a repeated update ID.

## Verification

```bash
unset PYTHONPATH; python -m pytest -q tests/test_telegram_rollout.py tests/test_gateway_registry.py tests/test_gateway_manager.py tests/test_release_controls.py
unset PYTHONPATH; python -m pytest -q
python scripts/verify_frozen.py
git diff --check
```