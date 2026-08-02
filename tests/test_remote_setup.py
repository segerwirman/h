"""Fase 15S: secure remote setup — hanya Google OAuth Desktop Client JSON."""
from __future__ import annotations

import json
import time


def _valid_oauth_installed() -> str:
    return json.dumps({
        "installed": {
            "client_id": "abc.apps.googleusercontent.com",
            "project_id": "jarvis-demo",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "SECRET-VALUE-DO-NOT-LEAK",
            "redirect_uris": ["http://localhost"],
        }
    })


def test_validator_accepts_only_installed_oauth_desktop_client():
    from jarvis.agent.remote_setup import validate_setup_payload

    ok, kind, reason = validate_setup_payload("google_oauth_client", _valid_oauth_installed().encode())

    assert ok is True
    assert kind == "google_oauth_client"
    assert reason == ""


def test_validator_rejects_web_client_service_account_and_malformed():
    from jarvis.agent.remote_setup import validate_setup_payload

    web = json.dumps({"web": {"client_id": "x", "client_secret": "y"}}).encode()
    svc = json.dumps({"type": "service_account", "private_key": "-----BEGIN"}).encode()
    broken = b"{not-json"
    empty = b"{}"

    for payload in (web, svc, broken, empty):
        ok, _, reason = validate_setup_payload("google_oauth_client", payload)
        assert ok is False
        assert reason


def test_validator_rejects_empty_or_non_string_required_oauth_fields():
    from jarvis.agent.remote_setup import validate_setup_payload

    invalid_installed = (
        {"client_id": "", "client_secret": "secret", "token_uri": "https://token"},
        {"client_id": "client", "client_secret": "", "token_uri": "https://token"},
        {"client_id": "client", "client_secret": "secret", "token_uri": ""},
        {"client_id": 123, "client_secret": "secret", "token_uri": "https://token"},
    )
    for installed in invalid_installed:
        payload = json.dumps({"installed": installed}).encode()
        result = validate_setup_payload("google_oauth_client", payload)
        assert result == (False, "", "setup_payload_incomplete_oauth_client")


def test_validator_reason_never_contains_client_secret():
    from jarvis.agent.remote_setup import validate_setup_payload

    tampered = json.dumps({
        "installed": {"client_id": "a", "token_uri": "t", "client_secret": "TOP-SECRET"}
    }).encode()

    ok, _, reason = validate_setup_payload("google_oauth_client", tampered)

    assert "TOP-SECRET" not in reason


def test_unsupported_provider_and_type_rejected_before_staging():
    from jarvis.agent.remote_setup import validate_setup_payload

    for provider in ("arbitrary_secret", "shell_setup", "env_file"):
        ok, _, reason = validate_setup_payload(provider, _valid_oauth_installed().encode())
        assert ok is False
        assert reason


def test_attachment_gate_rejects_bad_extension_size_and_type():
    from jarvis.agent.remote_setup import attachment_allowed

    assert attachment_allowed("client_secret_x.json", 4096)[0] is True
    assert attachment_allowed("setup.exe", 4096)[0] is False
    assert attachment_allowed("setup.bat", 4096)[0] is False
    assert attachment_allowed("setup.ps1", 4096)[0] is False
    assert attachment_allowed("secret.env", 4096)[0] is False
    assert attachment_allowed("archive.zip", 4096)[0] is False
    assert attachment_allowed("client_secret.json", 3 * 1024 * 1024)[0] is False


def test_setup_request_is_metadata_only_without_secret_bytes():
    from jarvis.agent.remote_setup import SetupQueue

    queue = SetupQueue()
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:123",
        filename="client_secret.json", payload=_valid_oauth_installed().encode(),
    )

    assert request.provider == "google_oauth_client"
    assert request.requester == "telegram:123"
    assert request.status == "pending"
    assert request.hash_suffix and len(request.hash_suffix) <= 12
    dumped = repr(vars(request))
    assert "SECRET-VALUE-DO-NOT-LEAK" not in dumped
    assert "installed" not in dumped
    assert "payload" not in vars(request)


def test_remote_cannot_import_directly_only_local_approval(monkeypatch):
    from jarvis.agent import remote_setup

    queue = remote_setup.SetupQueue()
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:123",
        filename="client_secret.json", payload=_valid_oauth_installed().encode(),
    )

    assert not hasattr(remote_setup.SetupQueue, "remote_import")

    imported = {}
    monkeypatch.setattr(remote_setup, "_import_to_secret_store",
                        lambda provider, payload: imported.setdefault(provider, True) or True)

    assert queue.approve_local(request.id) is True
    assert imported == {"google_oauth_client": True}
    # staging removed after import
    assert queue.get(request.id) is None


def test_staging_expires_and_is_removed_without_import(monkeypatch):
    from jarvis.agent import remote_setup

    queue = remote_setup.SetupQueue(ttl_s=1.0)
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:123",
        filename="client_secret.json", payload=_valid_oauth_installed().encode(),
    )
    monkeypatch.setattr(time, "monotonic", lambda: request.created_at + 2.0)

    assert queue.get(request.id) is None
    assert queue.approve_local(request.id) is False


def test_import_is_one_shot_and_rejects_replay(monkeypatch):
    from jarvis.agent import remote_setup

    queue = remote_setup.SetupQueue()
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:123",
        filename="client_secret.json", payload=_valid_oauth_installed().encode(),
    )
    monkeypatch.setattr(remote_setup, "_import_to_secret_store", lambda *_: True)

    assert queue.approve_local(request.id) is True
    assert queue.approve_local(request.id) is False


def test_staging_payload_is_encrypted_at_rest(monkeypatch):
    from jarvis.agent import remote_setup

    stored = {}
    monkeypatch.setattr(remote_setup, "_encrypt_staging",
                        lambda raw: stored.setdefault("cipher", b"ENC:" + b"x" * len(raw)) or stored["cipher"])
    monkeypatch.setattr(remote_setup, "_decrypt_staging",
                        lambda cipher: _valid_oauth_installed().encode())

    queue = remote_setup.SetupQueue()
    queue.stage(
        provider="google_oauth_client", requester="telegram:123",
        filename="client_secret.json", payload=_valid_oauth_installed().encode(),
    )

    assert stored["cipher"].startswith(b"ENC:")
    assert b"SECRET-VALUE-DO-NOT-LEAK" not in stored["cipher"]
