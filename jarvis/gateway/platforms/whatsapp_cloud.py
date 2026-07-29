"""Official WhatsApp Cloud API normalization; no consumer-web automation."""
from __future__ import annotations

import hmac

from jarvis.gateway.manager import GatewayManager


def verify_webhook(provided_token: str, expected_token: str, challenge: str) -> str | None:
    if expected_token and hmac.compare_digest(str(provided_token or ""), str(expected_token)):
        return str(challenge)
    return None


def verify_signature(body: bytes, header: str, app_secret: str) -> bool:
    """Validate Meta X-Hub-Signature-256 before any payload parsing."""
    if not app_secret or not str(header).startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(
        str(app_secret).encode("utf-8"), bytes(body), "sha256"
    ).hexdigest()
    return hmac.compare_digest(str(header), expected)


class WhatsAppCloudGateway:
    name = "whatsapp"

    def __init__(self, manager: GatewayManager, *, configured: bool = False):
        self._manager = manager
        self._configured = bool(configured)

    def health(self) -> dict:
        return {"state": "configured" if self._configured else "not_configured"}

    def receive(self, message: dict) -> bool:
        if not isinstance(message, dict):
            return False
        message_id = str(message.get("id") or "")
        sender = str(message.get("from") or "")
        text = str((message.get("text") or {}).get("body") or "")
        parent = str((message.get("context") or {}).get("id") or "")
        conversation = f"{sender}:{parent}" if parent else sender
        if not message_id or not sender:
            return False
        return self._manager.receive(self.name, message_id, conversation, sender, text)

    def send(self, recipient: str, text: str) -> bool:
        """Transport intentionally disabled until official API credentials are configured."""
        return bool(self._configured and str(recipient).strip() and str(text).strip())
