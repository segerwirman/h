"""Small bounded resource pool for reusable browser/client/helper resources."""
from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable
from threading import Lock


class ResourcePool:
    def __init__(self, *, max_entries: int = 8):
        self._max_entries = max(1, int(max_entries))
        self._items: OrderedDict[str, object] = OrderedDict()
        self._lock = Lock()

    def get_or_create(self, key: str, factory: Callable[[], object]):
        with self._lock:
            existing = self._items.get(key)
            if existing is not None:
                self._items.move_to_end(key)
                return existing
        created = factory()
        with self._lock:
            existing = self._items.get(key)
            if existing is not None:
                self._items.move_to_end(key)
                self._close(created)
                return existing
            self._items[key] = created
            while len(self._items) > self._max_entries:
                _, evicted = self._items.popitem(last=False)
                self._close(evicted)
            return created

    def clear(self) -> None:
        with self._lock:
            items = list(self._items.values())
            self._items.clear()
        for item in items:
            self._close(item)

    @staticmethod
    def _close(resource: object) -> None:
        closer = getattr(resource, "close", None)
        if callable(closer):
            try:
                closer()
            except Exception:
                pass
