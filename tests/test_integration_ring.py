"""Phase 26 RED — cross-integration live ring (offline proof ring).

Satu alur deterministik yang membuktikan rangkaian inti (WA0→WA9) berjalan
BERSAMA-SAMA — tanpa kredensial, tanpa jaringan/live provider. Hasil
metadata-only; proof ring, bukan live-proven.
"""
from __future__ import annotations


def _ring(monkeypatch):
    import jarvis.integrations.whatsapp_rollout as wr
    import jarvis.core.call_memory as cm
    import jarvis.runtime.integration_ring as ring

    monkeypatch.setattr(
        wr, "_config_get",
        lambda key, default=None: {
            "integrations.whatsapp.rollout_enabled": True,
            "integrations.whatsapp.allowlist": ["Toko Bunga"],
            "integrations.whatsapp.rate_per_minute": 5,
            "integrations.whatsapp.daily_cap": 50,
        }.get(key, default))
    monkeypatch.setattr(cm, "_memory_enabled", lambda: True)
    return ring


def test_ring_runs_all_core_steps_together(monkeypatch):
    ring = _ring(monkeypatch)
    result = ring.run_ring()
    assert result["ok"] is True
    steps = result["steps"]
    # Semua 10 modul inti ikut dalam ring
    expected = {
        "readiness", "rollout", "countdown", "session", "audio",
        "dialogue", "memory", "proposal", "reservation", "case",
    }
    assert expected <= set(steps)


def test_ring_is_deterministic_offline(monkeypatch):
    ring = _ring(monkeypatch)
    first = ring.run_ring()
    second = ring.run_ring()
    assert first == second          # tanpa kredensial/jaringan → identik


def test_ring_reports_honest_deny_by_default_in_rollout(monkeypatch):
    import jarvis.integrations.whatsapp_rollout as wr
    import jarvis.integrations.whatsapp_readiness as wrd
    import jarvis.runtime.integration_ring as ring

    # Tanpa config/kredensial → rollout deny (disabled), readiness jujur absent
    monkeypatch.setattr(wr, "_config_get", lambda key, default=None: default)
    monkeypatch.setattr(wrd, "_has_secret", lambda key: False)
    result = ring.run_ring()
    assert result["ok"] is True                    # ring tetap jalan
    assert result["steps"]["rollout"]["ok"] is False
    assert result["steps"]["rollout"]["reason"] == "wa_rollout_disabled"
    assert result["steps"]["readiness"]["credentials_ready"] is False


def test_ring_session_flow_produces_expected_states(monkeypatch):
    ring = _ring(monkeypatch)
    steps = ring.run_ring()["steps"]

    assert steps["session"]["status"] == "active"   # approved lokal
    assert steps["audio"]["samples_captured"] > 0   # fake capture
    assert steps["dialogue"]["turn_count"] >= 2     # local ↔ remote
    assert steps["memory"]["count"] == 1            # opt-in config ON
    assert steps["proposal"]["status"] == "approved"
    assert steps["reservation"]["ok"] is True
    assert steps["case"]["disclosed"] is True


def test_ring_countdown_is_running_and_bounded(monkeypatch):
    import jarvis.core.countdown_timer as ct
    import jarvis.runtime.integration_ring as ring

    state = {"now": 1_000.0}
    monkeypatch.setattr(ct, "_now", lambda: state["now"])
    steps = ring.run_ring()["steps"]
    assert steps["countdown"]["status"] == "running"
    assert steps["countdown"]["remaining_s"] == 5
    # Anti-drift: deadline monotonic — timer yang sama selesai tepat waktu
    timer = ct.CountdownTimer()
    assert timer.start(5) is True
    state["now"] += 5.5
    assert timer.status() == "done"


def test_ring_result_is_metadata_only(monkeypatch):
    ring = _ring(monkeypatch)
    result = ring.run_ring()
    text = str(result)
    for forbidden in ("password", "token=", "api_key", "411111"):
        assert forbidden not in text, forbidden


def test_ring_has_no_live_integration_authority(monkeypatch):
    from pathlib import Path

    source = Path(
        "jarvis/runtime/integration_ring.py").read_text(encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes"):
        assert forbidden not in source, forbidden
