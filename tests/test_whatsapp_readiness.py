"""Phase WA0 RED — WhatsApp readiness gate.

Gate boolean murni: dependency check, credential absence check, toggle
config, dan allowlist policy placeholder — tanpa kredensial nyata, tanpa
jaringan, tanpa live client.
"""
from __future__ import annotations

_READINESS_KEYS = (
    "dependency_available", "credentials_ready", "toggle_enabled",
    "allowlist_configured", "client_available", "service_available",
)


def test_readiness_returns_boolean_gate_only():
    # RED: jarvis/integrations/whatsapp_readiness.py belum ada
    from jarvis.integrations.whatsapp_readiness import readiness

    report = readiness()
    assert set(report) == set(_READINESS_KEYS)
    for value in report.values():
        assert isinstance(value, bool)


def test_client_and_service_available_match_official_api_shape():
    from jarvis.integrations.whatsapp_readiness import (
        client_available,
        service_available,
    )

    assert callable(client_available) and callable(service_available)
    assert isinstance(client_available(), bool)
    assert isinstance(service_available(), bool)


def test_readiness_is_deterministic_without_credentials(monkeypatch):
    from jarvis.integrations.whatsapp_readiness import readiness

    monkeypatch.setattr("jarvis.core.secrets_store.get", lambda _k: None)
    monkeypatch.setattr("jarvis.core.config.get", lambda _k, default=None: default)
    report = readiness()
    assert report["credentials_ready"] is False      # absent, bukan crash
    assert report["client_available"] is False


def test_dependency_missing_blocks_client_even_with_credentials(monkeypatch):
    from jarvis.integrations.whatsapp_readiness import readiness

    monkeypatch.setattr(
        "jarvis.integrations.whatsapp_readiness._dependency_available",
        lambda: False)
    monkeypatch.setattr("jarvis.core.secrets_store.get", lambda _k: "x")
    report = readiness()
    assert report["dependency_available"] is False
    assert report["client_available"] is False
    assert report["service_available"] is False


def test_toggle_and_allowlist_gate_service_availability(monkeypatch):
    from jarvis.integrations.whatsapp_readiness import readiness

    def _config(key, default=None):
        return {"integrations.whatsapp.enabled": True,
                "integrations.whatsapp.allowed_ids": ["+6281111"]}.get(key, default)

    monkeypatch.setattr("jarvis.core.secrets_store.get", lambda _k: "x")
    monkeypatch.setattr("jarvis.core.config.get", _config)
    monkeypatch.setattr(
        "jarvis.integrations.whatsapp_readiness._dependency_available",
        lambda: True)
    report = readiness()
    assert report["credentials_ready"] is True
    assert report["toggle_enabled"] is True
    assert report["allowlist_configured"] is True
    assert report["client_available"] is True
    assert report["service_available"] is True

    # toggle off → service tidak available walau semuanya siap
    def _config_off(key, default=None):
        return {"integrations.whatsapp.enabled": False,
                "integrations.whatsapp.allowed_ids": ["+6281111"]}.get(key, default)

    monkeypatch.setattr("jarvis.core.config.get", _config_off)
    assert readiness()["service_available"] is False

    # allowlist kosong → service tidak available
    def _config_no_allow(key, default=None):
        return {"integrations.whatsapp.enabled": True}.get(key, default)

    monkeypatch.setattr("jarvis.core.config.get", _config_no_allow)
    assert readiness()["allowlist_configured"] is False
    assert readiness()["service_available"] is False


def test_readiness_never_writes_to_secrets_store(monkeypatch):
    from jarvis.integrations.whatsapp_readiness import readiness

    def _forbid(*_args, **_kwargs):
        raise AssertionError("readiness menulis ke secrets store!")

    monkeypatch.setattr("jarvis.core.secrets_store.set", _forbid)
    monkeypatch.setattr("jarvis.core.secrets_store.delete", _forbid)
    report = readiness()
    assert all(isinstance(v, bool) for v in report.values())


def test_readiness_summary_is_metadata_only():
    from jarvis.integrations.whatsapp_readiness import readiness_summary

    summary = readiness_summary()
    assert "dependency_available:" in summary
    assert "service_available:" in summary


def test_probe_whatsapp_uses_readiness_gate(monkeypatch):
    # Integrasi: canary Phase 25 kini mendapat status nyata dari gate WA0.
    from jarvis.runtime.credential_free_probe import probe_providers

    monkeypatch.setattr("jarvis.core.secrets_store.get", lambda _k: None)
    monkeypatch.setattr("jarvis.core.config.get", lambda _k, default=None: default)
    report = probe_providers()
    assert report["whatsapp"] in {"ready", "absent", "disabled"}
