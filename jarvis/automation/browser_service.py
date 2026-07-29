"""Warm browser resource ownership keyed by named Jarvis browser profile."""
from __future__ import annotations

from collections.abc import Callable

from jarvis.runtime.resource_pool import ResourcePool


class BrowserService:
    def __init__(self, *, max_profiles: int = 3):
        self._pool = ResourcePool(max_entries=max_profiles)

    def get_or_create(self, profile: str, factory: Callable[[], object]):
        return self._pool.get_or_create(f"browser:{str(profile).strip().lower()}", factory)

    def shutdown(self) -> None:
        self._pool.clear()


BROWSERS = BrowserService()
