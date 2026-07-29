"""Embedded browser view for the ContentStage (Part 3.2).

QtWebEngine (installed, real Chromium) hosts the page inside the stage — the
page appears immediately; extraction + summarization happen afterwards, off
the UI thread. If QtWebEngine is unavailable the module degrades to opening
the system browser and fetching content directly for summarization.

The summarization contract (spec constraint): ``summarize_page`` accepts only
content that came from this browser module — chat traffic never routes here.
"""
from __future__ import annotations

import threading
from typing import Callable

from PyQt6.QtCore import QTimer, QUrl, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout

from jarvis.core import config, llm, log
from jarvis.core.bus import BUS
from jarvis.browser.extract import extract_main_content, fetch_and_extract

_logger = log.get("browser")

try:
    from PyQt6.QtWebEngineWidgets import QWebEngineView
    _HAS_WEBENGINE = True
except ImportError:
    QWebEngineView = None
    _HAS_WEBENGINE = False


def available() -> bool:
    return _HAS_WEBENGINE


class EmbeddedBrowser(QWidget):
    """Stage child hosting a live Chromium view.

    content_ready(str) fires with extracted main text once the DOM settles.
    """
    content_ready = pyqtSignal(str, str)          # (text, url)
    display_ready = pyqtSignal(bool)              # real page payload is mounted
    NO_FX = True          # native compositing — ContentStage must not fade it

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._settle_ms = int(config.get("browser.dom_ready_extra_ms", 1200))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._view = None
        self._pending_extract = False
        if _HAS_WEBENGINE:
            self._view = QWebEngineView(self)
            lay.addWidget(self._view)
            if bool(config.get("browser.video.autoplay", True)):
                try:
                    from PyQt6.QtWebEngineCore import QWebEngineSettings
                    self._view.settings().setAttribute(
                        QWebEngineSettings.WebAttribute.PlaybackRequiresUserGesture,
                        False)
                except Exception:
                    _logger.warning("browser.autoplay_flag_unavailable")
            self._view.loadFinished.connect(self._on_load_finished)
            self._view.urlChanged.connect(
                lambda u: BUS.publish("browser.nav", url=u.toString(), title=""))

    # ── navigation ───────────────────────────────────────────────────────────

    def navigate(self, url: str, extract: bool = True) -> None:
        self._pending_extract = extract
        _logger.info("browser.navigate", url=url)
        if self._view is not None:
            self._view.setUrl(QUrl(url))
            return
        # degraded: system browser for display, direct fetch for content
        import webbrowser
        webbrowser.open(url)
        if extract:
            threading.Thread(
                target=lambda: self.content_ready.emit(fetch_and_extract(url), url),
                daemon=True, name="browser-fetch").start()

    def play_embed(self, embed_url: str) -> None:
        """Mark L Change 6: video path. YouTube embeds refuse top-level loads
        without a referer (Error 153) — wrap in an iframe with a proper
        baseUrl so the player initializes and autoplays."""
        if self._view is None:
            self.navigate(embed_url, extract=False)
            return
        self._pending_extract = False
        html = (
            '<!doctype html><html><body style="margin:0;background:#000">'
            f'<iframe src="{embed_url}" '
            'style="position:fixed;inset:0;width:100%;height:100%;border:0" '
            'allow="autoplay; encrypted-media; fullscreen" allowfullscreen>'
            '</iframe></body></html>')
        _logger.info("browser.play_embed", url=embed_url)
        base = str(config.get("browser.video.embed_referer",
                              "https://embed.jarvis.local/"))
        self._view.setHtml(html, QUrl(base))

    def current_url(self) -> str:
        return self._view.url().toString() if self._view is not None else ""

    # ── extraction ───────────────────────────────────────────────────────────

    def _on_load_finished(self, ok: bool) -> None:
        self.display_ready.emit(ok)
        if not self._pending_extract:
            return
        self._pending_extract = False
        if not ok:
            # page refused the embedded engine — fetch directly so the
            # summary still arrives while the view shows whatever loaded
            url = self.current_url()
            _logger.warning("browser.load_failed_fallback_fetch", url=url)
            threading.Thread(
                target=lambda: self.content_ready.emit(
                    fetch_and_extract(url), url),
                daemon=True, name="browser-fallback-fetch").start()
            return
        # let SPA/JS content settle before pulling the DOM
        QTimer.singleShot(self._settle_ms, self._pull_html)

    def _pull_html(self) -> None:
        if self._view is None:
            return
        url = self.current_url()
        self._view.page().toHtml(
            lambda html: threading.Thread(
                target=self._extract_off_thread, args=(html, url),
                daemon=True, name="browser-extract").start())

    def _extract_off_thread(self, html: str, url: str) -> None:
        text = extract_main_content(html, url)
        _logger.info("browser.extracted", url=url, chars=len(text))
        self.content_ready.emit(text, url)


# ── summarization module (browser-sourced content ONLY) ──────────────────────

def summarize_page(page_text: str, query: str, source_url: str) -> None:
    """Stream an Indonesian summary of *browser-sourced* page text.

    Chunks are published on ``summary.chunk``; the final event carries
    done=True. This module must never be fed chat responses.
    """
    if not page_text.strip():
        BUS.publish("summary.chunk", text="Halaman tidak memuat konten yang "
                    "dapat diringkas.", done=True, source_url=source_url)
        return

    system = config.get("summarizer.system_prompt", "")
    prompt = (
        f"Kueri pengguna: {query}\n\n"
        f"URL sumber: {source_url}\n\n"
        f"Konten halaman:\n{page_text}"
    )

    def _run():
        got_any = False
        try:
            for chunk in llm.stream(prompt, system=system):
                got_any = True
                BUS.publish("summary.chunk", text=chunk, done=False,
                            source_url=source_url)
        finally:
            if not got_any:
                BUS.publish("summary.chunk",
                            text="Modul ringkasan tidak tersedia saat ini.",
                            done=False, source_url=source_url)
            BUS.publish("summary.chunk", text="", done=True,
                        source_url=source_url)
            _logger.info("summary.done", source_url=source_url)

    threading.Thread(target=_run, daemon=True, name="summarize").start()
