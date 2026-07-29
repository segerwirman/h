"""Payload-free latency counters for helper performance diagnostics."""
from __future__ import annotations

from threading import Lock


class LatencyMetrics:
    def __init__(self):
        self._items: dict[str, list[float]] = {}
        self._lock = Lock()

    def record(self, name: str, seconds: float, **_ignored) -> None:
        with self._lock:
            values = self._items.setdefault(str(name), [])
            values.append(round(max(0.0, float(seconds)) * 1000, 3))
            del values[:-128]

    def summary(self, name: str) -> dict:
        with self._lock:
            values = self._items.get(str(name), [])
            return {"count": len(values), "last_ms": values[-1] if values else 0.0}


METRICS = LatencyMetrics()
