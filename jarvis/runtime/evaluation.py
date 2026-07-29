"""Deterministic, payload-free local evaluation runner."""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class EvaluationCase:
    id: str
    scenario: Callable[[], Awaitable[object]]
    payload: str = ""


class EvaluationRunner:
    def __init__(self, *, timeout_s: float = 1.0) -> None:
        self.timeout_s = max(0.001, float(timeout_s))

    async def run(self, cases: list[EvaluationCase]) -> dict:
        rows: list[dict] = []
        for case in cases:
            started = time.perf_counter()
            row = {"id": str(case.id)[:80], "outcome": "failed"}
            try:
                result = await asyncio.wait_for(case.scenario(), timeout=self.timeout_s)
                row["outcome"] = "passed" if result is not False else "failed"
            except asyncio.TimeoutError:
                row["outcome"] = "timeout"
            except Exception as exc:  # noqa: BLE001
                row["error_class"] = type(exc).__name__[:80]
            row["elapsed_ms"] = round((time.perf_counter() - started) * 1000, 3)
            rows.append(row)
        return {
            "total": len(rows),
            "passed": sum(row["outcome"] == "passed" for row in rows),
            "failed": sum(row["outcome"] == "failed" for row in rows),
            "timed_out": sum(row["outcome"] == "timeout" for row in rows),
            "cases": rows,
        }
