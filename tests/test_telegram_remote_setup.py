"""Fase 15S: Telegram ingress hanya request/upload; approval tetap desktop lokal."""
from __future__ import annotations

import json


def _oauth_json() -> bytes:
    return json.dumps({
        "installed": {
            "client_id": "abc.apps.googleusercontent.com",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "SECRET-NEVER-ECHO",
        }
    }).encode()


def test_ingress_stages_only_for_paired_actor_and_returns_safe_status():
    from jarvis.agent import remote_setup_ingress
    from jarvis.agent.remote_setup import SetupQueue

    queue = SetupQueue()
    status = remote_setup_ingress.receive_setup_upload(
        queue, provider="google_oauth_client", requester="telegram:123",
        paired=True, filename="client_secret.json", payload=_oauth_json(),
    )

    assert status["accepted"] is True
    assert status["status"] == "awaiting_desktop_approval"
    assert "SECRET-NEVER-ECHO" not in json.dumps(status)
    assert "installed" not in json.dumps(status)
    assert "payload" not in status


def test_ingress_rejects_unpaired_actor_without_staging():
    from jarvis.agent import remote_setup_ingress
    from jarvis.agent.remote_setup import SetupQueue

    queue = SetupQueue()
    status = remote_setup_ingress.receive_setup_upload(
        queue, provider="google_oauth_client", requester="telegram:999",
        paired=False, filename="client_secret.json", payload=_oauth_json(),
    )

    assert status["accepted"] is False
    assert status["status"] == "rejected"
    assert queue.get(status.get("request_id", "")) is None


def test_ingress_rejects_malformed_context_and_payload_types_with_fixed_reason():
    from jarvis.agent import remote_setup_ingress
    from jarvis.agent.remote_setup import SetupQueue

    cases = (
        {"requester": "telegram:1", "paired": "false", "filename": "client.json", "payload": _oauth_json()},
        {"requester": "", "paired": True, "filename": "client.json", "payload": _oauth_json()},
        {"requester": "telegram:1", "paired": True, "filename": "client.json", "payload": "not-bytes"},
    )
    for values in cases:
        result = remote_setup_ingress.receive_setup_upload(
            SetupQueue(), provider="google_oauth_client", **values,
        )
        assert result == {
            "accepted": False, "status": "rejected", "reason": "setup_context_rejected",
        }


def test_ingress_rejects_bad_type_and_returns_reason_code_only():
    from jarvis.agent import remote_setup_ingress
    from jarvis.agent.remote_setup import SetupQueue

    queue = SetupQueue()
    status = remote_setup_ingress.receive_setup_upload(
        queue, provider="google_oauth_client", requester="telegram:123",
        paired=True, filename="payload.exe", payload=_oauth_json(),
    )

    assert status["accepted"] is False
    assert status["status"] == "rejected"
    assert status["reason"] == "setup_attachment_type_rejected"


def test_ingress_never_exposes_secret_in_reason_for_bad_payload():
    from jarvis.agent import remote_setup_ingress
    from jarvis.agent.remote_setup import SetupQueue

    queue = SetupQueue()
    web = json.dumps({"web": {"client_secret": "LEAK-ME"}}).encode()
    status = remote_setup_ingress.receive_setup_upload(
        queue, provider="google_oauth_client", requester="telegram:123",
        paired=True, filename="client_secret.json", payload=web,
    )

    assert status["accepted"] is False
    assert "LEAK-ME" not in json.dumps(status)
    assert status["reason"] == "setup_payload_not_desktop_client"
