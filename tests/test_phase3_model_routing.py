"""Fase 3 (§3) — model routing per lane: resolusi light/heavy, rantai
fallback, degrade jujur, dan pin side-task ke lane ringan (§3.3).

Semua test deterministik: config dan registry provider dipalsukan sehingga
tidak bergantung providers.json/api key mesin.
"""
from __future__ import annotations

import asyncio

import pytest

from jarvis.agent import llm_client, model_routing
from jarvis.agent.llm_client import ChatResponse, ToolCall
from jarvis.agent.providers import Provider
from jarvis.core import config


def _prov(name, kind="openai_compat", api_key="k", base_url="u", model="m"):
    return Provider(name=name, kind=kind, label=name, api_key=api_key,
                    base_url=base_url, model=model)


@pytest.fixture()
def cfg(monkeypatch):
    """config.get palsu: routing.*/auxiliary.* dari dict, sisanya asli."""
    values: dict = {}
    orig = config.get

    def fake(key, default=None):
        if key in values:
            return values[key]
        if key.startswith(("routing.", "auxiliary.")):
            return default
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    return values


@pytest.fixture()
def providers(monkeypatch):
    """Registry provider palsu untuk model_routing (get_provider + active)."""
    table: dict[str, Provider] = {}

    def fake_get(name=None):
        key = name or "gemini"
        if key not in table:
            raise KeyError(key)
        return table[key]

    monkeypatch.setattr(model_routing, "get_provider", fake_get)
    from jarvis.agent import providers as prov_mod
    monkeypatch.setattr(prov_mod, "active_name", lambda: table.get(
        "__active__", _prov("gemini")).name)

    def set_active(name):
        table["__active__"] = table[name]

    table["set_active"] = set_active  # type: ignore[assignment]
    return table


def _fill(providers, **provs):
    for name, p in provs.items():
        providers[name] = p


# ── konfigurasi nyata di config.yaml ──────────────────────────────────────

def test_config_yaml_routing_section_exists():
    """Section §3.1 benar-benar ada di config.yaml repo."""
    config.reload()
    assert config.get("routing.light.provider") == "gemini"
    assert config.get("routing.heavy.provider") == "custom"
    assert config.get("routing.heavy.fallback") == ["openrouter", "local"]
    assert config.get("routing.heavy.allow_light_fallback") is True


def test_openrouter_ada_di_defaults():
    from jarvis.agent.providers import DEFAULTS, list_names
    assert "openrouter" in DEFAULTS
    assert DEFAULTS["openrouter"]["env_key"] == "OPENROUTER_API_KEY"
    assert "openrouter" in list_names()


# ── lane ringan ───────────────────────────────────────────────────────────

def test_light_name_default_dan_override(cfg):
    assert model_routing.light_name() == "gemini"
    cfg["routing.light.provider"] = "local"
    assert model_routing.light_name() == "local"


def test_light_client_pakai_factory_cache(cfg, monkeypatch):
    sentinel = object()
    seen = {}

    def fake_client(name=None):
        seen["name"] = name
        return sentinel

    monkeypatch.setattr(llm_client, "client", fake_client)
    assert model_routing.light_client() is sentinel
    assert seen["name"] == "gemini"


def test_light_client_model_override(cfg, monkeypatch):
    cfg["routing.light.model"] = "model-kecil"
    monkeypatch.setattr(model_routing, "get_provider",
                        lambda name=None: _prov("gemini", kind="gemini",
                                                model="default"))
    cl = model_routing.light_client()
    assert isinstance(cl, llm_client.LLMClient)
    assert cl.provider.model == "model-kecil"


# ── kandidat lane berat ───────────────────────────────────────────────────

def test_heavy_candidates_urutan_dan_dedup(cfg, providers):
    _fill(providers, gemini=_prov("gemini", kind="gemini"),
          openai=_prov("openai"), openrouter=_prov("openrouter"),
          local=_prov("local"))
    providers["set_active"]("openai")
    cfg["routing.heavy.provider"] = "anthropic"
    cfg["routing.heavy.fallback"] = ["openrouter", "anthropic", "local"]
    assert model_routing.heavy_candidates() == [
        "anthropic", "openai", "openrouter", "local"]


