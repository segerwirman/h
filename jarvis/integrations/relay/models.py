"""Relay.app integration — payload models + normalization (Fase 5).

Relay.app delivers data to JARVIS through an HTTP step inside a Relay
workflow (the officially supported outbound mechanism); the payload shape is
whatever the user maps in that step. Normalization is therefore tolerant:
a few well-known fields are lifted when present, everything else stays in
``payload`` untouched.

Expected (recommended) JSON body from the Relay HTTP step:
    {
      "event_id":  "<unique id — enables dedup/replay protection>",
      "workflow":  "<workflow name>",
      "kind":      "event" | "workflow_result" | "source",
      "timestamp": "<ISO-8601 — enables replay window check>",
      "data":      { ...arbitrary mapped fields... }
    }
Only ``event_id`` is strongly recommended; everything else is optional.
"""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone


class PayloadError(ValueError):
    pass


MAX_PAYLOAD_BYTES = 256 * 1024          # reject absurd bodies early


@dataclass
class RelayEvent:
    event_id: str
    kind: str = "event"                  # event | workflow_result | source
    workflow: str = ""
    timestamp: float = 0.0               # epoch seconds (0 = not provided)
    data: dict = field(default_factory=dict)
    received_at: float = field(default_factory=time.time)

    def to_row(self) -> tuple:
        return (self.event_id, self.kind, self.workflow, self.timestamp,
                self.received_at, json.dumps(self.data, ensure_ascii=False))

    @classmethod
    def from_row(cls, row) -> "RelayEvent":
        return cls(event_id=row[0], kind=row[1], workflow=row[2],
                   timestamp=row[3], received_at=row[4],
                   data=json.loads(row[5] or "{}"))

    def summary(self, max_chars: int = 400) -> dict:
        """Bounded, credential-free view for the agent/UI."""
        body = json.dumps(self.data, ensure_ascii=False)
        return {
            "event_id": self.event_id,
            "kind": self.kind,
            "workflow": self.workflow,
            "received_at": datetime.fromtimestamp(
                self.received_at, tz=timezone.utc).isoformat(),
            "data": body[:max_chars] + ("…" if len(body) > max_chars else ""),
        }


def _parse_ts(value) -> float:
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return datetime.fromisoformat(
            str(value).replace("Z", "+00:00")).timestamp()
    except ValueError:
        return 0.0


def parse_event(body: bytes) -> RelayEvent:
    """Validate + normalize one webhook body. Raises PayloadError."""
    if len(body) > MAX_PAYLOAD_BYTES:
        raise PayloadError("payload too large")
    try:
        obj = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PayloadError("body is not valid JSON")
    if not isinstance(obj, dict):
        raise PayloadError("payload must be a JSON object")

    event_id = str(obj.get("event_id") or obj.get("id") or "").strip()
    if not event_id:
        # stable fallback id → duplicates of the identical body still dedup
        event_id = "sha-" + hashlib.sha256(body).hexdigest()[:24]

    kind = str(obj.get("kind") or "event").strip().lower()
    if kind not in ("event", "workflow_result", "source"):
        kind = "event"

    data = obj.get("data")
    if data is None:                     # tolerate flat payloads
        data = {k: v for k, v in obj.items()
                if k not in ("event_id", "id", "kind", "workflow", "timestamp")}
    if not isinstance(data, dict):
        raise PayloadError("'data' must be a JSON object")

    return RelayEvent(
        event_id=event_id,
        kind=kind,
        workflow=str(obj.get("workflow") or "")[:120],
        timestamp=_parse_ts(obj.get("timestamp")),
        data=data,
    )
