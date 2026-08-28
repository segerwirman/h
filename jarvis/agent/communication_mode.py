"""Process-local owner for the WhatsApp communication execution lock."""
from __future__ import annotations

import math
import threading


ESCAPE_CAPABILITY_IDS = frozenset({
    "whatsapp_status",
    "whatsapp_hangup",
    "task_cancel",
    "emergency_stop",
    "communication_auth",
})


class CommunicationMode:
    """Own one active communication generation and its grant retirement."""

    def __init__(self, *, grant_manager=None) -> None:
        self._lock = threading.RLock()
        self._active = False
        self._generation = 0
        self._grant_manager = grant_manager

    def active(self) -> bool:
        with self._lock:
            return self._active

    def generation(self) -> int:
        with self._lock:
            return self._generation

    def enter(self) -> int:
        """Engage the lock once; repeated enter calls keep one generation."""
        with self._lock:
            if not self._active:
                self._generation += 1
                self._active = True
            return self._generation

    def exit(self) -> bool:
        """Retire the current generation and revoke its override grants."""
        with self._lock:
            generation = self._generation
            was_active = self._active
            self._active = False
        if generation:
            self._grants().revoke_generation(
                generation,
                purpose=self._communication_purpose(),
            )
        return was_active

    @staticmethod
    def is_escape(capability_id: str) -> bool:
        return str(capability_id or "") in ESCAPE_CAPABILITY_IDS

    def issue_override(
        self,
        *,
        task_id: str,
        trace_id: str,
        capability_ids,
        ttl_s: float,
        uses: int = 1,
    ):
        """Issue one override bound to the currently active generation."""
        normalized_task = str(task_id or "").strip()
        normalized_trace = str(trace_id or "").strip()
        normalized_caps = frozenset(
            str(item).strip() for item in (capability_ids or ())
            if str(item).strip()
        )
        ttl = float(ttl_s)
        use_count = int(uses)
        if (
            not normalized_task
            or not normalized_trace
            or not normalized_caps
            or not math.isfinite(ttl)
            or ttl <= 0
            or use_count <= 0
        ):
            raise ValueError("override grant scope is invalid")
        with self._lock:
            if not self._active:
                raise RuntimeError("communication mode is not active")
            generation = self._generation
            grant = self._grants().issue(
                purpose=self._communication_purpose(),
                task_id=normalized_task,
                trace_id=normalized_trace,
                capability_ids=normalized_caps,
                ttl_s=ttl,
                uses=use_count,
                generation=generation,
            )
            if not self._active or self._generation != generation:
                self._grants().revoke(grant.id)
                raise RuntimeError("communication generation changed")
            return grant

    def revoke_grant(self, grant_id: str) -> bool:
        return self._grants().revoke(grant_id)

    def _grants(self):
        if self._grant_manager is not None:
            return self._grant_manager
        from jarvis.agent.execution_grants import MANAGER
        return MANAGER

    @staticmethod
    def _communication_purpose() -> str:
        from jarvis.agent.execution_grants import PURPOSE_COMMUNICATION_OVERRIDE
        return PURPOSE_COMMUNICATION_OVERRIDE


MODE = CommunicationMode()


def enter() -> int:
    return MODE.enter()


def exit() -> bool:
    return MODE.exit()


def active() -> bool:
    return MODE.active()


def generation() -> int:
    return MODE.generation()


def is_escape(capability_id: str) -> bool:
    return MODE.is_escape(capability_id)


def issue_override(
    *, task_id: str, trace_id: str, capability_ids, ttl_s: float, uses: int = 1,
):
    return MODE.issue_override(
        task_id=task_id,
        trace_id=trace_id,
        capability_ids=capability_ids,
        ttl_s=ttl_s,
        uses=uses,
    )


__all__ = [
    "CommunicationMode",
    "ESCAPE_CAPABILITY_IDS",
    "MODE",
    "active",
    "enter",
    "exit",
    "generation",
    "is_escape",
    "issue_override",
]
