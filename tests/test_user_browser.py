"""Fase 21 — Jarvis melihat & mengendalikan Chrome milik Takeda (S-21).

Takeda: *"perintah untuk pause youtube tapi jarvis tidak mengetahui jika
browser ada banyak tab yang terbuka."*

`browser_media` dan `browser_tabs` menggerakkan Chrome milik AGENT, yang
sengaja terisolasi dari profil user ([browser.py:41-47]). Jadi Jarvis memeriksa
browsernya sendiri yang kosong dan jujur melaporkan tidak ada media — sementara
YouTube Takeda memutar di Chrome pribadinya.

Isolasi itu TIDAK dibuang: ia menyelesaikan masalah nyata (lock profil, tab
user tidak dirusak agent). Yang ditambah adalah jalur terpisah yang eksplisit
menyasar browser user.

Kendala keras yang membentuk seluruh fase ini: **Chrome yang sudah berjalan
tidak bisa di-attach belakangan.** Ia harus dimulai dengan
``--remote-debugging-port``. Karena itu satu-satunya sikap jujur saat port
tidak ada adalah MENGATAKANNYA — bukan melaporkan "tidak ada video".
"""
from __future__ import annotations

import pytest

from jarvis.integrations import user_browser as ub


class _FakePage:
    def __init__(self, url, title, media=None):
        self.url = url
        self._title = title
        self._media = media or {}
        self.evaluated: list[str] = []
        self.brought_front = False

    def title(self):
        return self._title

    def evaluate(self, script, *args):
        # Rekam AKSI, bukan skripnya: _MEDIA_JS memuat kata 'pause' di dalam
        # badan JS-nya, jadi memeriksa skrip tidak membuktikan apa pun.
        self.evaluated.append(str(args[0]) if args else "")
        return dict(self._media)

    def bring_to_front(self):
        self.brought_front = True

    def goto(self, url, **_):
        self.url = url


class _FakeContext:
    def __init__(self, pages):
        self.pages = pages
        self.created: list[_FakePage] = []

    def new_page(self):
        page = _FakePage("about:blank", "baru")
        self.pages.append(page)
        self.created.append(page)
        return page


class _FakeBrowser:
    def __init__(self, pages):
        self.contexts = [_FakeContext(pages)]
        self.closed = False

    def close(self):
        self.closed = True


def _wire(monkeypatch, pages=None, *, fail=None):
    """Ganti koneksi CDP dengan browser palsu; tidak ada Chrome sungguhan."""
    def _connect(_port):
        if fail:
            raise fail
        return _FakeBrowser(list(pages or []))

    monkeypatch.setattr(ub, "_connect", _connect)


_YT = {"found": True, "paused": False, "muted": False, "title": "lagu",
       "currentTime": 12.0}


# ── status jujur ──────────────────────────────────────────────────────────

def test_status_reports_attached_when_the_port_answers(monkeypatch):
    _wire(monkeypatch, [_FakePage("https://youtube.com/watch?v=a", "YouTube")])

    status = ub.status()

    assert status["attached"] is True
    assert status["tabs"] == 1


def test_status_explains_a_closed_port_instead_of_pretending(monkeypatch):
    """Yang paling penting di fase ini.

    Melaporkan "tidak ada video" saat sebenarnya Jarvis tidak bisa melihat
    browser user sama sekali adalah klaim palsu — penyakit S-1 lagi.
    """
    _wire(monkeypatch, fail=ConnectionRefusedError("no port"))

    status = ub.status()

    assert status["attached"] is False
    reason = status["reason"].casefold()
    assert "remote-debugging-port" in reason, status["reason"]
    assert str(ub.debug_port()) in status["reason"]


def test_status_never_raises(monkeypatch):
    _wire(monkeypatch, fail=RuntimeError("apa saja"))
    assert ub.status()["attached"] is False


# ── tab milik user ────────────────────────────────────────────────────────

def test_tabs_lists_the_users_real_tabs(monkeypatch):
    _wire(monkeypatch, [
        _FakePage("https://youtube.com/watch?v=a", "Lagu - YouTube"),
        _FakePage("https://mail.google.com", "Gmail"),
        _FakePage("https://maps.google.com", "Maps"),
    ])

    result = ub.list_tabs()

    assert result["ok"] is True
    assert len(result["tabs"]) == 3
    assert result["tabs"][0]["title"] == "Lagu - YouTube"
    assert result["tabs"][1]["url"] == "https://mail.google.com"


