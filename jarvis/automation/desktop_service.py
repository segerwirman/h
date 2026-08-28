"""Exclusive lease for mutable desktop automation actions."""
from __future__ import annotations

from collections.abc import Callable
from threading import Lock


class DesktopService:
    def __init__(self):
        self._owner = ""
        self._authority_owner = ""
        self._authority_borrows = 0
        self._retiring_owner = ""
        self._retiring_borrows = 0
        self._lock = Lock()

    def claim(self, session_id: str) -> bool:
        owner = str(session_id or "")
        if not owner:
            return False
        with self._lock:
            if self._owner and self._owner != owner:
                return False
            self._owner = owner
            if self._authority_owner == owner:
                self._authority_borrows += 1
            return True

    def release(self, session_id: str) -> None:
        owner = str(session_id or "")
        with self._lock:
            if self._authority_owner == owner and self._authority_borrows > 0:
                self._authority_borrows -= 1
                return
            if self._retiring_owner == owner and self._retiring_borrows > 0:
                self._retiring_borrows -= 1
                if self._retiring_borrows == 0:
                    self._retiring_owner = ""
                return
            if self._owner == owner and self._authority_owner != owner:
                self._owner = ""

    def claim_authority(self, session_id: str) -> bool:
        """Pin the lease for one bounded higher-level authority session."""
        owner = str(session_id or "")
        if not owner:
            return False
        with self._lock:
            if self._owner and self._owner != owner:
                return False
            if self._authority_owner:
                return self._authority_owner == owner
            if self._retiring_owner == owner and self._retiring_borrows > 0:
                return False
            self._owner = owner
            self._authority_owner = owner
            self._authority_borrows = 0
            return True

    def release_authority(self, session_id: str) -> None:
        """Retire only the matching pinned authority without blocking."""
        owner = str(session_id or "")
        with self._lock:
            if self._authority_owner != owner:
                return
            self._authority_owner = ""
            self._retiring_owner = owner if self._authority_borrows else ""
            self._retiring_borrows = self._authority_borrows
            self._authority_borrows = 0
            if self._owner == owner:
                self._owner = ""

    def run(self, session_id: str, operation: Callable[[], object]):
        if not self.claim(session_id):
            return None
        try:
            return operation()
        except Exception:
            # Success retains the owner's lease for the caller's explicit
            # lifecycle; an exception must never strand that owner forever.
            self.release(session_id)
            raise


DESKTOP = DesktopService()
