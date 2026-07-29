"""Framework maturity Phase 12 — official WhatsApp Cloud webhook boundary."""
from __future__ import annotations


def test_whatsapp_verify_webhook_challenge_hanya_bila_token_cocok():
    from jarvis.gateway.platforms.whatsapp_cloud import verify_webhook

    assert verify_webhook("expected", "expected", "challenge") == "challenge"
    assert verify_webhook("wrong", "expected", "challenge") is None


def test_whatsapp_signature_sha256_fail_closed():
    import hashlib
    import hmac
    from jarvis.gateway.platforms.whatsapp_cloud import verify_signature

    body = b'{"entry":[]}'
    secret = "app-secret"
    signature = "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

    assert verify_signature(body, signature, secret) is True
    assert verify_signature(body, "sha256=wrong", secret) is False
    assert verify_signature(body, signature, "") is False


def test_whatsapp_normalize_dedup_dan_tidak_kirim_tanpa_config():
    from jarvis.gateway.platforms.whatsapp_cloud import WhatsAppCloudGateway

    from jarvis.gateway.manager import GatewayManager

    received = []
    manager = GatewayManager(on_message=received.append)
    gateway = WhatsAppCloudGateway(manager)
    assert manager.register(gateway)
    assert manager.pair("whatsapp", "6281")
    payload = {
        "id": "wamid-1",
        "from": "6281",
        "text": {"body": "halo"},
        "context": {"id": "thread-1"},
    }

    assert gateway.receive(payload) is True
    assert gateway.receive(payload) is False
    assert received[0].platform == "whatsapp"
    assert received[0].conversation_id == "6281:thread-1"
    assert gateway.health() == {"state": "not_configured"}
    assert gateway.send("6281", "halo") is False
