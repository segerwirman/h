"""Framework maturity Phase 14 — release defaults remain fail-safe."""
from __future__ import annotations


def test_safe_mode_mematikan_semua_optional_subsystem():
    from jarvis.core import release_controls

    enabled = {
        "naturalizer": True,
        "plugins": True,
        "gateway": True,
        "discord": True,
        "whatsapp": True,
        "deterministic_delivery": False,
    }

    assert release_controls.preset(enabled, "safe-mode") == {
        "naturalizer": False,
        "plugins": False,
        "gateway": False,
        "discord": False,
        "whatsapp": False,
        "deterministic_delivery": True,
    }


def test_rollout_ring_hanya_mengizinkan_flag_yang_dikenal():
    from jarvis.core.release_controls import rollout_for_ring

    assert rollout_for_ring("discord-sandbox") == {
        "gateway": True,
        "discord": True,
        "whatsapp": False,
    }
    assert rollout_for_ring("unknown") == {}


def test_webhook_verification_tidak_fail_open():
    from jarvis.gateway.platforms.whatsapp_cloud import verify_webhook

    assert verify_webhook("provided", "expected", "challenge") is None
    assert verify_webhook("", "", "challenge") is None
