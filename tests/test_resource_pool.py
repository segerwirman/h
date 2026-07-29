"""Framework maturity Phase 3 — pooled resources are reused and bounded."""
from __future__ import annotations


def test_resource_pool_reuses_factory_hasil_untuk_key_sama():
    from jarvis.runtime.resource_pool import ResourcePool

    pool = ResourcePool(max_entries=2)
    calls = []

    first = pool.get_or_create("browser:chrome", lambda: calls.append(1) or object())
    second = pool.get_or_create("browser:chrome", lambda: calls.append(2) or object())

    assert first is second
    assert calls == [1]


def test_resource_pool_evict_menutup_resource_terlama():
    from jarvis.runtime.resource_pool import ResourcePool

    closed = []

    class Resource:
        def __init__(self, name): self.name = name
        def close(self): closed.append(self.name)

    pool = ResourcePool(max_entries=1)
    pool.get_or_create("first", lambda: Resource("first"))
    pool.get_or_create("second", lambda: Resource("second"))

    assert closed == ["first"]
