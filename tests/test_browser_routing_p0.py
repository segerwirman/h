"""P0 browser-routing regression suite — MK50 §7.

Kontrak baru: panel browser/Tabbit dibuang dari ContentStage. Perintah
URL/pencarian ringan (voice DAN typed) membuka browser SISTEM lewat
``webbrowser.open``; alur web bertujuan berjalan di agent (browser_* tools).
Kebijakan skema URL tetap: skema di luar allowlist tidak pernah dibuka.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtWidgets import QApplication

from jarvis.core.focus_mode import FocusMode
from jarvis.core.router import Intent, IntentRouter
from jarvis.ui.stage import ContentStatus

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


@pytest.fixture()
def router():
    return IntentRouter()


@pytest.fixture()
def win():
    _app()
    FocusMode._reset_for_tests()
    from jarvis.ui.window import MainWindow
    w = MainWindow(services={})
    yield w
    FocusMode._reset_for_tests()


@pytest.fixture()
def opened(monkeypatch):
    """Tangkap pembukaan URL eksternal — tidak pernah membuka browser nyata.

    ``MainWindow.open_url`` memakai ``jarvis.core.native_actions.
    open_external_url``, dan di Windows fungsi itu memanggil ``os.startfile``,
    BUKAN ``webbrowser.open``. Menambal ``webbrowser.open`` saja karena itu
    tidak menangkap apa pun — dan lebih buruk, membuat suite benar-benar
    meluncurkan browser default. Terverifikasi 2026-08-04:
    ``os.startfile('https://example.com')`` sungguh terpanggil saat test jalan.

    Tiga lapis ditambal sekaligus supaya tidak ada jalur yang lolos di
    platform mana pun.
    """
    import webbrowser

    from jarvis.core import native_actions

    urls: list[str] = []

    def _capture(url, *a, **k):
        urls.append(url)
        return native_actions.NativeActionResult(True, "test-capture")

    monkeypatch.setattr(native_actions, "open_external_url", _capture)
    monkeypatch.setattr(webbrowser, "open", lambda url, **k: urls.append(url))
    monkeypatch.setattr(os, "startfile", lambda t, *a, **k: urls.append(t),
                        raising=False)
    return urls


# ── klasifikasi intent (tidak berubah oleh §7) ──────────────────────────────

@pytest.mark.parametrize("phrase", [
    "open browser", "buka browser", "show browser", "launch browser",
    "tampilkan browser", "buka browser agent", "open browser agent",
    "buka peramban",
])
def test_open_browser_phrases_still_one_intent(router, phrase):
    c = router.classify(phrase)
    assert c.intent is Intent.OPEN_BROWSER_AGENT, phrase


def test_open_browser_never_reaches_app_launcher(router):
    for phrase in ("buka browser", "open browser"):
        c = router.classify(phrase)
        assert c.intent is not Intent.OPEN_APP, phrase


def test_named_app_still_routes_to_app_launcher(router):
    c = router.classify("buka spotify")
    assert c.intent is Intent.OPEN_APP


def test_pasted_url_classifies_open_url(router):
    c = router.classify("buka https://example.com/path?q=1")
    assert c.intent is Intent.OPEN_URL
    assert c.slots["url"] == "https://example.com/path?q=1"


def test_search_query_classifies_search_web(router):
    c = router.classify("cari tutorial python")
    assert c.intent is Intent.SEARCH_WEB
    assert c.slots["query"] == "tutorial python"


# ── §7: panel browser tidak lagi terdaftar di ContentStage ──────────────────

def test_stage_has_no_browser_panels(win):
    assert win.stage.widget("browser") is None
    assert win.stage.widget("browser_agent") is None
    assert win.browser is None


def test_stage_registers_vision_info_home(win):
    # "tasks" ditambahkan AUDIT §8.5 (Task Deck); "studio" oleh Content Studio
    # (Studio A-D). Kontrak intinya tetap: tidak ada panel browser di
    # ContentStage — dijaga tes di atas.
    assert win.stage.registered_names == frozenset(
        {"vision", "info", "home", "tasks", "studio"})


def test_home_click_uses_loading_until_panel_ready(win, monkeypatch):
    monkeypatch.setattr(win.home_panel, "refresh", lambda: None)
    win._toggle_home_panel()
    assert win.stage.status is ContentStatus.LOADING
    assert win.stage.is_loading("home")
    win.home_panel.ready.emit()
    assert win.stage.current == "home"
    assert win.stage.status is ContentStatus.ACTIVE


def test_legacy_show_content_is_an_info_card(win):
    before = win.info_panel.card_count
    win._show_content("Hasil", "baris satu\nbaris dua")
    assert win.stage.current == "info"
    assert win.info_panel.card_count == before + 1


# ── kebijakan skema URL tetap ditegakkan ────────────────────────────────────

def test_open_url_rejects_disallowed_schemes(win, opened):
    for bad in ("file:///C:/windows/system32", "javascript:alert(1)",
                "data:text/html,<b>x</b>", "ftp://host/x"):
        win.open_url(bad)
        assert opened == [], bad


def test_open_url_allows_https_and_normalizes_bare_domain(win, opened):
    win.open_url("example.com")
    assert opened[-1] == "https://example.com"
    win.open_url("https://example.org")
    assert opened[-1] == "https://example.org"


def test_open_url_host_port_is_not_treated_as_scheme(win, opened):
    win.open_url("localhost:8080/dash")
    assert opened[-1] == "https://localhost:8080/dash"


# ── voice & typed berbagi satu jalur: browser sistem ────────────────────────

def test_voice_url_command_opens_system_browser(win, opened):
    win._voice_intercept("buka example.com")
    assert opened and opened[-1].startswith("https://example.com")


def test_voice_search_no_longer_dumps_the_query_into_the_browser(win, opened):
    """§23 — kontrak lama DICABUT dengan sengaja.

    Test ini dulu mengunci "pencarian suara membuka browser sistem dengan
    kuerinya". Di lapangan itu berarti transkrip mentah Takeda muncul sebagai
    hasil pencarian Google:

        'kan saya restoran yang - Search - Google Chrome'

    Yang tampil di layar adalah kalimatnya sendiri, bukan jawaban. Pencarian
    kini dijalankan lewat tool `web_search` yang menghasilkan sumber nyata
    (web, media sosial, peta), lalu sumber itu yang ditawarkan.

    Yang TIDAK berubah dan tetap dikunci di bawah: membuka URL yang jelas
    ("buka example.com") tetap lewat browser sistem — di sana tidak ada
    transkrip yang dipantulkan, hanya alamat yang user sebut sendiri.
    """
    # Jalur pencarian nyata menjalankan tool `web_search` di thread — jaringan
    # sungguhan, dan sentuhan Qt setelah window dibongkar. Yang diuji di sini
    # adalah ROUTING-nya, jadi pekerjaannya ditambal.
    routed: list[tuple] = []
    win._run_web_lookup = lambda query, *, mode, label: routed.append(
        (query, mode))

    win._voice_intercept("cari berita teknologi hari ini")

    assert not opened, (
        "pencarian tidak boleh lagi meluncurkan browser dengan kueri mentah")
    assert routed, "pencarian tetap harus dijalankan, hanya lewat jalur sumber"


def test_typed_and_voice_url_take_identical_route(win, opened):
    win.handle_command("buka example.com")
    typed = list(opened)
    opened.clear()
    win._voice_intercept("buka example.com")
    assert opened == typed


def test_open_browser_agent_opens_system_browser(win, opened):
    win.open_browser_agent({})
    assert len(opened) == 1
    win.open_browser_agent({"url": "https://example.com"})
    assert opened[-1] == "https://example.com"
    # tidak ada view/panel yang dimount
    assert win._browser_agent is None
    assert win.stage.widget("browser_agent") is None
