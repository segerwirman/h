"""Framework maturity Phase 3 — bounded cache and latency telemetry."""
from __future__ import annotations

import importlib


def test_ttl_cache_menghindari_loader_sampai_expiry():
    try:
        cache = importlib.import_module("jarvis.runtime.cache")
    except ModuleNotFoundError as exc:
        assert exc.name == "jarvis.runtime.cache"
        raise

    store = cache.TTLCache(clock=lambda: 10.0)
    calls = []

    assert store.get_or_load("weather:bandung", 30, lambda: calls.append(1) or "cerah") == "cerah"
    assert store.get_or_load("weather:bandung", 30, lambda: calls.append(2) or "hujan") == "cerah"
    assert calls == [1]


def test_metrics_menyimpan_hanya_duration_bukan_payload():
    metrics = importlib.import_module("jarvis.runtime.metrics")
    recorder = metrics.LatencyMetrics()

    recorder.record("weather.lookup", 0.125, payload="rahasia")
    summary = recorder.summary("weather.lookup")

    assert summary == {"count": 1, "last_ms": 125.0}
    assert "rahasia" not in repr(summary)


def test_weather_cache_key_normalized():
    cache = importlib.import_module("jarvis.runtime.cache")
    assert cache.normalized_key(" Weather  Bandung ", "TODAY") == "weather bandung:today"


def test_weather_action_cache_menghindari_browser_kedua(monkeypatch):
    from actions import weather_report
    import webbrowser

    calls = []
    weather_report._WEATHER_CACHE.clear()
    monkeypatch.setattr(webbrowser, "open", lambda url: calls.append(url) or True)

    first = weather_report.weather_action({"city": "Bandung", "time": "today"})
    second = weather_report.weather_action({"city": " bandung ", "time": "TODAY"})

    assert "Bandung" in first
    assert "bandung" in second.lower()
    assert len(calls) == 1
