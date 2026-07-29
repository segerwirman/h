"""Bounded, secret-safe identity propagated through Jarvis execution seams."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from typing import Mapping


def _actor_hash(actor_id: str) -> str:
    return hashlib.sha256(actor_id.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ExecutionContext:
    source: str
    actor_id: str
    session_id: str
    surface: str
    toolsets: frozenset[str]
    trace_id: str
    secrets: Mapping[str, str] = field(default_factory=dict, repr=False,
                                       compare=False)

    @classmethod
    def create(cls, *, source: str, actor_id: str, session_id: str,
               surface: str, toolsets, secrets: Mapping[str, str] | None = None):
        return cls(source=str(source), actor_id=str(actor_id),
                   session_id=str(session_id), surface=str(surface),
                   toolsets=frozenset(str(item) for item in toolsets),
                   trace_id=secrets_module.token_hex(12),
                   secrets=dict(secrets or {}))

    def for_child(self, *, toolsets=None) -> "ExecutionContext":
        return ExecutionContext.create(
            source=self.source, actor_id=self.actor_id,
            session_id=self.session_id, surface=self.surface,
            toolsets=self.toolsets if toolsets is None else toolsets,
        )

    def safe_metadata(self) -> dict:
        return {
            "source": self.source,
            "actor_id": _actor_hash(self.actor_id),
            "session_id": self.session_id,
            "surface": self.surface,
            "toolsets": sorted(self.toolsets),
            "trace_id": self.trace_id,
        }


secrets_module = secrets