def test_heavy_candidates_gemini_light_tidak_dipromosikan(cfg, providers):
    """§0 keputusan 3: provider aktif == lane ringan → BUKAN kandidat berat."""
    _fill(providers, gemini=_prov("gemini", kind="gemini"))
    providers["set_active"]("gemini")
    cfg["routing.heavy.fallback"] = []
    assert model_routing.heavy_candidates() == []


def test_heavy_candidates_light_fallback_hanya_saat_opt_in(cfg, providers):
    _fill(providers, gemini=_prov("gemini", kind="gemini"))
    providers["set_active"]("gemini")
    cfg["routing.heavy.fallback"] = []
    cfg["routing.heavy.allow_light_fallback"] = True
    assert model_routing.heavy_candidates() == ["gemini"]


def test_heavy_resolution_bisa_memakai_gemini_sebagai_kandidat_terakhir(
    cfg, providers, monkeypatch
):
    _fill(
        providers,
        gemini=_prov("gemini", kind="gemini"),
        custom=_prov("custom", api_key="", model=""),
    )
    providers["set_active"]("gemini")
    cfg["routing.heavy.provider"] = "custom"
    cfg["routing.heavy.fallback"] = []
    cfg["routing.heavy.allow_light_fallback"] = True
    monkeypatch.setattr(llm_client, "client", lambda name=None: ("client", name))
    client, name, _reason = model_routing.heavy_resolution()
    assert client == ("client", "gemini")
    assert name == "gemini"


def test_heavy_candidates_active_non_light_dihormati(cfg, providers):
    """Pilihan eksplisit user di Settings (aktif ≠ light) tetap dipakai."""
    _fill(providers, gemini=_prov("gemini", kind="gemini"),
          anthropic=_prov("anthropic", kind="anthropic"))
    providers["set_active"]("anthropic")
    cfg["routing.heavy.fallback"] = []
    assert model_routing.heavy_candidates() == ["anthropic"]


# ── resolusi lane berat ───────────────────────────────────────────────────

def test_heavy_resolution_lewati_yang_belum_konfigurasi(cfg, providers,
                                                        monkeypatch):
    _fill(providers, gemini=_prov("gemini", kind="gemini"),
          openrouter=_prov("openrouter", api_key="", model=""),   # kosong
          local=_prov("local", model="qwen-3"))
    providers["set_active"]("gemini")
    cfg["routing.heavy.fallback"] = ["openrouter", "local"]
    monkeypatch.setattr(llm_client, "client",
                        lambda name=None: ("client", name))
    cl, name, reason = model_routing.heavy_resolution()
    assert cl == ("client", "local")
    assert name == "local"
    assert "local" in reason


def test_heavy_resolution_none_saat_kosong(cfg, providers):
    _fill(providers, gemini=_prov("gemini", kind="gemini"))
    providers["set_active"]("gemini")
    cfg["routing.heavy.fallback"] = []
    cl, name, reason = model_routing.heavy_resolution()
    assert cl is None and name == ""
    assert "tidak ada provider berat" in reason


def test_heavy_resolution_model_override_hanya_untuk_eksplisit(cfg, providers):
    _fill(providers, gemini=_prov("gemini", kind="gemini"),
          openai=_prov("openai", model="gpt-default"))
    providers["set_active"]("gemini")
    cfg["routing.heavy.provider"] = "openai"
    cfg["routing.heavy.model"] = "gpt-berat"
    cl, name, _ = model_routing.heavy_resolution()
    assert name == "openai"
    assert isinstance(cl, llm_client.LLMClient)
    assert cl.provider.model == "gpt-berat"


def test_heavy_ready_toggle_mengubah_perilaku(cfg, providers, monkeypatch):
    """Mengisi routing.heavy.provider benar-benar menyalakan lane berat."""

    class Ok:
        def available(self):
            return True

    monkeypatch.setattr(llm_client, "client", lambda name=None: Ok())
    _fill(providers, gemini=_prov("gemini", kind="gemini"),
          local=_prov("local", model="qwen-3"))
    providers["set_active"]("gemini")
    cfg["routing.heavy.fallback"] = []
    assert model_routing.heavy_ready() is False
    cfg["routing.heavy.provider"] = "local"
    assert model_routing.heavy_ready() is True


# ── failover dalam-run ────────────────────────────────────────────────────

