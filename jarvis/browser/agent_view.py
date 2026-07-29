"""BrowserAgentView — the embedded browser agent inside ContentStage (§6/§7).

A first-class, tabbed browser mounted in the Mark XLIX ContentStage: minimal
vector chrome (back / forward / reload-stop / home / address field with a
security indicator / tab strip / new tab), session persistence, hidden-tab
suspension, scoped keyboard shortcuts, and a live semantic element model
(``jarvis.core.element_model``) harvested from the page DOM.

Follows the exact conventions ContentStage already relies on for
``EmbeddedBrowser``: ``NO_FX = True`` (native compositing — never fade a
WebEngine view) and a ``display_ready(bool)`` signal that fires only when a
real payload is usable. The engine is optional exactly like embed.py's:
without QtWebEngine, ``open()`` reports failure honestly (→ ContentStage
ERROR) and never silently launches an external browser.

For tests, ``view_factory`` injects a stub view — the tab model, chrome,
session, suspension, and element plumbing are all exercised without a
Chromium runtime.
"""
from __future__ import annotations

import json
import time
from collections import deque
from dataclasses import dataclass, field

from PyQt6.QtCore import QRectF, Qt, QUrl, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QPainter, QPainterPath, QPen, QShortcut
from PyQt6.QtWidgets import (QHBoxLayout, QLineEdit, QPushButton,
                             QStackedLayout, QTabBar, QVBoxLayout, QWidget)

from jarvis.browser.embed import available as webengine_available
from jarvis.core import config, log
from jarvis.core.element_model import ScreenElementTree, elements_from_harvest
from jarvis.ui import theme

_logger = log.get("browser.agent_view")

# In-page harvest: interactive elements → JSON for elements_from_harvest().
# Runs entirely inside the page sandbox; reads only — never clicks, types,
# or touches password field VALUES (type is recorded so callers can refuse
# to act on password inputs without explicit user intent).
_HARVEST_JS = """
(function () {
  const sel = 'a,button,input,textarea,select,[role],[contenteditable="true"]';
  const out = [];
  const containerOf = (el) => {
    const c = el.closest('aside,dialog,header,nav,form,main,footer');
    return c ? c.tagName.toLowerCase() : '';
  };
  document.querySelectorAll(sel).forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2) return;
    if (r.bottom < 0 || r.top > innerHeight) return;
    out.push({
      tag: el.tagName.toLowerCase(),
      role: el.getAttribute('role') || '',
      type: el.getAttribute('type') || '',
      name: el.getAttribute('aria-label') || el.getAttribute('name') || '',
      label: (el.labels && el.labels[0]) ? el.labels[0].innerText : '',
      text: (el.innerText || el.value || '').slice(0, 120),
      editable: el.isContentEditable || false,
      disabled: !!el.disabled,
      checked: !!el.checked,
      focused: el === document.activeElement,
      container: containerOf(el),
      visible: true,
      rect: { x: Math.round(r.x), y: Math.round(r.y),
              w: Math.round(r.width), h: Math.round(r.height) },
    });
  });
  return JSON.stringify(out);
})();
"""


def _cfg(key: str, default):
    return config.get(f"ui.browser_agent.{key}", default)


