"""Phase 14 — benchmark harness reports bounded, payload-free latency stats."""
from __future__ import annotations


def test_benchmark_summary_menghasilkan_p50_p95_tanpa_payload():
    from scripts.benchmark_helpers import summarize

    report = summarize("memory-search", [1.0, 2.0, 3.0], failures=1)

    assert report == {
        "name": "memory-search",
        "samples": 3,
        "failures": 1,
        "success_rate": 0.75,
        "error_classes": {},
        "p50_ms": 2.0,
        "p95_ms": 3.0,
    }


def test_benchmark_summary_kosong_aman():
    from scripts.benchmark_helpers import summarize

    assert summarize("empty", []) == {
        "name": "empty", "samples": 0, "failures": 0,
        "success_rate": 0.0, "error_classes": {},
        "p50_ms": 0.0, "p95_ms": 0.0,
    }


def test_benchmark_summary_menghitung_success_rate_dan_error_class_terbatas():
    from scripts.benchmark_helpers import summarize

    report = summarize("gateway", [2.0, 4.0], failures=1,
                       error_classes=["TimeoutError", "TimeoutError", "ValueError"])

    assert report["success_rate"] == 2 / 3
    assert report["error_classes"] == {"TimeoutError": 2, "ValueError": 1}
