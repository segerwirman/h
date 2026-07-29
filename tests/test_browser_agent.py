"""Embedded Browser Agent — intent routing, lifecycle, ContentStage
integration (§6/§7/§26 tests 14-18, 30).

QtWebEngine cannot initialize in this environment (pre-existing, unrelated
to this repo — see tests/test_window_integration.py's module docstring), so
BrowserAgentView is exercised through its injectable ``view_factory`` with
stub views. The tab model, chrome state, session persistence, suspension
hooks, element plumbing, and all MainWindow wiring are real.
"""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from jarvis.core.router import Intent, IntentRouter
from jarvis.ui.stage import ContentStatus

_APP_REF = None


def _app():
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


class StubView(QWidget):
    loadStarted = pyqtSignal()
    loadFinished = pyqtSignal(bool)
    urlChanged = pyqtSignal(QUrl)
    titleChanged = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.loaded: list[str] = []
        self.nav_calls: list[str] = []

    def load(self, qurl: QUrl):
        self.loaded.append(qurl.toString())

    def url(self):
        return QUrl(self.loaded[-1] if self.loaded else "")

    def back(self): self.nav_calls.append("back")
    def forward(self): self.nav_calls.append("forward")
    def reload(self): self.nav_calls.append("reload")
    def stop(self): self.nav_calls.append("stop")


def _make_view(tmp_path, **kwargs):
    _app()
    from jarvis.browser.agent_view import BrowserAgentView
    created: list[StubView] = []

    def factory():
        v = StubView()
        created.append(v)
        return v

    view = BrowserAgentView(view_factory=kwargs.pop("view_factory", factory),
                            session_path=tmp_path / "session.json", **kwargs)
    return view, created


# ── intent routing (§26 tests 14-15) ─────────────────────────────────────

# MK50 §7: test mount panel dihapus — open_browser_agent kini membuka
# browser sistem (lihat test_browser_routing_p0).
def test_open_browser_agent_english_and_indonesian_share_one_intent():
    r = IntentRouter()
    phrases = ("open browser agent", "open the browser agent",
               "launch browser agent", "start browser agent",
               "show browser agent", "buka browser agent",
               "tolong buka browser agent", "buka agen browser",
               "open default browser", "buka browser bawaan")
    for p in phrases:
        c = r.classify(p)
        assert c.intent is Intent.OPEN_BROWSER_AGENT, p
        assert c.slots.get("external") is False, p


def test_explicit_external_browser_phrase_sets_external_flag():
    r = IntentRouter()
    c = r.classify("open browser agent in external browser")
    assert c.intent is Intent.OPEN_BROWSER_AGENT
    assert c.slots["external"] is True
    c = r.classify("buka browser agent di browser eksternal")
    assert c.slots["external"] is True


def test_unrelated_open_commands_do_not_hit_browser_agent_intent():
    r = IntentRouter()
    assert r.classify("buka youtube").intent is Intent.OPEN_URL
    assert r.classify("buka spotify").intent is Intent.OPEN_APP


# ── view lifecycle ────────────────────────────────────────────────────────

def test_open_creates_single_tab_and_repeated_open_reuses(tmp_path):
    view, created = _make_view(tmp_path)
    view.open()
    assert view.tab_count() == 1
    assert len(created) == 1
    ready = []
    view.display_ready.connect(ready.append)
    view.open()                    # §26 test 16 — reuse, never a duplicate
    assert view.tab_count() == 1
    assert len(created) == 1
    assert ready == [True]         # instant readiness on reuse
    view.shutdown()


def test_open_without_engine_reports_failure_never_external(tmp_path, monkeypatch):
    launched = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url: launched.append(url))
    view, _ = _make_view(tmp_path, view_factory=lambda: None)
    ready = []
    view.display_ready.connect(ready.append)
    view.open()
    assert ready == [False]
    assert launched == []          # §26 test 18 — no silent external fallback
    view.shutdown()


def test_navigation_surface_reaches_current_view(tmp_path):
    view, created = _make_view(tmp_path)
    view.open("https://example.com")
    stub = created[0]
    assert stub.loaded[-1] == "https://example.com"
    view.back(); view.forward(); view.reload()
    assert stub.nav_calls == ["back", "forward", "reload"]
    view.navigate("plain search words")
    assert "bing.com" in stub.loaded[-1] or "duckduckgo" in stub.loaded[-1]
    view.shutdown()


def test_tab_limit_close_and_reopen(tmp_path):
    view, created = _make_view(tmp_path)
    view.open("https://a.example")
    view.new_tab("https://b.example")
    assert view.tab_count() == 2
    view.close_tab(1)
    assert view.tab_count() == 1
    view.reopen_last_tab()
    assert view.tab_count() == 2
    assert created[-1].loaded[-1] == "https://b.example"
    view.shutdown()


def test_session_saved_and_restored(tmp_path):
    view, _ = _make_view(tmp_path)
    view.open("https://a.example")
    view.new_tab("https://b.example")
    view.shutdown()
    data = json.loads((tmp_path / "session.json").read_text(encoding="utf-8"))
    assert [t["url"] for t in data["tabs"]] == ["https://a.example",
                                                "https://b.example"]
    view2, created2 = _make_view(tmp_path)
    view2.open()
    assert view2.tab_count() == 2      # restored, not the home page
    assert {v.loaded[-1] for v in created2} == {"https://a.example",
                                                "https://b.example"}
    view2.shutdown()


def test_shutdown_leaves_no_tabs_or_views(tmp_path):
    view, _ = _make_view(tmp_path)
    view.open()
    view.new_tab()
    view.shutdown()
    assert view.tab_count() == 0        # §26 test 30
    assert view._tab_bar.count() == 0
    view.shutdown()                     # idempotent


def test_element_tree_invalidated_on_navigation_and_tab_change(tmp_path):
    from jarvis.core.element_model import ElementScope, UIElement
    view, created = _make_view(tmp_path)
    view.open("https://a.example")
    view.elements.add(UIElement(element_id="x", scope=ElementScope.PAGE_MAIN,
                                role="button", confidence=0.9))
    assert view.elements.actionable("x") is not None
    created[0].loadStarted.emit()       # navigation begins → stale
    assert view.elements.actionable("x") is None
    view.shutdown()


def test_harvest_without_real_page_yields_empty_tree(tmp_path):
    view, _ = _make_view(tmp_path)
    view.open()
    results = []
    view.harvest_elements(callback=results.append)
    assert len(results) == 1
    assert results[0].scopes() == []
    view.shutdown()


# ── MainWindow integration (§26 tests 17-18 + docking) ────────────────────

@pytest.fixture()
def win(monkeypatch, tmp_path):
    _app()

    class _StubBrowser(QWidget):
        content_ready = pyqtSignal(str, str)
        display_ready = pyqtSignal(bool)
        NO_FX = True

        def navigate(self, url, extract=True): pass
        def play_embed(self, url): pass
        def current_url(self): return ""

    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    from jarvis.ui.window import MainWindow
    w = MainWindow(services={})
    w._stub_views = []

    def factory():
        v = StubView()
        w._stub_views.append(v)
        return v

    w._browser_agent_factory = factory
    yield w
    if w._browser_agent is not None:
        w._browser_agent.shutdown()


def test_explicit_external_phrase_opens_os_browser_only_then(win, monkeypatch):
    launched = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda url: launched.append(url))
    win.handle_command("open browser agent in external browser")
    assert len(launched) == 1
    assert win._browser_agent is None                    # embedded untouched
