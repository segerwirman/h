"""Payload-free latency summary helper for controlled local benchmarks."""
from __future__ import annotations

from collections import Counter


def summarize(name: str, samples: list[float], failures: int = 0,
              error_classes: list[str] | None = None) -> dict:
    values = sorted(max(0.0, float(value)) for value in samples)
    failure_count = max(0, int(failures))
    errors = Counter(str(value)[:80] for value in (error_classes or []) if value)
    total = len(values) + failure_count
    if not values:
        return {
            "name": str(name), "samples": 0, "failures": failure_count,
            "success_rate": 0.0, "error_classes": dict(errors),
            "p50_ms": 0.0, "p95_ms": 0.0,
        }
    p50_index = (len(values) - 1) // 2
    p95_index = min(len(values) - 1, int((len(values) * 0.95) + 0.9999) - 1)
    return {
        "name": str(name), "samples": len(values), "failures": failure_count,
        "success_rate": len(values) / total if total else 0.0,
        "error_classes": dict(errors),
        "p50_ms": values[p50_index], "p95_ms": values[p95_index],
    }


if __name__ == "__main__":
    print(summarize("example", []))