def test_failover_error_pola():
    assert model_routing.failover_error("HTTP 402 Payment Required")
    assert model_routing.failover_error("insufficient credit balance")
    assert model_routing.failover_error("Quota exceeded for model")
    assert model_routing.failover_error("request timed out")
    assert model_routing.failover_error("429 rate limit")
    assert model_routing.failover_error("404 model not found")
    assert model_routing.failover_error(
        "function calling is not supported by this model")
    assert not model_routing.failover_error("invalid tool schema")
    assert not model_routing.failover_error(None)


def test_next_heavy_client_lewati_yang_sudah_dicoba(cfg, providers,
                                                    monkeypatch):
    _fill(providers, gemini=_prov("gemini", kind="gemini"),
          openai=_prov("openai"), local=_prov("local", model="qwen-3"))
    providers["set_active"]("gemini")
    cfg["routing.heavy.provider"] = "openai"
    cfg["routing.heavy.fallback"] = ["local"]
    monkeypatch.setattr(llm_client, "client",
                        lambda name=None: ("client", name))
    nxt = model_routing.next_heavy_client({"openai"})
    assert nxt == (("client", "local"), "local")
    assert model_routing.next_heavy_client({"openai", "local"}) is None


def test_loop_failover_402_pindah_provider(monkeypatch, tmp_path):
    """Loop: provider berat pertama 402 → provider fallback menyelesaikan."""
    from jarvis.agent import loop as agent_loop
    from jarvis.agent import registry

    class Broke:
        def available(self):
            return True

        def chat(self, messages, tools=None, **kw):
            return ChatResponse(error="402 insufficient credit")

    class Works:
        def available(self):
            return True

        def chat(self, messages, tools=None, **kw):
            return ChatResponse(content="Beres lewat fallback.")

    monkeypatch.setattr(model_routing, "heavy_resolution",
                        lambda: (Broke(), "openai", "test"))
    monkeypatch.setattr(model_routing, "next_heavy_client",
                        lambda tried: (Works(), "local")
                        if "local" not in tried else None)
    monkeypatch.setattr(agent_loop, "reflect_async", lambda s: None)
    monkeypatch.setattr(registry, "_tools", {})

    import jarvis.agent.memory_store as ms
    import jarvis.agent.session as sess
    db = tmp_path / "agent.sqlite"
    monkeypatch.setattr(ms, "db_path", lambda: db)
    monkeypatch.setattr(sess, "db_path", lambda: db)

    from jarvis.agent.adapters.base import NullAdapter
    adapter = NullAdapter()
    result = asyncio.run(agent_loop.run("tugas uji", adapter=adapter))
    assert result.ok
    assert "fallback" in result.text
    registry._tools = None


def test_loop_degrade_jujur_saat_heavy_kosong(monkeypatch, tmp_path):
    from jarvis.agent import loop as agent_loop

    monkeypatch.setattr(model_routing, "heavy_resolution",
                        lambda: (None, "", "kosong"))

    import jarvis.agent.memory_store as ms
    import jarvis.agent.session as sess
    db = tmp_path / "agent.sqlite"
    monkeypatch.setattr(ms, "db_path", lambda: db)
    monkeypatch.setattr(sess, "db_path", lambda: db)

    from jarvis.agent.adapters.base import NullAdapter
    adapter = NullAdapter()
    result = asyncio.run(agent_loop.run("kerjakan riset itu",
                                        adapter=adapter))
    assert not result.ok
    assert "tugas berat belum diatur" in result.text
    assert adapter.outputs and "Settings" in adapter.outputs[0]


def test_loop_degrade_bahasa_inggris(monkeypatch, tmp_path):
    from jarvis.agent import loop as agent_loop

    monkeypatch.setattr(model_routing, "heavy_resolution",
                        lambda: (None, "", "kosong"))
    import jarvis.agent.memory_store as ms
    import jarvis.agent.session as sess
    db = tmp_path / "agent.sqlite"
    monkeypatch.setattr(ms, "db_path", lambda: db)
    monkeypatch.setattr(sess, "db_path", lambda: db)

    from jarvis.agent.adapters.base import NullAdapter
    adapter = NullAdapter()
    result = asyncio.run(agent_loop.run(
        "please research the latest market data and build the report",
        adapter=adapter))
    assert not result.ok
    assert "heavy tasks is not set up" in result.text


# ── dispatch & pesan refusal ──────────────────────────────────────────────

