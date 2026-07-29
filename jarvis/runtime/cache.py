"""Thread-safe bounded TTL cache for local helper warm paths."""
from __future__ import annotations

import time
from collections import OrderedDict
from collections.abc import Callable
from threading import Lock


def normalized_key(*parts: str) -> str:
    return ":".join(" ".join(str(part).lower().split()) for part in parts)


class TTLCache:
    def __init__(self, *, max_entries: int = 128, clock: Callable[[], float] = time.monotonic):
        self._max_entries = max(1, int(max_entries))
        self._clock = clock
        self._items: OrderedDict[str, tuple[float, object]] = OrderedDict()
        self._lock = Lock()

    def get_or_load(self, key: str, ttl_s: float, loader: Callable[[], object]):
        now = self._clock()
        with self._lock:
            cached = self._items.get(key)
            if cached and now < cached[0]:
                self._items.move_to_end(key)
                return cached[1]
        value = loader()
        with self._lock:
            self._items[key] = (now + max(0.0, float(ttl_s)), value)
            self._items.move_to_end(key)
            while len(self._items) > self._max_entries:
                self._items.popitem(last=False)
        return value

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
