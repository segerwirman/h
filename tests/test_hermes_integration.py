"""Retirement contract: legacy wording routes native; CLI stays impossible."""
from __future__ import annotations

import time

from jarvis.core.router import Intent, IntentRouter
from jarvis.integrations.hermes.bridge import HermesBridge, is_enabled


def test_legacy_wording_routes_to_native_agent():
    classified = IntentRouter().classify(
        "suruh hermes buatkan laporan penjualan"
    )
    assert classified.intent is Intent.NATIVE_AGENT_TASK
    assert classified.slots["tier"] == 3
    assert "laporan penjualan" in classified.slots["task"]


def test_native_message_intent():
    classified = IntentRouter().classify(
        "kirim pesan ke whatsapp halo dari Jarvis"
    )
    assert classified.intent is Intent.NATIVE_AGENT_TASK
    assert classified.slots["tier"] == 2
    assert classified.slots["platform"] == "whatsapp"


def test_rules_path_remains_sub_millisecond():
    router = IntentRouter()
    started = time.perf_counter()
    for _ in range(300):
        router._rules("kirim pesan ke whatsapp halo")
        router._rules("matikan wifi")
        router._rules("suruh hermes riset pasar")
    elapsed_ms = (time.perf_counter() - started) * 1000 / 900
    assert elapsed_ms < 1.0


def test_bridge_is_permanently_inert_even_with_stale_executable():
    HermesBridge._reset_for_tests()
    bridge = HermesBridge.get()
    bridge._resolved = "hermes"

    assert is_enabled() is False
    assert bridge.available() is False
    assert bridge.run_task("apa saja")["ok"] is False
    assert bridge.send_direct("telegram", "halo")["ok"] is False