def test_dispatch_available_mengikuti_heavy_ready(monkeypatch):
    from jarvis.agent import dispatch

    monkeypatch.setattr(model_routing, "heavy_ready", lambda: False)
    assert dispatch.available() is False
    monkeypatch.setattr(model_routing, "heavy_ready", lambda: True)
    assert dispatch.available() is True


def test_unavailable_reason_heavy_unconfigured(monkeypatch):
    from jarvis.agent import interaction

    monkeypatch.setattr(model_routing, "heavy_ready", lambda: False)
    reason_id = interaction.unavailable_reason("kerjakan riset pasar")
    assert "tugas berat belum diatur" in reason_id
    assert "Settings" in reason_id
    reason_en = interaction.unavailable_reason(
        "please build the report now", language="en")
    assert "heavy tasks is not set up" in reason_en


def test_unavailable_reason_busy(monkeypatch):
    from jarvis.agent import dispatch, interaction

    monkeypatch.setattr(model_routing, "heavy_ready", lambda: True)
    monkeypatch.setattr(dispatch, "is_active", lambda task: True)
    reason = interaction.unavailable_reason("kerjakan riset pasar")
    assert "masih berjalan" in reason


# ── side-task §3.3 ────────────────────────────────────────────────────────

def test_compression_default_lane_ringan(cfg, monkeypatch):
    sentinel = object()
    monkeypatch.setattr(model_routing, "light_client", lambda: sentinel)
    assert model_routing.compression_client() is sentinel


def test_compression_override_auxiliary_menang(cfg, monkeypatch):
    """Toggle auxiliary.compression tetap toggle nyata setelah §3.3."""
    from jarvis.agent import auxiliary

    cfg["auxiliary.compression.provider"] = "local"
    sentinel = object()
    monkeypatch.setattr(auxiliary, "client_for",
                        lambda task: sentinel if task == "compression"
                        else None)
    assert model_routing.compression_client() is sentinel


def test_embedding_pakai_lane_ringan(monkeypatch):
    from jarvis.agent import memory_store

    calls = {}

    class EmbedClient:
        def available(self):
            return True

        def embed(self, texts):
            calls["texts"] = texts
            return [[0.1, 0.2] for _ in texts]

    monkeypatch.setattr(model_routing, "light_client",
                        lambda: EmbedClient())
    out = memory_store._embed(["halo dunia"])
    assert out == [[0.1, 0.2]]
    assert calls["texts"] == ["halo dunia"]


def test_kompaksi_loop_memakai_klien_ringan(monkeypatch, tmp_path):
    """Kompaksi dipanggil dengan compression_client, bukan klien berat."""
    from jarvis.agent import loop as agent_loop
    from jarvis.agent import context as ctx
    from jarvis.agent import registry

    used = {}

    class LightStub:
        def generate(self, *a, **kw):
            used["light"] = True
            return "ringkasan"

    class Heavy:
        def __init__(self):
            self.n = 0

        def available(self):
            return True

        def chat(self, messages, tools=None, **kw):
            self.n += 1
            if self.n == 1:
                return ChatResponse(content=None, tool_calls=[
                    ToolCall(id="c1", name="noop", arguments={})])
            return ChatResponse(content="Selesai.")

    from jarvis.agent.base import Tool, ToolResult

    class Noop(Tool):
        name = "noop"
        description = "tidak melakukan apa pun"
        read_only = True
        timeout_s = 5

        async def run(self, **_):
            return ToolResult.success("ok")

    monkeypatch.setattr(model_routing, "heavy_resolution",
                        lambda: (Heavy(), "openai", "test"))
    monkeypatch.setattr(model_routing, "compression_client",
                        lambda: LightStub())
    monkeypatch.setattr(agent_loop, "reflect_async", lambda s: None)
    monkeypatch.setattr(registry, "_tools", {"noop": Noop()})
    monkeypatch.setattr(ctx, "over_threshold", lambda messages: True)
    monkeypatch.setattr(ctx, "compact",
                        lambda messages, llm: (llm.generate(), messages)[1])

    import jarvis.agent.memory_store as ms
    import jarvis.agent.session as sess
    db = tmp_path / "agent.sqlite"
    monkeypatch.setattr(ms, "db_path", lambda: db)
    monkeypatch.setattr(sess, "db_path", lambda: db)

    from jarvis.agent.adapters.base import NullAdapter
    result = asyncio.run(agent_loop.run("tugas uji", adapter=NullAdapter()))
    assert result.ok
    assert used.get("light") is True
    registry._tools = None
