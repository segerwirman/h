"""Fase 4 (§6) — locale web/berita Indonesia: resolver prioritas
config → bahasa/Silent Language Memory → fallback id-ID, injeksi region ke
tool web (agent + action legacy), dan augmentasi query berita generik.

Deterministik: config, memori, dan ddgs dipalsukan; tidak ada network.
"""
from __future__ import annotations

import asyncio
import sys
import types

import pytest

from jarvis.core import config
from jarvis.core import locale as jlocale


@pytest.fixture()
def cfg(monkeypatch):
    """config.get palsu: locale.* dari dict (default: kosong), sisanya asli."""
    values: dict = {}
    orig = config.get

    def fake(key, default=None):
        if key in values:
            return values[key]
        if key.startswith("locale."):
            return default
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    return values


@pytest.fixture()
def no_memory(monkeypatch):
    monkeypatch.setattr(jlocale, "_memory_language", lambda: "")


# ── konfigurasi nyata ─────────────────────────────────────────────────────

def test_config_yaml_locale_section_exists():
    config.reload()
    assert config.get("locale.region") == "ID"
    assert config.get("locale.language") == "id"
    assert config.get("locale.timezone") == "Asia/Jakarta"
    assert config.get("locale.news_market") == "id-ID"


# ── prioritas resolusi §6.3 ───────────────────────────────────────────────

def test_prioritas_1_config_eksplisit(cfg, no_memory):
    cfg["locale.region"] = "US"
    cfg["locale.language"] = "en"
    loc = jlocale.resolve("apa berita terbaru hari ini")
    assert (loc.region, loc.language, loc.source) == ("US", "en", "config")
    assert not loc.indonesian
    assert jlocale.ddg_region(loc=loc) == "us-en"


def test_prioritas_2_bahasa_perintah(cfg, no_memory):
    loc = jlocale.resolve("apa berita terbaru hari ini")
    assert (loc.region, loc.language, loc.source) == ("ID", "id", "text")
    assert loc.indonesian


def test_prioritas_2_silent_language_memory(cfg, monkeypatch):
    monkeypatch.setattr(jlocale, "_memory_language",
                        lambda: "indonesian (bahasa indonesia)")
    loc = jlocale.resolve("please give me the latest news today")
    assert (loc.region, loc.source) == ("ID", "memory")


def test_prioritas_3_fallback_id(cfg, no_memory):
    loc = jlocale.resolve("please give me the latest news today")
    assert (loc.region, loc.language, loc.source) == ("ID", "id", "fallback")
    assert loc.news_market == "id-ID"
    assert loc.timezone == "Asia/Jakarta"


def test_resolver_tidak_pernah_raise(monkeypatch):
    def boom(key, default=None):
        raise RuntimeError("config mati")

    monkeypatch.setattr(config, "get", boom)
    monkeypatch.setattr(jlocale, "_memory_language", lambda: "")
    loc = jlocale.resolve("halo")
    assert loc.region == "ID"


def test_memory_language_membaca_identity(monkeypatch):
    import memory.memory_manager as mm

    monkeypatch.setattr(mm, "load_memory", lambda: {
        "identity": {"language": {"value": "Indonesian"}}})
    assert jlocale._memory_language() == "indonesian"


def test_toggle_region_mengubah_hasil(cfg, no_memory):
    """§6.5 — mengubah locale.region harus mengubah region efektif."""
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    assert jlocale.ddg_region("berita") == "id-id"
    cfg["locale.region"] = "DE"
    cfg["locale.language"] = "de"
    assert jlocale.ddg_region("berita") == "de-de"


def test_accept_language_format(cfg, no_memory):
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    assert jlocale.accept_language() == "id-ID,id;q=0.9,en;q=0.6"
    cfg["locale.region"] = "US"
    cfg["locale.language"] = "en"
    assert jlocale.accept_language() == "en-US,en;q=0.9"


# ── augmentasi query berita §6.2 ──────────────────────────────────────────

