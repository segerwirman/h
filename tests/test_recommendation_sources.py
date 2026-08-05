"""Fase 23 — rekomendasi membuka SUMBERNYA, bukan transkrip user (S-23).

Takeda: *"ketika jarvis memberi rekomendasi … memberikan opsi untuk menampilkan
informasi itu di chrome, baik sumber itu berupa web, social media atau map.
Bukan menampilkan apa yang saya ucapkan di chrome."*

Bukti lapangan — judul jendela Chrome miliknya:

    'kan saya restoran yang - Search - Google Chrome'

Itu pencarian Google atas potongan transkrip ("…kan saya restoran yang…"),
karena `run_search` jatuh ke `spoken` lalu mengirimnya ke browser sistem
sebagai kueri.
"""
from __future__ import annotations

import pytest

from jarvis.agent import sources


_ROWS = [
    {"title": "Warung Bu Tini", "href": "https://warungbutini.example/menu",
     "body": "warung sunda"},
    {"title": "Warung Bu Tini di Instagram",
     "href": "https://www.instagram.com/warungbutini/", "body": "foto"},
    {"title": "Warung Bu Tini - Google Maps",
     "href": "https://www.google.com/maps/place/Warung+Bu+Tini", "body": "peta"},
]


# ── sumber bertipe, diambil dari hasil tool ───────────────────────────────

def test_sources_are_typed_by_where_they_come_from():
    found = sources.from_search_rows(_ROWS)
    kinds = {s.kind for s in found}

    assert kinds == {"web", "social", "map"}
    assert next(s for s in found if s.kind == "map").url.startswith(
        "https://www.google.com/maps")
    assert next(s for s in found if s.kind == "social").url.startswith(
        "https://www.instagram.com")


@pytest.mark.parametrize("url,kind", [
    ("https://www.instagram.com/x/", "social"),
    ("https://www.tiktok.com/@x", "social"),
    ("https://x.com/x", "social"),
    ("https://web.facebook.com/x", "social"),
    ("https://www.youtube.com/watch?v=a", "social"),
    ("https://maps.google.com/?q=a", "map"),
    ("https://www.google.com/maps/place/A", "map"),
    ("https://goo.gl/maps/abc", "map"),
    ("https://kompas.com/artikel", "web"),
])
def test_kind_classification(url, kind):
    assert sources.classify(url) == kind


def test_rows_without_usable_urls_yield_nothing():
    assert sources.from_search_rows([{"title": "x", "href": ""}]) == []
    assert sources.from_search_rows([]) == []


# ── tempat/makanan: peta adalah sumber yang benar ─────────────────────────

@pytest.mark.parametrize("task", [
    "carikan saya restoran yang enak di dekat sini",
    "cari tempat makan sunda",
    "rekomendasi kafe buat kerja",
    "warung soto terdekat",
])
def test_place_requests_prefer_a_map(task):
    assert sources.is_place_request(task) is True


@pytest.mark.parametrize("task", [
    "cari harga gpu terbaru",
    "apa itu transformer",
    "cari berita hari ini",
])
def test_non_place_requests_do_not_force_a_map(task):
    assert sources.is_place_request(task) is False


def test_place_request_ranks_the_map_first():
    ranked = sources.rank(_ROWS, task="carikan restoran yang enak")

    assert ranked[0].kind == "map", [s.kind for s in ranked]


def test_ordinary_request_ranks_the_web_page_first():
    ranked = sources.rank(_ROWS, task="cari resep warung bu tini")

    assert ranked[0].kind == "web"


def test_place_request_without_any_map_row_synthesises_one():
    """Rekomendasi tempat tanpa baris Maps tetap layak dapat lokasi.

    Yang disintesis adalah pencarian Maps atas NAMA TEMPAT dari hasil tool —
    bukan atas kalimat yang diucapkan user.
    """
    rows = [{"title": "Warung Bu Tini", "href": "https://warungbutini.example"}]
    ranked = sources.rank(rows, task="carikan restoran enak")

    top = ranked[0]
    assert top.kind == "map"
    assert "Warung+Bu+Tini" in top.url or "Warung%20Bu%20Tini" in top.url
    assert "carikan" not in top.url.casefold(), (
        "URL tidak boleh dibangun dari ucapan user")


# ── transkrip mentah tidak boleh menjadi kueri ────────────────────────────

def test_no_source_is_built_from_the_spoken_words():
    ranked = sources.rank([], task="carikan saya restoran yang enak di sini")
    assert ranked == [], "tanpa hasil tool, tidak ada sumber yang bisa dibuka"


def test_run_search_no_longer_sends_the_transcript_to_the_browser():
    """Bukti lapangan: 'kan saya restoran yang - Search - Google Chrome'."""
    from pathlib import Path

    source = Path("jarvis/ui/window.py").read_text(encoding="utf-8")
    body = source.split("def run_search")[1].split("\n    def ")[0]
    # Invariannya adalah AKSI, bukan penyebutan: docstring boleh mengutip kode
    # lama untuk menjelaskan sebabnya, tetapi tidak boleh ada lagi jalur yang
    # meluncurkan browser sistem dengan kueri buatan sendiri.
    code = "\n".join(
        line for line in body.splitlines()
        if not line.strip().startswith(("#", '"""', "'''", "'", '"'))
    )
    assert "open_external_url" not in code, (
        "masih meluncurkan browser sistem dari jalur pencarian suara")


# ── tawaran, bukan aksi otomatis ──────────────────────────────────────────

def test_offer_names_the_kinds_available():
    offer = sources.offer_text(sources.rank(_ROWS, task="carikan restoran"))

    lowered = offer.casefold()
    assert "peta" in lowered or "maps" in lowered
    assert "?" in offer, "tawaran harus berupa pertanyaan"


def test_offer_is_empty_without_sources():
    assert sources.offer_text([]) == ""


# ── dibuka di Chrome user ─────────────────────────────────────────────────

def test_open_prefers_the_users_chrome(monkeypatch):
    from jarvis.integrations import user_browser

    calls: list[str] = []
    monkeypatch.setattr(user_browser, "status", lambda: {"attached": True})
    monkeypatch.setattr(
        user_browser, "open_url",
        lambda url, **_: (calls.append(url), {"ok": True, "url": url})[1])

    result = sources.open_source(
        sources.SourceCandidate("map", "Peta", "https://maps.example/a"))

    assert result["ok"] is True
    assert result["where"] == "user_browser"
    assert calls == ["https://maps.example/a"]


def test_open_says_why_when_the_users_chrome_is_unreachable(monkeypatch):
    from jarvis.integrations import user_browser

    monkeypatch.setattr(
        user_browser, "status",
        lambda: {"attached": False, "reason": "port 9222 tidak menjawab"})

    result = sources.open_source(
        sources.SourceCandidate("web", "Situs", "https://a.example"))

    assert result["ok"] is False
    assert "9222" in result["reason"]
