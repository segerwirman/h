"""Fase 29 — sesi model hangat.

Diukur di proses baru, sebelum model ditanya apa pun:

| tahap | dingin |
|---|---|
| `import llm_client` | 235 ms |
| `client()` | 248 ms |
| **SDK dibangun (import + ctor)** | **1577 ms** |
| `all_tools()` (103 tool) | 319 ms |
| `schemas()` (94 schema) | 49 ms |
| **total** | **2427 ms** |

Itu yang Takeda tunggu pada perintah pertama setelah boot, dan seluruhnya
terjadi sebelum satu byte pun dikirim ke model. Dua pekerjaan di sini:
memanaskannya di latar belakang saat boot, dan berhenti menghitung ulang
bagian yang tidak pernah berubah.

**Yang sengaja TIDAK di-cache:** apa pun yang bergantung pada `context` atau
policy. `exposed_tool_names` menjalankan `policy.decide` per descriptor, dan
cache basi di sana berarti izin yang sudah dicabut masih berlaku. Yang
di-cache hanya fungsi murni dari tool itu sendiri.
"""
from __future__ import annotations

import threading
import time

import pytest

from jarvis.agent import registry


# ── schema tidak dihitung ulang tanpa alasan ──────────────────────────────

def test_schema_content_is_unchanged_by_caching():
    first = registry.schemas()
    second = registry.schemas()

    assert first == second
    assert first, "registry kosong — ukurannya tidak berarti"


def test_a_tool_schema_is_built_once_per_registry_generation(monkeypatch):
    builds: list[str] = []

    tools = registry.all_tools()
    name = sorted(tools)[0]
    tool = tools[name]
    original = type(tool).json_schema

    def counting(self):
        builds.append(self.name)
        return original(self)

    monkeypatch.setattr(type(tool), "json_schema", counting)
    registry.invalidate_schema_cache()

    registry.schemas()
    registry.schemas()
    registry.schemas()

    assert builds.count(name) == 1, f"json_schema dipanggil {builds.count(name)}x"


def test_rediscovery_invalidates_the_cached_schemas(monkeypatch):
    """Cache yang tidak pernah basi adalah cache yang menyembunyikan bug."""
    before = registry.schemas()
    generation_before = registry.generation()

    registry.all_tools(refresh=True)

    assert registry.generation() != generation_before
    assert registry.schemas() == before, "isi berubah tanpa tool berubah"


def test_a_changed_tool_is_visible_after_refresh(monkeypatch):
    tools = registry.all_tools()
    name = sorted(tools)[0]

    def fake_discover():
        changed = dict(tools)
        replacement = changed[name]
        monkeypatch.setattr(type(replacement), "description",
                            "deskripsi yang benar-benar baru", raising=False)
        return changed

    monkeypatch.setattr(registry, "_discover", fake_discover)
    registry.all_tools(refresh=True)
    try:
        entry = [item for item in registry.schemas()
                 if item["function"]["name"] == name][0]
        assert entry["function"]["description"] == "deskripsi yang benar-benar baru"
    finally:
        monkeypatch.undo()
        registry.all_tools(refresh=True)


def test_schemas_still_honour_the_allowed_filter():
    tools = sorted(registry.all_tools())
    picked = tools[:2]

    names = [item["function"]["name"] for item in registry.schemas(allowed=picked)]

    assert set(names) <= set(picked)


def test_schemas_still_honour_the_exclude_filter():
    tools = sorted(registry.all_tools())
    dropped = tools[0]

    names = [item["function"]["name"] for item in registry.schemas(exclude=[dropped])]

    assert dropped not in names


# ── pencarian descriptor: indeks, bukan pemindaian ────────────────────────

def test_descriptor_lookup_matches_a_plain_linear_scan():
    """Indeks yang lebih cepat tetapi menjawab beda adalah bug, bukan optimasi."""
    from jarvis.agent.capabilities import REGISTRY

    everything = REGISTRY.descriptors()
    for descriptor in everything:
        found = REGISTRY.descriptor_for_tool(descriptor.tool_name)
        expected = next(item for item in everything
                        if item.tool_name == descriptor.tool_name)
        assert found is not None
        assert found.id == expected.id


def test_descriptor_lookup_of_an_unknown_tool_is_none():
    from jarvis.agent.capabilities import REGISTRY

    assert REGISTRY.descriptor_for_tool("tool_yang_tidak_pernah_ada") is None


def test_descriptor_index_follows_registry_rediscovery():
    from jarvis.agent.capabilities import REGISTRY

    known = sorted(registry.all_tools())[0]
    assert REGISTRY.descriptor_for_tool(known) is not None

    registry.all_tools(refresh=True)

    assert REGISTRY.descriptor_for_tool(known) is not None


def test_a_redefined_descriptor_is_never_answered_from_a_stale_copy():
    """Ini kegagalan yang membuat cache lintas panggilan ditolak di sini.

    ``risk`` masuk ke ``policy.decide``. Menjawab dari salinan lama berarti
    izin dinilai dengan angka yang sudah tidak berlaku — diam-diam.
    """
    from jarvis.agent.capabilities import REGISTRY, CapabilityDescriptor

    saved = dict(REGISTRY._items)
    try:
        REGISTRY._items.clear()
        REGISTRY.register(CapabilityDescriptor(
            id="uji.satu", tool_name="tool_uji_29", toolset="local",
            risk="low", timeout_s=5))
        assert REGISTRY.descriptor_for_tool("tool_uji_29").risk == "low"

        REGISTRY._items.clear()
        REGISTRY.register(CapabilityDescriptor(
            id="uji.satu", tool_name="tool_uji_29", toolset="local",
            risk="high", timeout_s=5))

        assert REGISTRY.descriptor_for_tool("tool_uji_29").risk == "high"
    finally:
        REGISTRY._items.clear()
        REGISTRY._items.update(saved)


