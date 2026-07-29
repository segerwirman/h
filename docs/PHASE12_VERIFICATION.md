# Fase 12 — Verification, Rollout, Rollback

## Release controls

`release_controls` is intentionally non-secret and fail-safe:

| Flag | Default | Rollback |
|---|---:|---|
| `naturalizer` | false | false |
| `plugins` | false | false |
| `gateway` | false | false |
| `deterministic_delivery` | true | always true |

Rollback disables optional enhancements only. Deterministic `ConversationDelivery`
remains active.

## Focused evidence

```text
29 passed in 1.47s
AD_HOC_PHASE12_VERIFY_OK
```

## Full-suite blocker observed

`unset PYTHONPATH && python -m pytest -q` cannot collect because the workspace
contains `hermes-agent-main/tests`, whose `tests.conftest` conflicts with the
project `tests.conftest` (`ImportPathMismatchError`).

`unset PYTHONPATH && python -m pytest -q tests` ran 663 tests: 658 passed, 5
failed. The failures are pre-existing baseline conflicts outside Fase 12:

- Curator tests expect automatic archiving; current Fase 9 contract is
  review-first and forbids automatic archive.
- Frozen integrity verifier detects the pre-existing `main.py` Fase 3–6 voice
  delivery changes against the MK50 frozen baseline manifest.

No frozen manifest was rewritten. No legacy behavior was restored merely to
make the suite green.

## Manual acceptance remains required

OAuth browser authentication, live heavy provider behavior, actual voice
barge-in, and real Telegram delivery require user-owned credentials/devices and
were not exercised here.
