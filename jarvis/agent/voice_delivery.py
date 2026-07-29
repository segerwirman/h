"""Transport-agnostic state guard for interruptible spoken delivery."""
from __future__ import annotations

import threading
import uuid
from collections.abc import Callable


class VoiceDeliveryController:
    """Reject terminal callbacks for speech cancelled by barge-in/ESC."""

    def __init__(self, publish: Callable[..., None]) -> None:
        self._publish = publish
        self._active: str | None = None
        self._lock = threading.Lock()

    def start(self, _speech: str) -> str:
        token = uuid.uuid4().hex[:12]
        with self._lock:
            self._active = token
        self._publish("conversation.delivery_started", delivery_id=token)
        return token

    def interrupt(self, token: str) -> bool:
        with self._lock:
            if token != self._active:
                return False
            self._active = None
        self._publish("conversation.delivery_interrupted", delivery_id=token)
        return True

    def finish(self, token: str) -> bool:
        with self._lock:
            if token != self._active:
                return False
            self._active = None
        self._publish("conversation.delivery_finished", delivery_id=token)
        return True
