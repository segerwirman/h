"""Bounded idempotency and least-privilege defaults for platform ingress."""
from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock

from jarvis.agent import toolsets
from jarvis.gateway.receipts import GatewayReceipts


class GatewayRegistry:
    def __init__(self, seen_limit: int = 2048, *, receipt_path: Path | None = None) -> None:
        self._seen_limit = max(1, int(seen_limit))
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._lock = Lock()
        # Durable receipts are injected by the application-owned runtime. Keep
        # isolated/unit adapters process-local unless a receipt path is explicit.
        self._receipts = GatewayReceipts(receipt_path) if receipt_path else None

    def accept_inbound(self, platform: str, message_id: str, conversation_id: str) -> bool:
        values = tuple(str(value or "").strip()[:256]
                       for value in (platform, conversation_id, message_id))
        key = ":".join(values)
        if not all(values):
            return False
        with self._lock:
            if key in self._seen:
                self._seen.move_to_end(key)
                return False
            if self._receipts is not None and not self._receipts.accept(
                    values[0], values[2], values[1]):
                return False
            self._seen[key] = None
            while len(self._seen) > self._seen_limit:
                self._seen.popitem(last=False)
        return True

    def receipt_stats(self) -> dict[str, int]:
        return self._receipts.stats() if self._receipts is not None else {"count": 0, "max_rows": 0}

    @staticmethod
    def default_toolsets(platform: str) -> frozenset[str]:
        name = str(platform or "").strip().lower()
        if name == "telegram":
            return toolsets.allowed_for_surface("telegram")
        return frozenset()
