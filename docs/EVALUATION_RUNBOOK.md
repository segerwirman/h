# Deterministic Evaluation Runbook

## Purpose

Phase 16 evaluation measures local deterministic scenarios without invoking an LLM provider, voice transport, browser, Telegram, dashboard, credential store, or external network.

## Safe evaluation contract

`jarvis.runtime.evaluation.EvaluationRunner` exports only:

- scenario ID;
- outcome: `passed`, `failed`, or `timeout`;
- elapsed milliseconds;
- exception class for failures.

It must never export scenario payload, prompt/task text, tool arguments, model output, actor ID, session ID, token, credential, or raw exception body.

## Scenario classes

| Scenario | Expected result |
|---|---|
| Remote policy deny | `passed` when policy rejects disallowed capability. |
| Unknown tool | `passed` when registry returns controlled failure. |
| Tool deadline | `timeout` after configured local deadline. |
| Capability approval | `passed` when execution requests approval instead of side effect. |

## Benchmark metadata

`scripts/benchmark_helpers.py` reports sample count, failure count, success rate, bounded error-class counts, p50, and p95. Do not add task text or payloads to benchmark output.

## Commands

```bash
unset PYTHONPATH; python -m pytest -q tests/test_runtime_evaluation.py tests/test_benchmark_helpers.py tests/test_policy.py tests/test_capabilities.py
unset PYTHONPATH; python -m pytest -q
python scripts/verify_frozen.py
git diff --check
```

## Promotion gate

Record a benchmark/evaluation report only with hardware, revision, sample count, cold/warm definition, safe aggregate latency, success rate, and failure classes. A failed scenario blocks promotion until reproduced deterministically and fixed. A passing local evaluation is not evidence of live provider, gateway, desktop-control, or network reliability.
