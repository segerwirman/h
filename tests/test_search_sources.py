"""Fase 18 — hasil pencarian menampilkan sumbernya (S-3).

Permintaan Takeda: saat diminta mencarikan informasi, Jarvis menampilkan sumber
informasi itu dengan membuka browsernya.

Dua cacat terpisah pada perilaku lama:

1. Mode ``news`` **membuang URL sepenuhnya** dari kartu info — sumbernya bahkan
   tidak terlihat sebagai teks, apalagi terbuka.
2. ``web_search`` berhenti di kartu info; browser tidak pernah dibuka. Aturan
   lane suara bahkan melarangnya secara eksplisit.
"""
from __future__ import annotations

import asyncio

import pytest

from jarvis.agent.tools.web import WebSearch


_TEXT_ROWS = [
    {"title": "Hasil Satu", "href": "https://satu.example/artikel",
     "body": "ringkasan satu"},
    {"title": "Hasil Dua", "href": "https://dua.example/artikel",
     "body": "ringkasan dua"},
]
_NEWS_ROWS = [
    {"title": "Berita Satu", "url": "https://berita.example/a",
     "source": "Antara", "date": "2026-08-05", "body": "isi"},
    {"title": "Berita Dua", "url": "https://berita.example/b",
     "source": "Kompas", "date": "2026-08-05", "body": "isi"},
]


@pytest.fixture
def cards(monkeypatch):
    """Tangkap kartu info tanpa menyentuh BUS global lebih dari perlunya."""
    from jarvis.core.bus import BUS

    published: list[dict] = []
    real = BUS.publish

    def _publish(topic, **kwargs):
        if topic == "info.card":
            published.append(kwargs)
            return None
        return real(topic, **kwargs)

    monkeypatch.setattr(BUS, "publish", _publish)
    return published


@pytest.fixture
def rows(monkeypatch):
    """Ganti pencarian jaringan dengan baris tetap."""
    state = {"rows": _TEXT_ROWS}

    async def _to_thread(fn, *a, **k):
        return state["rows"]

    monkeypatch.setattr("jarvis.agent.tools.web.asyncio.to_thread", _to_thread)
    return state


class _Session:
    id = "sesi-uji"

    def __init__(self, task=""):
        self.task = task


def _search(rows_state, *, query="harga gpu", mode="text", task="",
            session=True):
    return asyncio.run(WebSearch().run(
        query=query, mode=mode,
        _session=_Session(task) if session else None))


# ── cacat 1: mode news membuang URL ───────────────────────────────────────

def test_news_card_includes_the_source_url(rows, cards):
    rows["rows"] = _NEWS_ROWS
    _search(rows, mode="news", query="berita hari ini")

    assert cards, "kartu info tidak terbit"
    lines = " ".join(cards[0]["lines"])
    assert "https://berita.example/a" in lines, (
        "sumber berita tidak terlihat sama sekali — bahkan sebagai teks")


def test_text_card_still_includes_urls(rows, cards):
    _search(rows)

    lines = " ".join(cards[0]["lines"])
    assert "https://satu.example/artikel" in lines


# ── cacat 2: browser tidak pernah dibuka ──────────────────────────────────

@pytest.fixture
def opened(monkeypatch):
    """Rekam pemanggilan tool browser tanpa meluncurkan browser sungguhan."""
    calls: list[dict] = []

    async def _execute(name, args, adapter=None, session=None, context=None,
                       **_):
        from jarvis.agent.base import ToolResult
        calls.append({"tool": name, "args": dict(args or {})})
        return ToolResult.success({"url": args.get("url")})

    monkeypatch.setattr("jarvis.agent.registry.execute", _execute)
    return calls


def _mode(monkeypatch, value):
    from jarvis.agent.tools import web as web_mod

    real = web_mod.config

    class _Shim:
        def get(self, path, default=None):
            if path == "agent.search.open_sources":
                return value
            return real.get(path, default)

        def __getattr__(self, name):
            return getattr(real, name)

    monkeypatch.setattr(web_mod, "config", _Shim())


def test_default_mode_is_on_request():
    from jarvis.core import config

    assert config.get("agent.search.open_sources") == "on_request"


