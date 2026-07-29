"""Manager-owned gateway lifecycle, pairing gate, idempotent ingress."""
from __future__ import annotations

import hashlib
from collections import deque
from collections.abc import Callable

from jarvis.gateway.authz import GatewayAuthz
from jarvis.gateway.base import InboundMessage
from jarvis.gateway.registry import GatewayRegistry


class GatewayManager:
    def __init__(self, *, on_message: Callable[[InboundMessage], None],
                 registry: GatewayRegistry | None = None,
                 authz: GatewayAuthz | None = None):
        self._on_message = on_message
        self._registry = registry or GatewayRegistry()
        self._authz = authz or GatewayAuthz()
        self._adapters: dict[str, object] = {}
        self._events: deque[dict[str, str]] = deque(maxlen=256)

    def _record(self, action: str, platform: str, *, trace: str = "") -> None:
        """Keep bounded rollout evidence without retaining remote identities or payloads."""
        event = {"action": str(action)[:64], "platform": str(platform)[:32]}
        if trace:
            event["trace_hash"] = hashlib.sha256(trace.encode("utf-8")).hexdigest()[:16]
        self._events.append(event)

    def recent_events(self, limit: int = 50) -> list[dict[str, str]]:
        """Return bounded in-memory safe lifecycle/ingress evidence."""
        return [dict(event) for event in list(self._events)[-max(1, min(int(limit), 256)):]]

    def register(self, adapter: object) -> bool:
        name = str(getattr(adapter, "name", "")).strip().lower()
        if not name or name in self._adapters:
            return False
        self._adapters[name] = adapter
        return True

    def start(self, platform: str) -> bool:
        name = str(platform).strip().lower()
        adapter = self._adapters.get(name)
        started = bool(adapter and getattr(adapter, "start", lambda: False)())
        if started:
            self._record("lifecycle.started", name)
        return started

    def stop(self, platform: str) -> None:
        name = str(platform).strip().lower()
        adapter = self._adapters.get(name)
        if adapter:
            getattr(adapter, "stop", lambda: None)()
            self._record("lifecycle.stopped", name)

    def pair(self, platform: str, actor_id: str, *,
             paired_by: str = "local-admin") -> bool:
        return self._authz.pair(platform, actor_id, paired_by=paired_by)

    def allowed(self, platform: str, actor_id: str) -> bool:
        return self._authz.allowed(platform, actor_id)

    def paired_count(self, platform: str) -> int:
        return self._authz.paired_count(platform)

    def registered(self, platform: str) -> bool:
        return str(platform).strip().lower() in self._adapters

    def receive(self, platform: str, message_id: str, conversation_id: str,
                actor_id: str, text: str) -> bool:
        name = str(platform).strip().lower()
        if name not in self._adapters or not self.allowed(name, actor_id):
            return False
        trace = "\x1f".join((name, str(message_id), str(conversation_id), str(actor_id)))
        if not self._registry.accept_inbound(name, message_id, conversation_id):
            self._record("ingress.deduplicated", name, trace=trace)
            return False
        self._on_message(InboundMessage(
            message_id=str(message_id), platform=name,
            conversation_id=str(conversation_id), sender_id=str(actor_id), text=str(text),
        ))
        self._record("ingress.accepted", name, trace=trace)
        return True

    def health(self) -> dict[str, dict]:
        out = {}
        for name, adapter in self._adapters.items():
            try:
                state = getattr(adapter, "health", lambda: {"state": "unknown"})()
                out[name] = {"state": str((state or {}).get("state", "unknown"))[:32]}
            except Exception:  # noqa: BLE001
                out[name] = {"state": "error"}
        return out
