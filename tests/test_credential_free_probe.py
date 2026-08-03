"""Phase 25 RED — credential-free canary probe.

Status provider boolean (ready/absent/disabled/skipped/unknown) tanpa
menyimpan, meng-log, mengirim, atau mengembalikan nilai kredensial.
"""
from __future__ import annotations

_PROVIDERS = ("telegram", "google", "llm", "voice", "image", "whatsapp")
_VALID_STATUS = {"ready", "absent", "disabled", "skipped", "unknown"}


def test_probe_providers_returns_all_providers_with_valid_status():
    # RED: jarvis/runtime/credential_free_probe.py belum ada
    from jarvis.runtime.credential_free_probe import probe_providers

    report = probe_providers()
    assert set(report) == set(_PROVIDERS)
    assert set(report.values()) <= _VALID_STATUS


def test_probe_never_exposes_secret_values():
    from jarvis.runtime.credential_free_probe import probe_providers

    report = probe_providers()
    for status in report.values():
        assert status in _VALID_STATUS          # hanya label, bukan nilai
        assert len(status) < 16


def test_probe_does_not_write_to_secrets_store(monkeypatch):
    from jarvis.runtime.credential_free_probe import probe_providers

    def _forbid(*_args, **_kwargs):
        raise AssertionError("probe menulis ke secrets store!")

    monkeypatch.setattr("jarvis.core.secrets_store.set", _forbid)
    monkeypatch.setattr("jarvis.core.secrets_store.delete", _forbid)
    report = probe_providers()
    assert set(report.values()) <= _VALID_STATUS


def test_probe_is_deterministic_without_credentials(monkeypatch):
    from jarvis.runtime.credential_free_probe import probe_providers

    monkeypatch.setattr("jarvis.core.secrets_store.get", lambda _k: None)
    report = probe_providers()
    assert report["llm"] == "absent"
    assert report["google"] == "absent"
    assert report["telegram"] in {"absent", "disabled"}


def test_probe_respects_telegram_master_disable(monkeypatch):
    from jarvis.runtime.credential_free_probe import probe_providers

    monkeypatch.setattr(
        "jarvis.integrations.telegram_control.master_enabled",
        lambda: False)
    report = probe_providers()
    assert report["telegram"] == "disabled"


def test_probe_marks_voice_skipped_when_no_voice(monkeypatch):
    from jarvis.runtime.credential_free_probe import probe_providers

    monkeypatch.setattr("jarvis.core.secrets_store.get", lambda _k: None)
    report = probe_providers(no_voice=True)
    assert report["voice"] == "skipped"


def test_probe_summary_is_metadata_only():
    from jarvis.runtime.credential_free_probe import probe_summary

    summary = probe_summary(no_voice=True)
    assert "telegram:" in summary and "voice: skipped" in summary
    assert ":" in summary.splitlines()[0]
