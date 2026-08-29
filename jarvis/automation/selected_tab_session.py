"""Process-local identity lease for one selected everyday-Chrome tab."""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

_MAX_TTL_S = 3600.0


@dataclass(frozen=True)
class SelectedTabSessionSnapshot:
    active: bool = False
    session_id: str = ""
    task_id: str = ""
    target_id: str = ""
    target_generation: int = 0
    expires_at: float = 0.0


class SelectedTabSessionOwner:
    """Own an exact selected-target binding without native desktop authority."""

    def __init__(self, *, clock=time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.RLock()
        self._snapshot = SelectedTabSessionSnapshot()

    def snapshot(self) -> SelectedTabSessionSnapshot:
        with self._lock:
            return self._snapshot

    def activate(
        self,
        session_id: str,
        task_id: str,
        target_id: str,
        *,
        target_generation: int,
        ttl_s: float,
    ) -> bool:
        session = str(session_id or "").strip()
        task = str(task_id or "").strip()
        target = str(target_id or "").strip()
        try:
            ttl = float(ttl_s)
        except (TypeError, ValueError):
            return False
        if (
            not session
            or not task
            or not target
            or type(target_generation) is not int
            or target_generation <= 0
            or not math.isfinite(ttl)
            or ttl <= 0
            or ttl > _MAX_TTL_S
        ):
            return False
        try:
            now = float(self._clock())
            expires_at = now + ttl
        except Exception:
            return False
        with self._lock:
            current = self._snapshot
            if current.active:
                return False
            self._snapshot = SelectedTabSessionSnapshot(
                active=True,
                session_id=session,
                task_id=task,
                target_id=target,
                target_generation=target_generation,
                expires_at=expires_at,
            )
        return True

    def binding_error(
        self,
        *,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
    ) -> str:
        with self._lock:
            current = self._snapshot
            if not current.active:
                return "selected_tab_lease_not_active"
            try:
                expired = float(self._clock()) >= current.expires_at
            except Exception:
                expired = True
            if expired:
                self._snapshot = SelectedTabSessionSnapshot()
                return "selected_tab_lease_expired"
            if current.session_id != str(session_id or "").strip():
                return "selected_tab_lease_session_mismatch"
            if current.task_id != str(task_id or "").strip():
                return "selected_tab_lease_task_mismatch"
            if current.target_id != str(target_id or "").strip():
                return "selected_tab_lease_target_mismatch"
            if current.target_generation != target_generation:
                return "selected_tab_lease_generation_mismatch"
        return ""

    def release_session(
        self,
        session_id: str,
        reason: str = "task_terminal",
    ) -> bool:
        del reason
        session = str(session_id or "").strip()
        return self._clear_if(lambda current: current.session_id == session)

    def release_task(
        self,
        task_id: str,
        reason: str = "task_terminal",
    ) -> bool:
        del reason
        task = str(task_id or "").strip()
        return self._clear_if(lambda current: current.task_id == task)

    def revoke(self, reason: str = "revoked") -> bool:
        del reason
        return self._clear_if(lambda _current: True)

    def _clear_if(self, matches) -> bool:
        with self._lock:
            current = self._snapshot
            if not current.active or not matches(current):
                return False
            self._snapshot = SelectedTabSessionSnapshot()
        return True


SELECTED_TABS = SelectedTabSessionOwner()


__all__ = [
    "SELECTED_TABS",
    "SelectedTabSessionOwner",
    "SelectedTabSessionSnapshot",
]