@pytest.mark.parametrize("task", [
    "cari harga gpu dan tunjukkan sumbernya",
    "cari berita hari ini, buktikan dari mana",
    "cari info itu lalu buka sumbernya",
    "cari referensi soal ini",
])
def test_asking_for_sources_opens_exactly_one_tab(task, rows, cards, opened,
                                                  monkeypatch):
    _mode(monkeypatch, "on_request")
    _search(rows, task=task)

    tabs = [call for call in opened if call["tool"] == "browser_new_tab"]
    assert len(tabs) == 1, "satu tab per pencarian, bukan satu per hasil"
    assert tabs[0]["args"]["url"] == "https://satu.example/artikel"


def test_plain_search_does_not_open_a_browser(rows, cards, opened, monkeypatch):
    """Membuka browser untuk setiap pencarian akan merebut layar Takeda."""
    _mode(monkeypatch, "on_request")
    _search(rows, task="cari harga gpu")

    assert opened == []


def test_always_mode_opens_without_being_asked(rows, cards, opened,
                                               monkeypatch):
    _mode(monkeypatch, "always")
    _search(rows, task="cari harga gpu")

    assert [call["tool"] for call in opened] == ["browser_new_tab"]


def test_never_mode_stays_closed_even_when_asked(rows, cards, opened,
                                                 monkeypatch):
    _mode(monkeypatch, "never")
    _search(rows, task="cari harga gpu dan tunjukkan sumbernya")

    assert opened == []


def test_unknown_mode_falls_back_to_on_request(rows, cards, opened,
                                               monkeypatch):
    _mode(monkeypatch, "sesuka-hati")
    _search(rows, task="cari harga gpu")
    assert opened == []

    _search(rows, task="cari harga gpu, tunjukkan sumbernya")
    assert [call["tool"] for call in opened] == ["browser_new_tab"]


def test_search_still_succeeds_when_the_browser_fails(rows, cards, monkeypatch):
    """Membuka sumber itu bonus; kegagalannya tidak boleh menggagalkan hasil."""
    async def _boom(*_a, **_k):
        raise RuntimeError("browser mati")

    monkeypatch.setattr("jarvis.agent.registry.execute", _boom)
    _mode(monkeypatch, "always")

    result = _search(rows, task="cari harga gpu")

    assert result.ok is True
    assert "Hasil Satu" in str(result.content)


def test_no_session_means_no_browser(rows, cards, opened, monkeypatch):
    """Cron dan sub-agent tanpa sesi tidak boleh membuka jendela diam-diam."""
    _mode(monkeypatch, "always")
    _search(rows, session=False)

    assert opened == []


def test_empty_results_open_nothing(rows, cards, opened, monkeypatch):
    rows["rows"] = []
    _mode(monkeypatch, "always")
    _search(rows, task="cari sesuatu")

    assert opened == []


# ── aturan lama yang bertentangan ─────────────────────────────────────────

def test_voice_rules_no_longer_forbid_opening_sources():
    """Aturan lane suara dulu melarang persis yang sekarang diminta Takeda."""
    from jarvis.integrations import voice_native_tools

    rules = voice_native_tools.rules().casefold()
    assert "jangan membuka browser hanya untuk pencarian" not in rules
    assert "sumber" in rules


@pytest.mark.parametrize("task", [
    "apa sumber energi terbarukan",
    "cari sumber protein nabati terbaik",
    "jelaskan sumber daya alam indonesia",
    "cari link aja deh",
])
def test_topical_use_of_the_word_source_does_not_open_a_browser(
        task, rows, cards, opened, monkeypatch):
    """"Sumber" sebagai topik bukan permintaan sumber.

    Membuka tab untuk "apa sumber energi terbarukan" merebut layar Takeda
    padahal dia hanya bertanya. Kata itu baru berarti permintaan bila
    berimbuhan pemilik ("sumbernya") atau didahului kata kerja meminta.
    """
    _mode(monkeypatch, "on_request")
    _search(rows, task=task)

    assert opened == []


@pytest.mark.parametrize("task", [
    "cari harga gpu, sebutkan sumbernya",
    "cari data itu dan sertakan sumber",
    "cari beritanya lalu tampilkan link",
    "cari itu, tunjukkan sumber-sumbernya",
])
def test_explicit_source_requests_still_open(task, rows, cards, opened,
                                             monkeypatch):
    _mode(monkeypatch, "on_request")
    _search(rows, task=task)

    assert [call["tool"] for call in opened] == ["browser_new_tab"], task