def test_tabs_without_a_port_says_why(monkeypatch):
    _wire(monkeypatch, fail=ConnectionRefusedError("no port"))

    result = ub.list_tabs()

    assert result["ok"] is False
    assert "remote-debugging-port" in result["reason"].casefold()
    assert "tabs" not in result or not result.get("tabs")


# ── media di browser user ─────────────────────────────────────────────────

def test_pause_finds_the_playing_tab_among_many(monkeypatch):
    """Inti keluhan Takeda: banyak tab terbuka, satu memutar video."""
    quiet = _FakePage("https://mail.google.com", "Gmail", {"found": False})
    playing = _FakePage("https://youtube.com/watch?v=a", "Lagu - YouTube", _YT)
    _wire(monkeypatch, [quiet, playing])

    result = ub.media("pause")

    assert result["ok"] is True
    assert result["tab"]["title"] == "Lagu - YouTube"
    assert "pause" in playing.evaluated, "tab yang memutar harus dijeda"
    assert "pause" not in quiet.evaluated, (
        "tab lain hanya boleh diperiksa, bukan ikut dijeda")


def test_media_reports_honestly_when_nothing_is_playing(monkeypatch):
    _wire(monkeypatch, [_FakePage("https://mail.google.com", "Gmail",
                                  {"found": False})])

    result = ub.media("pause")

    assert result["ok"] is False
    assert "tidak ada" in result["reason"].casefold()


def test_media_without_a_port_does_not_claim_there_is_no_video(monkeypatch):
    """Pembeda yang menentukan: 'tak terjangkau' ≠ 'tidak ada video'.

    Kedua keadaan harus menghasilkan alasan yang BERBEDA. Menyamakannya
    membuat Jarvis menyatakan fakta tentang browser user yang tidak pernah
    ia lihat — penyakit S-1 lagi.
    """
    _wire(monkeypatch, fail=ConnectionRefusedError("no port"))
    unreachable = ub.media("pause")

    _wire(monkeypatch, [_FakePage("https://mail.google.com", "Gmail",
                                  {"found": False})])
    nothing_playing = ub.media("pause")

    assert unreachable["ok"] is False and nothing_playing["ok"] is False
    assert unreachable["reason"] != nothing_playing["reason"]
    assert "remote-debugging-port" in unreachable["reason"].casefold()
    assert "remote-debugging-port" not in nothing_playing["reason"].casefold()


@pytest.mark.parametrize("action", ["play", "pause", "toggle", "mute",
                                    "unmute", "status"])
def test_supported_actions(monkeypatch, action):
    page = _FakePage("https://youtube.com", "YouTube", _YT)
    _wire(monkeypatch, [page])
    assert ub.media(action)["ok"] is True


def test_unknown_action_is_rejected(monkeypatch):
    _wire(monkeypatch, [_FakePage("https://youtube.com", "YouTube", _YT)])
    assert ub.media("meledak")["ok"] is False


# ── membuka URL di browser user ───────────────────────────────────────────

def test_open_url_creates_a_tab_in_the_users_browser(monkeypatch):
    pages: list = []
    _wire(monkeypatch, pages)

    result = ub.open_url("https://maps.google.com/?q=restoran")

    assert result["ok"] is True
    assert result["url"].startswith("https://maps.google.com")


def test_open_url_rejects_a_non_url(monkeypatch):
    _wire(monkeypatch, [])
    assert ub.open_url("bukan url sama sekali")["ok"] is False


# ── tool terpisah dari browser agent ──────────────────────────────────────

def test_tools_are_registered_and_distinct_from_agent_browser():
    """Dua browser, dua nama tool. Menyamakannya membuat target ambigu."""
    from jarvis.agent import registry

    tools = registry.all_tools()
    for name in ("user_browser_status", "user_browser_tabs",
                 "user_browser_media"):
        assert name in tools, name
    assert "browser_media" in tools, "browser agent tidak boleh hilang"


def test_user_browser_media_tool_surfaces_the_reason(monkeypatch):
    import asyncio

    from jarvis.agent.tools.user_browser import UserBrowserMedia

    monkeypatch.setattr(
        ub, "media",
        lambda *_a, **_k: {"ok": False,
                           "reason": "Chrome tidak dijalankan dengan "
                                     "remote-debugging-port 9222."})

    result = asyncio.run(UserBrowserMedia().run(action="pause"))

    assert result.ok is False
    assert "9222" in str(result.error)
