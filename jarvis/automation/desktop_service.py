"""Exclusive lease for mutable desktop automation actions."""
from __future__ import annotations

from collections.abc import Callable
from threading import Lock


class DesktopService:
    def __init__(self):
        self._owner = ""
        self._lock = Lock()

    def claim(self, session_id: str) -> bool:
        owner = str(session_id or "")
        if not owner:
            return False
        with self._lock:
            if self._owner and self._owner != owner:
                return False
            self._owner = owner
            return True

    def release(self, session_id: str) -> None:
        with self._lock:
            if self._owner == str(session_id or ""):
                self._owner = ""

    def run(self, session_id: str, operation: Callable[[], object]):
        if not self.claim(session_id):
            return None
        return operation()


DESKTOP = DesktopService()
