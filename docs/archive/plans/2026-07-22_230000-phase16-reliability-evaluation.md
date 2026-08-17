# Phase 16 Reliability and Evaluation Plan

**Goal:** Add deterministic, payload-free evaluation evidence for JARVIS agent execution, tool timeout behavior, and latency/failure summaries without live providers, voice, or gateway traffic.

**Architecture:** A small evaluation module consumes injected async scenarios and records only scenario ID, outcome, iteration count, elapsed milliseconds, and error class. It must never store prompt/task text, tool args, credentials, raw model responses, actor IDs, or payloads. Benchmark helpers remain metadata-only.

## TDD slices

1. Create `jarvis/runtime/evaluation.py` with an `EvaluationRunner` that executes injected async cases under a deadline.
2. Test pass/fail/timeout outcomes and prove no case payload appears in output.
3. Add a deterministic suite for agent-loop availability-independent scenarios: policy deny, unknown tool, tool timeout.
4. Extend `scripts/benchmark_helpers.py` with aggregate success rate and bounded error-class counts; test empty/nonempty reports.
5. Add `docs/EVALUATION_RUNBOOK.md` covering controlled local execution, thresholds, and prohibited live/secret data.
6. Run focused/full/frozen/diff verification.

## Constraints

- No live provider, Gemini Live, Telegram polling, LAN, firewall, browser, credential, commit, or push.
- Keep agent cancellation limitations explicit: a timeout reports failure; external side effects require their own cooperative cancellation contract.
- Evaluation output is safe for audit/export.

## Verification

```bash
unset PYTHONPATH; python -m pytest -q tests/test_runtime_evaluation.py tests/test_benchmark_helpers.py tests/test_policy.py tests/test_capabilities.py
unset PYTHONPATH; python -m pytest -q
python scripts/verify_frozen.py
git diff --check
```

## Acceptance

- Deterministic scenarios report pass/fail/timeout with elapsed metadata only.
- No output field contains case payload.
- Benchmark report includes count, failures, success rate, p50, p95, and bounded error-class counts.
- Full regression/frozen/diff pass.