class _ChromeButton(QPushButton):
    """Vector chrome icon — QPainter paths only, no emoji/raster (§7)."""

    def __init__(self, kind: str, tooltip: str, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.setToolTip(tooltip)
        self.setAccessibleName(tooltip)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        px = int(_cfg("chrome.icon_px", 16))
        self.setFixedSize(px + 14, px + 12)
        self.setStyleSheet("QPushButton { background: transparent; border: none; }")

    def set_kind(self, kind: str, tooltip: str) -> None:
        if kind != self.kind:
            self.kind = kind
            self.setToolTip(tooltip)
            self.setAccessibleName(tooltip)
            self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        s = min(self.width(), self.height()) * 0.5
        p.translate((self.width() - s) / 2, (self.height() - s) / 2)
        color = QColor(theme.PAL.accent if (self.underMouse() and self.isEnabled())
                       else theme.PAL.text_dim if self.isEnabled()
                       else theme.qcolor(theme.PAL.text_dim, 110))
        pen = QPen(color, float(_cfg("chrome.stroke_px", 1.6)))
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        path = QPainterPath()
        if self.kind == "back":
            path.moveTo(s * .7, s * .1); path.lineTo(s * .25, s * .5)
            path.lineTo(s * .7, s * .9)
        elif self.kind == "forward":
            path.moveTo(s * .3, s * .1); path.lineTo(s * .75, s * .5)
            path.lineTo(s * .3, s * .9)
        elif self.kind == "reload":
            path.arcMoveTo(QRectF(s * .1, s * .1, s * .8, s * .8), 40)
            path.arcTo(QRectF(s * .1, s * .1, s * .8, s * .8), 40, 280)
            tip = path.currentPosition()
            path.moveTo(tip); path.lineTo(tip.x() + s * .22, tip.y() - s * .06)
            path.moveTo(tip); path.lineTo(tip.x() + s * .04, tip.y() - s * .26)
        elif self.kind == "stop":
            path.addRect(QRectF(s * .2, s * .2, s * .6, s * .6))
        elif self.kind == "home":
            path.moveTo(s * .1, s * .5); path.lineTo(s * .5, s * .12)
            path.lineTo(s * .9, s * .5)
            path.moveTo(s * .22, s * .45); path.lineTo(s * .22, s * .9)
            path.lineTo(s * .78, s * .9); path.lineTo(s * .78, s * .45)
        elif self.kind == "plus":
            path.moveTo(s * .5, s * .12); path.lineTo(s * .5, s * .88)
            path.moveTo(s * .12, s * .5); path.lineTo(s * .88, s * .5)
        p.drawPath(path)


class _SecurityIndicator(QWidget):
    """Site-information indicator: closed vector padlock for https, open
    arc for anything else; tooltip carries the scheme + host."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._secure = False
        self.setFixedSize(20, 20)
        self.setAccessibleName("Site information")
        self.setToolTip("Site information")

    def set_url(self, url: str) -> None:
        self._secure = url.startswith("https://")
        host = url.split("//")[-1].split("/")[0] if "//" in url else url
        self.setToolTip(f"{'Secure — https' if self._secure else 'Not secure'} · {host}")
        self.update()

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(theme.PAL.success if self._secure else theme.PAL.text_dim)
        p.setPen(QPen(color, 1.4))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRect(QRectF(5, 9, 10, 7))
        start = 0 if self._secure else 40   # open shackle when not secure
        p.drawArc(QRectF(6.5, 3, 7, 9), start * 16, (180 - start) * 16)


@dataclass
class _Tab:
    view: QWidget
    url: str = ""
    title: str = "New Tab"
    created: float = field(default_factory=time.time)


class BrowserAgentView(QWidget):
    NO_FX = True                       # native compositing — no opacity fade
    display_ready = pyqtSignal(bool)
    status = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None, view_factory=None,
                 session_path=None):
        super().__init__(parent)
        self._factory = view_factory or self._default_factory
        self._session_path = session_path or config.resolve_path(
            str(_cfg("session_file", "config/browser_session.json")))
        self._tabs: list[_Tab] = []
        self._current = -1
        self._closed: deque[dict] = deque(maxlen=10)
        self._opened_once = False
        self._loading = False
        self.elements = ScreenElementTree()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        chrome_visible = bool(_cfg("chrome.visible", True))
        chrome = QWidget()
        chrome.setFixedHeight(int(_cfg("chrome.height", 40)))
        chrome.setStyleSheet(f"background: {theme.PAL.panel};")
        ch = QHBoxLayout(chrome)
        ch.setContentsMargins(8, 2, 8, 2)
        ch.setSpacing(4)

        self._back = _ChromeButton("back", "Back")
        self._fwd = _ChromeButton("forward", "Forward")
        self._reload = _ChromeButton("reload", "Reload")
        self._home = _ChromeButton("home", "Home")
        self._back.clicked.connect(self.back)
        self._fwd.clicked.connect(self.forward)
        self._reload.clicked.connect(self._reload_or_stop)
        self._home.clicked.connect(self.go_home)
        for b in (self._back, self._fwd, self._reload, self._home):
            ch.addWidget(b)

        self._security = _SecurityIndicator()
        ch.addWidget(self._security)
        self._address = QLineEdit()
        self._address.setPlaceholderText("Search or enter address")
        self._address.setAccessibleName("Address and search field")
        self._address.setFont(theme.mono_font(9))
        self._address.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.base}; color: {theme.PAL.text};"
            f" border: none; border-radius: 4px; padding: 4px 8px; }}")
        self._address.returnPressed.connect(self._address_submitted)
        ch.addWidget(self._address, stretch=1)

        self._tab_bar = QTabBar()
        self._tab_bar.setTabsClosable(True)
        self._tab_bar.setMovable(True)
        self._tab_bar.setExpanding(False)
        self._tab_bar.setAccessibleName("Browser tabs")
        self._tab_bar.setFont(theme.mono_font(8))
        self._tab_bar.setStyleSheet(
            f"QTabBar::tab {{ background: {theme.PAL.base}; color: {theme.PAL.text_dim};"
            f" padding: 3px 10px; margin-right: 2px; }}"
            f"QTabBar::tab:selected {{ color: {theme.PAL.accent};"
            f" border-bottom: 1px solid {theme.PAL.accent}; }}")
        self._tab_bar.currentChanged.connect(self._on_tab_changed)
        self._tab_bar.tabCloseRequested.connect(self.close_tab)
        ch.addWidget(self._tab_bar)
        self._new_tab_btn = _ChromeButton("plus", "New tab")
        self._new_tab_btn.clicked.connect(lambda: self.new_tab())
        ch.addWidget(self._new_tab_btn)

        if chrome_visible:
            root.addWidget(chrome)
        self._stack = QStackedLayout()
        stack_host = QWidget()
        stack_host.setLayout(self._stack)
        root.addWidget(stack_host, stretch=1)

        self._bind_shortcuts()

    # ── engine ────────────────────────────────────────────────────────────

    @staticmethod
    def _default_factory():
        if not webengine_available():
            return None
        from PyQt6.QtWebEngineWidgets import QWebEngineView
        return QWebEngineView()

    def _bind_shortcuts(self) -> None:
        # WidgetWithChildrenShortcut scope: never shadows the global F4/F11/
        # ESC bindings — active only while the browser subtree has focus.
        binds = {
            str(_cfg("shortcuts.focus_address", "Ctrl+L")):
                lambda: (self._address.setFocus(), self._address.selectAll()),
            str(_cfg("shortcuts.new_tab", "Ctrl+T")): lambda: self.new_tab(),
            str(_cfg("shortcuts.close_tab", "Ctrl+W")): self.close_current_tab,
            str(_cfg("shortcuts.reopen_tab", "Ctrl+Shift+T")): self.reopen_last_tab,
            str(_cfg("shortcuts.reload", "Ctrl+R")): self.reload,
            "Alt+Left": self.back,
            "Alt+Right": self.forward,
        }
        for seq, fn in binds.items():
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
            sc.activated.connect(fn)

    # ── open / lifecycle (§6) ─────────────────────────────────────────────

    def open(self, url: str | None = None) -> None:
        """Idempotent entry point for OPEN_BROWSER_AGENT. First call creates
        or restores tabs; later calls reuse the same instance — never a
        duplicate view."""
        if self._tabs:
            if url:
                self.navigate(url)
            else:
                self.status.emit("Browser agent aktif (instance digunakan ulang).")
                self.display_ready.emit(True)
            return
        restored = False
        if not self._opened_once and bool(_cfg("session_restore", True)) and not url:
            restored = self._restore_session()
        self._opened_once = True
        if not restored:
            ok = self.new_tab(url or str(_cfg("home_url", "https://www.google.com")))
            if not ok:
                self.display_ready.emit(False)

    def new_tab(self, url: str | None = None) -> bool:
        limit = int(_cfg("tab_limit", 12))
        if len(self._tabs) >= limit:
            self.status.emit(f"Batas {limit} tab tercapai.")
            return False
        view = self._factory()
        if view is None:
            self.status.emit("QtWebEngine tidak tersedia — browser agent "
                             "tidak dapat dimuat (tanpa fallback eksternal).")
            _logger.error("browser_agent.webengine_unavailable")
            return False
        tab = _Tab(view=view)
        self._tabs.append(tab)
        self._stack.addWidget(view)
        idx = self._tab_bar.addTab(tab.title)
        self._tab_bar.setTabToolTip(idx, tab.title)
        self._connect_view(tab)
        self._select_tab(len(self._tabs) - 1)
        target = url or str(_cfg("home_url", "https://www.google.com"))
        self._load(tab, target)
        self._save_session()
        return True

    def _connect_view(self, tab: _Tab) -> None:
        v = tab.view
        if hasattr(v, "loadStarted"):
            v.loadStarted.connect(lambda t=tab: self._on_load_started(t))
        if hasattr(v, "loadFinished"):
            v.loadFinished.connect(lambda ok, t=tab: self._on_load_finished(t, ok))
        if hasattr(v, "urlChanged"):
            v.urlChanged.connect(lambda u, t=tab: self._on_url_changed(t, u.toString()))
        if hasattr(v, "titleChanged"):
            v.titleChanged.connect(lambda s, t=tab: self._on_title_changed(t, s))

    def _load(self, tab: _Tab, url: str) -> None:
        if not url.lower().startswith(("http://", "https://", "about:", "file:")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                from jarvis.core.router import search_url
                url = search_url(url)
        tab.url = url
        self._loading = True
        if hasattr(tab.view, "load"):
            tab.view.load(QUrl(url))
        if tab is self._current_tab():
            self._address.setText(url)
            self._security.set_url(url)

    # ── navigation surface ────────────────────────────────────────────────

    def navigate(self, url: str) -> None:
        tab = self._current_tab()
        if tab is None:
            self.new_tab(url)
        else:
            self._load(tab, url)

    def back(self) -> None:
        t = self._current_tab()
        if t is not None and hasattr(t.view, "back"):
            t.view.back()

    def forward(self) -> None:
        t = self._current_tab()
        if t is not None and hasattr(t.view, "forward"):
            t.view.forward()

    def reload(self) -> None:
        t = self._current_tab()
        if t is not None and hasattr(t.view, "reload"):
            t.view.reload()

    def stop(self) -> None:
        t = self._current_tab()
        if t is not None and hasattr(t.view, "stop"):
            t.view.stop()
        self._loading = False
        self._reload.set_kind("reload", "Reload")

    def _reload_or_stop(self) -> None:
        self.stop() if self._loading else self.reload()

    def go_home(self) -> None:
        self.navigate(str(_cfg("home_url", "https://www.google.com")))

    def _address_submitted(self) -> None:
        text = self._address.text().strip()
        if text:
            self.navigate(text)

    # ── tabs ──────────────────────────────────────────────────────────────

    def _current_tab(self) -> _Tab | None:
        return self._tabs[self._current] if 0 <= self._current < len(self._tabs) else None

    def _select_tab(self, idx: int) -> None:
        if not (0 <= idx < len(self._tabs)):
            return
        prev = self._current_tab()
        self._current = idx
        if self._tab_bar.currentIndex() != idx:
            self._tab_bar.setCurrentIndex(idx)
        tab = self._tabs[idx]
        self._stack.setCurrentWidget(tab.view)
        self._address.setText(tab.url)
        self._security.set_url(tab.url)
        self.elements.invalidate("tab_change")
        if bool(_cfg("suspend_hidden_tabs", True)):
            self._set_frozen(prev, True)
            self._set_frozen(tab, False)

    def _on_tab_changed(self, idx: int) -> None:
        if idx != self._current:
            self._select_tab(idx)

    def switch_tab(self, delta: int = 1) -> None:
        if self._tabs:
            self._select_tab((self._current + delta) % len(self._tabs))

    def close_tab(self, idx: int) -> None:
        """Tab close is easy-recover (reopen metadata kept) → direct
        execution per the §19 policy; window close stays gated elsewhere."""
        if not (0 <= idx < len(self._tabs)):
            return
        tab = self._tabs.pop(idx)
        self._closed.appendleft({"url": tab.url, "title": tab.title,
                                 "ts": time.time()})
        self._tab_bar.removeTab(idx)
        self._stack.removeWidget(tab.view)
        self._destroy_view(tab.view)
        self.status.emit(f"Tab ditutup: {tab.title[:40]}")
        if not self._tabs:
            self._current = -1
            self.new_tab()          # keep the agent usable, like a browser
        else:
            self._select_tab(min(idx, len(self._tabs) - 1))
        self._save_session()

    def close_current_tab(self) -> None:
        if self._current >= 0:
            self.close_tab(self._current)

    def reopen_last_tab(self) -> None:
        if self._closed:
            item = self._closed.popleft()
            self.new_tab(item["url"])
        else:
            self.status.emit("Tidak ada tab tertutup untuk dibuka kembali.")

    # ── view signal handlers ──────────────────────────────────────────────

    def _on_load_started(self, tab: _Tab) -> None:
        if tab is self._current_tab():
            self._loading = True
            self._reload.set_kind("stop", "Stop loading")
            self.elements.invalidate("navigation")

    def _on_load_finished(self, tab: _Tab, ok: bool) -> None:
        if tab is self._current_tab():
            self._loading = False
            self._reload.set_kind("reload", "Reload")
            self.display_ready.emit(bool(ok))
            self._update_nav_state(tab)
            if ok:
                self.harvest_elements()
        self._save_session()

    def _on_url_changed(self, tab: _Tab, url: str) -> None:
        tab.url = url
        if tab is self._current_tab():
            self._address.setText(url)
            self._security.set_url(url)
            self.elements.invalidate("navigation")

    def _on_title_changed(self, tab: _Tab, title: str) -> None:
        tab.title = title or "New Tab"
        idx = self._tabs.index(tab)
        self._tab_bar.setTabText(idx, tab.title[:24])
        self._tab_bar.setTabToolTip(idx, tab.title)

    def _update_nav_state(self, tab: _Tab) -> None:
        try:
            hist = tab.view.history()
            self._back.setEnabled(hist.canGoBack())
            self._fwd.setEnabled(hist.canGoForward())
        except Exception:
            pass

    # ── element model (§8) ────────────────────────────────────────────────

    def harvest_elements(self, callback=None) -> None:
        """Refresh the semantic element tree from the live DOM. Runs the
        read-only harvest script in the page; without a real page (stub or
        engine-less), reports an empty harvest instead of failing."""
        tab = self._current_tab()
        page = getattr(tab.view, "page", lambda: None)() if tab else None
        page_id = f"tab-{self._current}"

        def _apply(raw_json: str | None) -> None:
            try:
                items = json.loads(raw_json) if raw_json else []
            except (TypeError, ValueError):
                items = []
            tree = ScreenElementTree()
            for el in elements_from_harvest(items, page_id=page_id):
                tree.add(el)
            self.elements = tree
            if callback:
                callback(tree)

        if page is not None and hasattr(page, "runJavaScript"):
            page.runJavaScript(_HARVEST_JS, _apply)
        else:
            _apply(None)

    # ── session persistence ───────────────────────────────────────────────

    def _save_session(self) -> None:
        if not bool(_cfg("session_restore", True)):
            return
        try:
            self._session_path.parent.mkdir(parents=True, exist_ok=True)
            self._session_path.write_text(json.dumps({
                "tabs": [{"url": t.url, "title": t.title} for t in self._tabs],
                "current": self._current, "saved": time.time(),
            }), encoding="utf-8")
        except OSError:
            pass

    def _restore_session(self) -> bool:
        try:
            data = json.loads(self._session_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return False
        tabs = [t for t in data.get("tabs", []) if t.get("url")]
        if not tabs:
            return False
        ok_any = False
        for t in tabs:
            ok_any = self.new_tab(t["url"]) or ok_any
        if ok_any:
            self._select_tab(min(int(data.get("current", 0)), len(self._tabs) - 1))
            self.status.emit(f"Sesi browser dipulihkan ({len(self._tabs)} tab).")
        return ok_any

    # ── suspension + teardown (§6 lifecycle, §24 leaks) ──────────────────

    @staticmethod
    def _set_frozen(tab: _Tab | None, frozen: bool) -> None:
        if tab is None:
            return
        try:
            from PyQt6.QtWebEngineCore import QWebEnginePage
            state = (QWebEnginePage.LifecycleState.Frozen if frozen
                     else QWebEnginePage.LifecycleState.Active)
            tab.view.page().setLifecycleState(state)
        except Exception:
            pass          # stub views / engines without lifecycle support

    def hideEvent(self, e) -> None:
        super().hideEvent(e)
        if bool(_cfg("suspend_hidden_tabs", True)):
            for t in self._tabs:
                self._set_frozen(t, True)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self._set_frozen(self._current_tab(), False)

    def resizeEvent(self, e) -> None:
        super().resizeEvent(e)
        self.elements.invalidate("resize")

    @staticmethod
    def _destroy_view(view: QWidget) -> None:
        try:
            page = getattr(view, "page", lambda: None)()
            if page is not None:
                page.deleteLater()
        except Exception:
            pass
        view.setParent(None)
        view.deleteLater()

    def shutdown(self) -> None:
        """Save session, then destroy every page/view — nothing may leak
        (§24). Safe to call more than once."""
        self._save_session()
        for tab in self._tabs:
            self._stack.removeWidget(tab.view)
            self._destroy_view(tab.view)
        self._tabs.clear()
        self._current = -1
        while self._tab_bar.count():
            self._tab_bar.removeTab(0)
        _logger.info("browser_agent.shutdown")

    # ── introspection ─────────────────────────────────────────────────────

    def current_url(self) -> str:
        t = self._current_tab()
        return t.url if t else ""

    def tab_count(self) -> int:
        return len(self._tabs)

    def focus_content(self) -> None:
        t = self._current_tab()
        if t is not None:
            t.view.setFocus()
