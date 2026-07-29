"""Credential-free Discord normalization; live SDK starts only after configuration."""
from __future__ import annotations

from jarvis.gateway.manager import GatewayManager


class DiscordGateway:
    name = "discord"

    def __init__(self, manager: GatewayManager, *, configured: bool = False):
        self._manager = manager
        self._configured = bool(configured)
        self._running = False

    def start(self) -> bool:
        if not self._configured:
            return False
        self._running = True
        return True

    def stop(self) -> None:
        self._running = False

    def health(self) -> dict:
        if not self._configured:
            return {"state": "not_configured"}
        return {"state": "connected" if self._running else "stopped"}

    def receive(self, message_id: str, conversation_id: str, sender_id: str,
                text: str, *, thread_id: str = "") -> bool:
        conversation = str(conversation_id)
        if thread_id:
            conversation = f"{conversation}:{str(thread_id)}"
        return self._manager.receive(
            self.name, str(message_id), conversation, str(sender_id), str(text)
        )