def test_is_generic_news():
    assert jlocale.is_generic_news("berita terbaru hari ini")
    assert jlocale.is_generic_news("apa berita terbaru hari ini")
    assert jlocale.is_generic_news("top world news today")
    assert jlocale.is_generic_news("world news today")
    assert jlocale.is_generic_news("")
    assert not jlocale.is_generic_news("berita terbaru Manchester United")
    assert not jlocale.is_generic_news("chip AI Nvidia news")


def test_news_query_generik_dilokalkan(cfg, no_memory):
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    assert jlocale.news_query("berita terbaru hari ini") == \
        "berita terbaru Indonesia hari ini"
    assert jlocale.news_query("top world news today") == \
        "berita terbaru Indonesia hari ini"


def test_news_query_spesifik_tidak_diubah(cfg, no_memory):
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    q = "berita terbaru Manchester United"
    assert jlocale.news_query(q) == q


def test_news_query_non_indonesia(cfg, no_memory):
    cfg["locale.region"] = "US"
    cfg["locale.language"] = "en"
    assert jlocale.news_query("top world news today") == "top news today"


# ── stub ddgs bersama ─────────────────────────────────────────────────────

class _FakeDDGS:
    calls: list[tuple[str, str, dict]] = []
    rows_news = [{"title": "Pemerintah umumkan kebijakan ekonomi baru",
                  "body": "Rincian kebijakan ekonomi.",
                  "url": "https://news.example.id/1",
                  "source": "Kompas", "date": "2026-07-20T06:00:00"}]
    rows_text = [{"title": "Halaman", "body": "Isi.",
                  "href": "https://example.id"}]

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def news(self, query, **kwargs):
        _FakeDDGS.calls.append(("news", query, kwargs))
        return list(_FakeDDGS.rows_news)

    def text(self, query, **kwargs):
        _FakeDDGS.calls.append(("text", query, kwargs))
        return list(_FakeDDGS.rows_text)


@pytest.fixture()
def fake_ddgs(monkeypatch):
    _FakeDDGS.calls = []
    module = types.ModuleType("ddgs")
    module.DDGS = _FakeDDGS
    monkeypatch.setitem(sys.modules, "ddgs", module)
    return _FakeDDGS


# ── tool agent web_search ─────────────────────────────────────────────────

def test_web_search_news_injeksi_region_dan_augmentasi(cfg, no_memory,
                                                       fake_ddgs,
                                                       monkeypatch):
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    from jarvis.agent.tools import web as web_mod
    monkeypatch.setattr(web_mod, "_MIN_INTERVAL_S", 0.0)

    tool = web_mod.WebSearch()
    res = asyncio.run(tool.run(query="apa berita terbaru hari ini",
                               mode="news"))
    assert res.ok
    mode, query, kwargs = fake_ddgs.calls[0]
    assert mode == "news"
    assert query == "berita terbaru Indonesia hari ini"
    assert kwargs["region"] == "id-id"
    assert "Kompas" in res.content and "2026-07-20" in res.content


def test_web_search_text_region_tanpa_augmentasi(cfg, no_memory, fake_ddgs,
                                                 monkeypatch):
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    from jarvis.agent.tools import web as web_mod
    monkeypatch.setattr(web_mod, "_MIN_INTERVAL_S", 0.0)
    seen: list[dict] = []
    from jarvis.core import bus
    monkeypatch.setattr(
        bus.BUS, "publish",
        lambda topic, **data: seen.append({"topic": topic, **data}))

    tool = web_mod.WebSearch()
    res = asyncio.run(tool.run(query="dokumentasi python asyncio",
                               mode="text"))
    assert res.ok
    mode, query, kwargs = fake_ddgs.calls[0]
    assert mode == "text"
    assert query == "dokumentasi python asyncio"
    assert kwargs["region"] == "id-id"
    assert seen and seen[0]["kind"] == "search"
    assert seen[0]["source"] == "DuckDuckGo Search"


