"""Bounded process-local execution grants.

Grants contain identifiers and scope only. They are never persisted and never
carry passphrases, tool arguments, model continuations, or secret material.
"""
from __future__ import annotations

import math
import threading
import time
import uuid
from dataclasses import dataclass


PURPOSE_DIRECT_EXECUTION = "direct_execution"
PURPOSE_COMMUNICATION_OVERRIDE = "communication_override"
_ALLOWED_PURPOSES = frozenset({
    PURPOSE_DIRECT_EXECUTION,
    PURPOSE_COMMUNICATION_OVERRIDE,
})


@dataclass(frozen=True)
class Grant:
    id: str
    purpose: str
    task_id: str
    trace_id: str
    capability_ids: frozenset[str]
    expires_at: float
    uses_left: int
    generation: int


class ExecutionGrantManager:
    """Locked, bounded owner for short-lived process-local grants."""

    def __init__(self, *, now_fn=time.monotonic, max_grants: int = 256) -> None:
        self._now_fn = now_fn
        self._max_grants = max(1, int(max_grants))
        self._lock = threading.RLock()
        self._grants: dict[str, Grant] = {}

    def _prune_locked(self) -> None:
        now = self._now_fn()
        expired = [
            grant_id for grant_id, grant in self._grants.items()
            if grant.expires_at <= now or grant.uses_left <= 0
        ]
        for grant_id in expired:
            self._grants.pop(grant_id, None)

    def issue(
        self,
        *,
        purpose: str,
        task_id: str,
        trace_id: str,
        capability_ids,
        ttl_s: float,
        uses: int = 1,
        generation: int = 0,
    ) -> Grant:
        normalized_purpose = str(purpose or "").strip()
        normalized_task = str(task_id or "").strip()
        normalized_trace = str(trace_id or "").strip()
        normalized_caps = frozenset(
            str(item).strip() for item in (capability_ids or ())
            if str(item).strip()
        )
        ttl = float(ttl_s)
        use_count = int(uses)
        if normalized_purpose not in _ALLOWED_PURPOSES:
            raise ValueError("unsupported grant purpose")
        if not normalized_task or not normalized_trace or not normalized_caps:
            raise ValueError("grant requires task, trace, and capabilities")
        if not math.isfinite(ttl) or ttl <= 0 or use_count <= 0:
            raise ValueError("grant ttl and uses must be positive")
        grant = Grant(
            id=f"G-{uuid.uuid4().hex[:16]}",
            purpose=normalized_purpose,
            task_id=normalized_task,
            trace_id=normalized_trace,
            capability_ids=normalized_caps,
            expires_at=self._now_fn() + ttl,
            uses_left=use_count,
            generation=int(generation),
        )
        with self._lock:
            self._prune_locked()
            if len(self._grants) >= self._max_grants:
                raise RuntimeError("execution grant store full")
            self._grants[grant.id] = grant
        return grant

    def verify(
        self,
        grant_id: str,
        *,
        purpose: str,
        task_id: str,
        trace_id: str,
        capability_id: str,
        generation: int,
        consume: bool = True,
    ) -> bool:
        with self._lock:
            self._prune_locked()
            grant = self._grants.get(str(grant_id or ""))
            if grant is None:
                return False
            if (
                grant.purpose != str(purpose or "")
                or grant.task_id != str(task_id or "")
                or grant.trace_id != str(trace_id or "")
                or str(capability_id or "") not in grant.capability_ids
                or grant.generation != int(generation)
            ):
                return False
            if not consume:
                return True
            remaining = grant.uses_left - 1
            if remaining <= 0:
                self._grants.pop(grant.id, None)
            else:
                self._grants[grant.id] = Grant(
                    id=grant.id,
                    purpose=grant.purpose,
                    task_id=grant.task_id,
                    trace_id=grant.trace_id,
                    capability_ids=grant.capability_ids,
                    expires_at=grant.expires_at,
                    uses_left=remaining,
                    generation=grant.generation,
                )
            return True

    def revoke(self, grant_id: str) -> bool:
        with self._lock:
            return self._grants.pop(str(grant_id or ""), None) is not None

    def revoke_task(self, task_id: str) -> int:
        target = str(task_id or "")
        with self._lock:
            ids = [
                grant.id for grant in self._grants.values()
                if grant.task_id == target
            ]
            for grant_id in ids:
                self._grants.pop(grant_id, None)
            return len(ids)

    def revoke_generation(
        self, generation: int, *, purpose: str | None = None,
    ) -> int:
        generation_value = int(generation)
        purpose_value = str(purpose or "")
        with self._lock:
            ids = [
                grant.id for grant in self._grants.values()
                if grant.generation == generation_value
                and (not purpose_value or grant.purpose == purpose_value)
            ]
            for grant_id in ids:
                self._grants.pop(grant_id, None)
            return len(ids)

    def clear(self) -> None:
        with self._lock:
            self._grants.clear()

    def get(self, grant_id: str) -> Grant | None:
        with self._lock:
            self._prune_locked()
            return self._grants.get(str(grant_id or ""))

    def __len__(self) -> int:
        with self._lock:
            self._prune_locked()
            return len(self._grants)


MANAGER = ExecutionGrantManager()


__all__ = [
    "ExecutionGrantManager",
    "Grant",
    "MANAGER",
    "PURPOSE_COMMUNICATION_OVERRIDE",
    "PURPOSE_DIRECT_EXECUTION",
]