def test_schemas_takes_one_descriptor_snapshot_not_one_per_tool():
    """Biaya O(n^2) yang sebenarnya: 103 tool x pembangunan daftar 103-item."""
    from jarvis.agent.capabilities import REGISTRY

    calls = []
    original = REGISTRY.descriptors

    def counting():
        calls.append(1)
        return original()

    REGISTRY.descriptors = counting
    try:
        registry.schemas()
    finally:
        REGISTRY.descriptors = original

    assert len(calls) == 1, f"descriptors() dibangun {len(calls)}x"


# ── pemanasan latar belakang ──────────────────────────────────────────────

def test_prewarm_runs_off_the_calling_thread():
    """Boot tidak boleh menunggu 2,4 detik demi pemanasan."""
    from jarvis.agent import prewarm

    prewarm.reset()
    caller = threading.get_ident()
    seen: list[int] = []

    prewarm.start(steps=[("uji", lambda: seen.append(threading.get_ident()))])
    prewarm.wait(5)

    assert seen and seen[0] != caller


def test_prewarm_only_runs_once():
    from jarvis.agent import prewarm

    prewarm.reset()
    runs: list[int] = []

    prewarm.start(steps=[("uji", lambda: runs.append(1))])
    prewarm.start(steps=[("uji", lambda: runs.append(1))])
    prewarm.wait(5)

    assert len(runs) == 1


def test_one_failing_step_does_not_stop_the_others():
    """SDK gagal dibangun tanpa kredensial; registry tetap harus dipanaskan."""
    from jarvis.agent import prewarm

    prewarm.reset()
    done: list[str] = []

    def boom():
        raise RuntimeError("kredensial kosong")

    prewarm.start(steps=[("gagal", boom), ("lanjut", lambda: done.append("ok"))])
    prewarm.wait(5)

    assert done == ["ok"]


def test_prewarm_can_be_switched_off(monkeypatch):
    from jarvis.agent import prewarm

    prewarm.reset()
    runs: list[int] = []
    monkeypatch.setattr(prewarm.config, "get",
                        lambda path, default=None:
                        False if "prewarm.enabled" in path else default)

    assert prewarm.start(steps=[("uji", lambda: runs.append(1))]) is False
    assert runs == []


def test_prewarm_reports_what_it_actually_warmed(caplog):
    """Diam bukan bukti. Fase 24 ada karena tebakan mahal."""
    import json

    from jarvis.agent import prewarm

    prewarm.reset()
    with caplog.at_level("INFO"):
        prewarm.start(steps=[("registry", lambda: None)])
        prewarm.wait(5)

    events = []
    for record in caplog.records:
        try:
            events.append(json.loads(record.getMessage()))
        except (ValueError, TypeError):
            continue
    line = [event for event in events if event.get("event") == "prewarm.done"]
    assert line, "pemanasan tidak melaporkan apa pun"
    assert "registry_ms" in line[-1]
    assert "total_ms" in line[-1]


def test_prewarm_never_raises_to_its_caller():
    from jarvis.agent import prewarm

    prewarm.reset()
    assert prewarm.start(steps="bukan langkah") in (True, False)
    prewarm.wait(5)


def test_the_default_steps_are_the_measured_bottlenecks():
    """Yang dipanaskan harus yang benar-benar diukur mahal, bukan tebakan."""
    from jarvis.agent import prewarm

    names = [name for name, _ in prewarm.default_steps()]

    assert names == ["registry", "schemas", "llm_sdk"]


@pytest.mark.parametrize("attempt", [1, 2])
def test_prewarm_wait_returns_even_when_nothing_was_started(attempt):
    from jarvis.agent import prewarm

    prewarm.reset()
    assert prewarm.wait(0.2) is False


def test_boot_actually_starts_the_prewarm():
    """Modul yang tidak pernah dipanggil tidak memanaskan apa pun."""
    import inspect

    from jarvis import main as jarvis_main

    source = inspect.getsource(jarvis_main)
    assert "prewarm.start()" in source


def test_a_command_arriving_mid_prewarm_does_not_discover_twice(monkeypatch):
    """Jendela 2,4 detik itu justru saat Takeda paling mungkin bicara.

    Kalau perintahnya memicu penemuan tool KEDUA yang paralel, pemanasan
    malah membuat perintah pertama lebih lambat, bukan lebih cepat.
    """
    discoveries: list[int] = []
    real_discover = registry._discover

    def slow_discover():
        discoveries.append(1)
        time.sleep(0.2)
        return real_discover()

    monkeypatch.setattr(registry, "_discover", slow_discover)
    monkeypatch.setattr(registry, "_tools", None)

    from jarvis.agent import prewarm

    prewarm.reset()
    prewarm.start(steps=[("registry", lambda: registry.all_tools())])
    time.sleep(0.05)                     # perintah tiba di tengah pemanasan
    registry.all_tools()
    prewarm.wait(10)

    assert len(discoveries) == 1, f"tool ditemukan {len(discoveries)}x"
