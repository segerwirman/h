"""Fase 16A: import OAuth client Fase 15S menyambung ke google_auth."""
from __future__ import annotations

import json


def _installed_json() -> bytes:
    return json.dumps({
        "installed": {
            "client_id": "phase16a.apps.googleusercontent.com",
            "project_id": "jarvis-16a",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "SECRET-16A-VALUE",
            "redirect_uris": ["http://localhost"],
        }
    }).encode()


def test_import_parses_installed_and_saves_client_to_google_auth(monkeypatch):
    from jarvis.agent import remote_setup
    from jarvis.integrations import google_auth

    saved = {}
    monkeypatch.setattr(google_auth, "save_client",
                        lambda cid, secret: saved.update(client_id=cid, client_secret=secret) or True)

    ok = remote_setup._import_to_secret_store("google_oauth_client", _installed_json())

    assert ok is True
    assert saved == {
        "client_id": "phase16a.apps.googleusercontent.com",
        "client_secret": "SECRET-16A-VALUE",
    }


def test_import_rejects_json_without_installed_client(monkeypatch):
    from jarvis.agent import remote_setup
    from jarvis.integrations import google_auth

    monkeypatch.setattr(google_auth, "save_client", lambda *_: True)
    bad = json.dumps({"web": {"client_id": "x", "client_secret": "y"}}).encode()

    assert remote_setup._import_to_secret_store("google_oauth_client", bad) is False


def test_status_never_leaks_client_secret_or_token(monkeypatch):
    from jarvis.integrations import google_auth

    monkeypatch.setattr(google_auth.secrets_store, "get",
                        lambda key: "SECRET-XYZ" if "secret" in key else "id" if "client_id" in key else "")
    monkeypatch.setattr(google_auth, "provider_enabled", lambda: True)

    status = google_auth.status()
    blob = json.dumps(status)

    assert "SECRET-XYZ" not in blob
    assert "client_secret" not in blob
    assert "token" not in blob or "token_uri" not in blob
    assert set(status.keys()) <= {"connected", "client_configured", "backend", "scopes", "apis"}


def test_start_login_requires_client_and_enabled_api(monkeypatch):
    from jarvis.integrations import google_auth

    monkeypatch.setattr(google_auth.secrets_store, "available", lambda: True)
    monkeypatch.setattr(google_auth, "client_configured", lambda: False)

    try:
        google_auth.start_login(open_browser=False)
    except google_auth.GoogleAuthError as exc:
        assert "client" in str(exc).lower()
    else:
        raise AssertionError("start_login must fail without client credential")


def test_requested_scopes_read_write_separation(monkeypatch):
    from jarvis.integrations import google_auth

    enabled = {"calendar": True, "gmail": True}
    writes = {"calendar": True, "gmail": False}
    monkeypatch.setattr(google_auth.config, "get", lambda key, default=None: (
        True if key == "providers.google.enabled" else
        enabled.get(key.split(".")[-2], False) if key.endswith(".enabled") else
        writes.get(key.split(".")[-2], False) if key.endswith(".write") else default))

    scopes = google_auth.requested_scopes()

    assert "https://www.googleapis.com/auth/calendar.events" in scopes
    assert "https://www.googleapis.com/auth/gmail.readonly" in scopes
    assert "https://www.googleapis.com/auth/gmail.send" not in scopes