def test_web_search_region_ikut_config(cfg, no_memory, fake_ddgs,
                                       monkeypatch):
    cfg["locale.region"] = "DE"
    cfg["locale.language"] = "de"
    from jarvis.agent.tools import web as web_mod
    monkeypatch.setattr(web_mod, "_MIN_INTERVAL_S", 0.0)

    tool = web_mod.WebSearch()
    asyncio.run(tool.run(query="nachrichten", mode="news"))
    _, _, kwargs = fake_ddgs.calls[0]
    assert kwargs["region"] == "de-de"


def test_web_extract_fallback_accept_language(cfg, no_memory, monkeypatch):
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    captured = {}

    traf = types.ModuleType("trafilatura")
    traf.fetch_url = lambda url: None
    traf.extract = lambda downloaded, **kw: "Isi artikel bahasa Indonesia."
    monkeypatch.setitem(sys.modules, "trafilatura", traf)

    class _Resp:
        text = "<html>artikel</html>"

        def raise_for_status(self):
            return None

    req = types.ModuleType("requests")

    def fake_get(url, timeout=25, headers=None):
        captured["headers"] = dict(headers or {})
        return _Resp()

    req.get = fake_get
    monkeypatch.setitem(sys.modules, "requests", req)

    from jarvis.agent.tools.web import WebExtract
    res = asyncio.run(WebExtract().run(url="https://example.id/artikel"))
    assert res.ok
    assert captured["headers"]["Accept-Language"].startswith("id-ID")


# ── action legacy (jalur suara Gemini Live) ───────────────────────────────

def test_action_ddg_news_region_dan_tanggal(cfg, no_memory, fake_ddgs):
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    from actions import web_search as action

    rows = action._ddg_news("berita terbaru hari ini")
    _, _, kwargs = fake_ddgs.calls[0]
    assert kwargs["region"] == "id-id"
    assert rows and rows[0]["date"] == "2026-07-20T06:00:00"
    assert rows[0]["source"] == "Kompas"


def test_action_news_briefing_query_dilokalkan(cfg, no_memory, fake_ddgs,
                                               monkeypatch):
    """Query briefing hardcoded Inggris ('top world news today') menjadi
    frasa lokal penuh tanpa menyentuh main.py (FROZEN)."""
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    from actions import web_search as action

    def gemini_down(q):
        raise RuntimeError("gemini offline")

    monkeypatch.setattr(action, "_gemini_search", gemini_down)
    out = action._news("top world news today")
    news_calls = [c for c in fake_ddgs.calls if c[0] == "news"]
    assert news_calls
    assert news_calls[0][1] == "berita terbaru Indonesia hari ini"
    assert news_calls[0][2]["region"] == "id-id"
    assert "Pemerintah umumkan kebijakan ekonomi baru" in out
    assert "Kompas" in out


def test_action_news_subjek_spesifik_dipertahankan(cfg, no_memory, fake_ddgs,
                                                   monkeypatch):
    cfg["locale.region"] = "ID"
    cfg["locale.language"] = "id"
    from actions import web_search as action

    monkeypatch.setattr(
        action, "_gemini_search",
        lambda q: (_ for _ in ()).throw(RuntimeError("offline")))
    action._news("berita terbaru Manchester United")
    news_calls = [c for c in fake_ddgs.calls if c[0] == "news"]
    assert news_calls[0][1] == "berita terbaru Manchester United"
    assert news_calls[0][2]["region"] == "id-id"


def test_action_locale_mati_degrade_ke_perilaku_lama(cfg, no_memory,
                                                     fake_ddgs, monkeypatch):
    """Resolver locale gagal → pencarian tetap jalan tanpa region (jujur)."""
    from actions import web_search as action

    monkeypatch.setattr(action, "_locale", lambda q="": None)
    rows = action._ddg_search("apa saja")
    assert rows
    _, _, kwargs = fake_ddgs.calls[0]
    assert "region" not in kwargs
