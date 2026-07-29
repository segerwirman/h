"""Fase 12 — rollout flags preserve deterministic rollback."""
from __future__ import annotations

import importlib


def test_rollback_mematikan_hanya_optional_enhancements():
    try:
        controls = importlib.import_module("jarvis.core.release_controls")
    except ModuleNotFoundError:
        controls = None

    assert controls is not None
    config = {
        "naturalizer": True,
        "plugins": True,
        "gateway": True,
        "deterministic_delivery": True,
    }

    rolled_back = controls.rollback(config)

    assert rolled_back == {
        "naturalizer": False,
        "plugins": False,
        "gateway": False,
        "deterministic_delivery": True,
    }


def test_rollout_hanya_mengaktifkan_flag_allowlisted():
    controls = importlib.import_module("jarvis.core.release_controls")
    assert controls.apply({"naturalizer": False}, {"naturalizer": True,
                                                     "unknown": True}) == {
        "naturalizer": True
    }


def test_current_memakai_default_rollback_aman_bila_config_tidak_lengkap(monkeypatch):
    controls = importlib.import_module("jarvis.core.release_controls")
    monkeypatch.setattr(controls.config, "section", lambda _: {"plugins": True})

    assert controls.current() == {
        "naturalizer": False,
        "plugins": True,
        "gateway": False,
        "discord": False,
        "whatsapp": False,
        "deterministic_delivery": True,
    }


def test_status_ring_melaporkan_gate_yang_belum_terpenuhi_tanpa_mutasi():
    controls = importlib.import_module("jarvis.core.release_controls")

    status = controls.status_for_ring(
        "telegram-paired",
        current_flags={"gateway": False, "discord": False, "whatsapp": False},
        prerequisites={"dashboard_local_first": True, "telegram_preflight": False},
    )

    assert status["ring"] == "telegram-paired"
    assert status["eligible"] is False
    assert status["missing_flags"] == ["gateway"]
    assert status["missing_prerequisites"] == ["telegram_preflight"]


def test_advance_ring_hanya_mengizinkan_satu_langkah_maju():
    controls = importlib.import_module("jarvis.core.release_controls")

    assert controls.can_advance_ring("local-developer", "desktop-trusted") is True
    assert controls.can_advance_ring("local-developer", "telegram-paired") is False
    assert controls.can_advance_ring("telegram-paired", "local-developer") is False
    assert controls.can_advance_ring("unknown", "telegram-paired") is False
