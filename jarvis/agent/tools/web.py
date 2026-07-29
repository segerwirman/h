"""Web search & extract (§3.1.E) — ddgs + trafilatura, rate limit + retry.

MK50 §6: region/bahasa disuntikkan dari ``jarvis.core.locale`` (config →
bahasa perintah/Silent Language Memory → fallback id-ID) — tidak pernah
hardcode region di sini.
"""
from __future__ import annotations

import asyncio
import threading
import time

from pydantic import BaseModel, Field

from jarvis.core import locale as jlocale
from jarvis.core import log
from jarvis.agent.base import Tool, ToolResult

_logger = log.get("agent.tools.web")

_rate_lock = threading.Lock()
_last_search = 0.0
_MIN_INTERVAL_S = 1.2                       # DDG suka throttle — beri jeda


def _throttle() -> None:
    global _last_search
    with _rate_lock:
        wait = _MIN_INTERVAL_S - (time.monotonic() - _last_search)
        if wait > 0:
            time.sleep(wait)
        _last_search = time.monotonic()


class _SearchParams(BaseModel):
    query: str = Field(description="Kueri pencarian")
    max_results: int = Field(6, description="Jumlah hasil (maks 15)")
    mode: str = Field("text", description="text | news")


class WebSearch(Tool):
    name = "web_search"
    description = ("Cari web (DuckDuckGo, tanpa API key). Kembalikan judul, "
                   "URL, dan snippet. mode=news untuk berita terbaru.")
    params_schema = _SearchParams
    read_only = True
    timeout_s = 45

    async def run(self, query: str, max_results: int = 6,
                  mode: str = "text", **_) -> ToolResult:
        max_results = min(int(max_results or 6), 15)

        # §6 — locale per permintaan: region ddgs + augmentasi query berita
        # generik ("berita terbaru hari ini" → konteks lokal). Query spesifik
        # tidak diubah; penargetan cukup lewat region.
        loc = jlocale.resolve(query)
        region = jlocale.ddg_region(loc=loc)
        effective_query = jlocale.news_query(query, loc) \
            if mode == "news" else query
        if effective_query != query:
            _logger.info("web_search.localized", region=region,
                         query=effective_query)

        def _search():
            from ddgs import DDGS
            delay = 1.0
            last_err = None
            for attempt in range(3):
                _throttle()
                try:
                    with DDGS() as ddgs:
                        if mode == "news":
                            return list(ddgs.news(effective_query,
                                                  region=region,
                                                  max_results=max_results))
                        return list(ddgs.text(effective_query,
                                              region=region,
                                              max_results=max_results))
                except Exception as e:                       # noqa: BLE001
                    last_err = e
                    _logger.warning("web_search.retry", attempt=attempt + 1,
                                    error=str(e)[:100])
                    time.sleep(delay)
                    delay *= 2
            raise last_err or RuntimeError("search gagal")

        try:
            rows = await asyncio.to_thread(_search)
        except Exception as e:                               # noqa: BLE001
            return ToolResult.fail(f"pencarian gagal: {str(e)[:150]}")
        if not rows:
            return ToolResult.success("tidak ada hasil", display="0 hasil")
        # §7.2 — berita dan hasil pencarian sama-sama menjadi kartu info.
        # Publikasi best-effort dan tidak pernah menggagalkan hasil tool.
        try:
            from jarvis.core.bus import BUS
            if mode == "news":
                card_lines = [
                    f"{r.get('title', '')}  "
                    f"[{r.get('source', '')} {r.get('date', '')}]".strip()
                    for r in rows[:6] if r.get("title")]
                source = "DuckDuckGo News"
            else:
                card_lines = [
                    f"{r.get('title', '')} — "
                    f"{r.get('href') or r.get('url', '')}".strip(" —")
                    for r in rows[:6] if r.get("title")]
                source = "DuckDuckGo Search"
            if card_lines:
                BUS.publish("info.card",
                            kind="news" if mode == "news" else "search",
                            title=effective_query, lines=card_lines,
                            source=source, ts="")
        except Exception as e:                               # noqa: BLE001
            _logger.warning("web_search.info_card_failed", error=str(e)[:80])
        lines = []
        for r in rows:
            title = r.get("title", "")
            url = r.get("href") or r.get("url", "")
            body = (r.get("body") or r.get("excerpt", ""))[:280]
            src = r.get("source", "")
            date = r.get("date", "")
            head = f"• {title} — {url}"
            if src or date:
                head += f"  ({src} {date})".rstrip()
            lines.append(f"{head}\n  {body}")
        return ToolResult.success("\n".join(lines),
                                  display=f"{len(rows)} hasil")


class _ExtractParams(BaseModel):
    url: str = Field(description="URL halaman")
    mode: str = Field("markdown", description="text | markdown")
    max_chars: int = Field(16000, description="Batas panjang hasil")


class WebExtract(Tool):
    name = "web_extract"
    description = ("Unduh halaman dan ekstrak konten utamanya (artikel) — "
                   "trafilatura; fallback teks mentah. Untuk halaman "
                   "JS-heavy gunakan browser_navigate + browser_snapshot.")
    params_schema = _ExtractParams
    read_only = True
    timeout_s = 60

    async def run(self, url: str, mode: str = "markdown",
                  max_chars: int = 16000, **_) -> ToolResult:
        def _extract():
            import trafilatura
            downloaded = trafilatura.fetch_url(url)
            if not downloaded:
                import requests
                # §6 — situs multi-bahasa menghormati Accept-Language.
                resp = requests.get(url, timeout=25, headers={
                    "User-Agent": "Mozilla/5.0 (JarvisAgent)",
                    "Accept-Language": jlocale.accept_language()})
                resp.raise_for_status()
                downloaded = resp.text
            out = trafilatura.extract(
                downloaded,
                output_format="markdown" if mode == "markdown" else "txt",
                include_links=False, include_comments=False)
            if not out:
                from bs4 import BeautifulSoup
                soup = BeautifulSoup(downloaded, "html.parser")
                for t in soup(["script", "style", "noscript"]):
                    t.decompose()
                out = " ".join(soup.get_text(" ").split())
            return out or ""

        try:
            text = await asyncio.to_thread(_extract)
        except Exception as e:                               # noqa: BLE001
            return ToolResult.fail(f"ekstraksi gagal: {str(e)[:150]}")
        if not text:
            return ToolResult.fail("halaman tidak menghasilkan konten — "
                                   "coba jalur browser")
        text = text[:max(1000, int(max_chars))]
        return ToolResult.success(text, display=f"{len(text)} karakter",
                                  url=url)
