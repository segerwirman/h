"""Transport-neutral gateway contracts; payloads exclude transport secrets."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class InboundMessage:
    message_id: str
    platform: str
    conversation_id: str
    sender_id: str
    text: str = ""
    reply_target: str = ""

    @property
    def idempotency_key(self) -> str:
        return ":".join((self.platform, self.conversation_id, self.message_id))

    def execution_context(self):
        """Build a bounded remote context; no transport payload or secret leaks."""
        from jarvis.agent.execution_context import ExecutionContext
        return ExecutionContext.create(
            source=self.platform, actor_id=self.sender_id,
            session_id=self.conversation_id, surface="remote",
            # Paired remote actors can request bounded research or one image
            # generation. Desktop, shell, and file-write authority remain local.
            toolsets={"messaging", "agent", "web", "image", "skills", "memory", "gws_read"},
        )


@dataclass(frozen=True)
class DeliveryResult:
    ok: bool
    platform: str
    message_id: str = ""
    attempts: int = 0
    error_type: str = ""
