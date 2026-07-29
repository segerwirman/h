"""Telegram ingress adapter boundary. Existing service remains transport owner."""
from __future__ import annotations

from collections.abc import Callable

from jarvis.gateway.base import InboundMessage
from jarvis.gateway.registry import GatewayRegistry


class TelegramGateway:
    """Deduplicate inbound Telegram events before forwarding to Jarvis."""

    def __init__(self, on_message: Callable[[InboundMessage], None],
                 registry: GatewayRegistry | None = None) -> None:
        self._on_message = on_message
        self._registry = registry or GatewayRegistry()
        self.toolsets = self._registry.default_toolsets("telegram")

    def receive(self, message_id: str, conversation_id: str,
                sender_id: str, text: str) -> bool:
        if not self._registry.accept_inbound("telegram", message_id, conversation_id):
            return False
        self._on_message(InboundMessage(
            message_id=str(message_id), platform="telegram",
            conversation_id=str(conversation_id), sender_id=str(sender_id), text=str(text),
        ))
        return True
