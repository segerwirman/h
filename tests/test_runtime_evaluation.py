"""Phase 16 — deterministic evaluation emits metadata only."""
from __future__ import annotations

import asyncio


def test_evaluation_runner_merekam_lulus_tanpa_payload():
    from jarvis.runtime.evaluation import EvaluationCase, EvaluationRunner

    async def scenario():
        return True

    report = asyncio.run(EvaluationRunner().run([
        EvaluationCase("policy-deny", scenario, payload="private task text"),
    ]))

    assert report["total"] == 1
    assert report["passed"] == 1
    assert report["failed"] == 0
    assert report["timed_out"] == 0
    assert report["cases"][0]["id"] == "policy-deny"
    assert report["cases"][0]["outcome"] == "passed"
    assert report["cases"][0]["elapsed_ms"] >= 0
    assert "private task text" not in repr(report)


def test_evaluation_runner_merekam_timeout_tanpa_payload():
    from jarvis.runtime.evaluation import EvaluationCase, EvaluationRunner

    async def blocked():
        await asyncio.sleep(1)

    report = asyncio.run(EvaluationRunner(timeout_s=0.01).run([
        EvaluationCase("tool-timeout", blocked, payload="secret-like payload"),
    ]))

    assert report["timed_out"] == 1
    assert report["cases"][0]["outcome"] == "timeout"
    assert "secret-like payload" not in repr(report)


def test_evaluation_runner_merekam_kegagalan_sebagai_error_class_saja():
    from jarvis.runtime.evaluation import EvaluationCase, EvaluationRunner

    async def broken():
        raise ValueError("private error body")

    report = asyncio.run(EvaluationRunner().run([
        EvaluationCase("registry", broken, payload="private"),
    ]))

    assert report["failed"] == 1
    assert report["cases"][0]["outcome"] == "failed"
    assert report["cases"][0]["error_class"] == "ValueError"
    assert "private error body" not in repr(report)
    assert "private" not in repr(report)
