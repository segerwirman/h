"""Web search & extract (§3.1.E) — ddgs + trafilatura, rate limit + retry.

MK50 §6: region/bahasa disuntikkan dari ``jarvis.core.locale`` (config →
bahasa perintah/Silent Language Memory → fallback id-ID) — tidak pernah
hardcode region di sini.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time

from pydantic import BaseModel, Field

from jarvis.core import config, locale as jlocale
from jarvis.core import log
from jarvis.agent.base import Tool, ToolResult

_logger = log.get("agent.tools.web")

# §18 — kapan sumber pencarian dibuka di browser agent.
OPEN_SOURCE_MODES = ("always", "on_request", "never")
# Kata yang SELALU berarti "tunjukkan sumbernya": berimbuhan pemilik, atau
# kata kerja meminta yang berdiri sendiri.
_SOURCE_REQUEST_RE = re.compile(
    r"\b(?:sumber(?:-sumber)?nya|source[sd]?\b|referensi|reference|"
    r"bukti(?:kan)?(?:nya)?|tunjukkan|tunjukin|perlihatkan|"
    r"link(?:nya)|tautan(?:nya))\b",
    re.IGNORECASE,
)
# "sumber"/"link" telanjang ambigu: bisa TOPIK ("apa sumber energi terbarukan",
# "cari link aja deh") dan membuka tab untuk itu merebut layar user. Baru
# dihitung permintaan bila didahului kata kerja meminta.
_SOURCE_VERB_RE = re.compile(
    r"\b(?:tunjukkan|tunjukin|perlihatkan|tampilkan|sebutkan|cantumkan|"
    r"sertakan|beri(?:kan)?|kasih|buka(?:kan)?|lampirkan|show|give|include|"
    r"cite)\b[^.?!]{0,40}?\b(?:sumber|source|link|tautan|halaman)\b",
    re.IGNORECASE,
)


def _open_sources_mode() -> str:
    """Mode pembukaan sumber; nilai tak dikenal jatuh ke ``on_request``."""
    try:
        value = config.get("agent.search.open_sources", "on_request")
    except Exception:                                        # noqa: BLE001
        return "on_request"
    value = str(value or "").strip().casefold()
    return value if value in OPEN_SOURCE_MODES else "on_request"


def _wants_sources(mode: str, task: str, query: str) -> bool:
    if mode == "never":
        return False
    if mode == "always":
        return True
    text = f"{task} {query}"
    return bool(_SOURCE_REQUEST_RE.search(text)
                or _SOURCE_VERB_RE.search(text))


def _top_source_url(rows: list[dict]) -> str:
    for row in rows:
        url = str(row.get("href") or row.get("url") or "").strip()
        if url.lower().startswith(("http://", "https://")):
            return url
    return ""


async def _open_top_source(rows: list[dict], session, adapter, context,
                           query: str) -> None:
    """Buka SATU tab ke sumber peringkat teratas; best-effort.

    Satu tab per pencarian, bukan satu per hasil — membuka enam tab tiap kali
    Takeda bertanya akan merebut layarnya. Memakai panel browser agent (lewat
    registry, bukan memanggil internal browser) supaya lease, lifecycle, dan
    pelepasannya tetap ditangani jalur yang sudah ada.
    """
    url = _top_source_url(rows)
    if not url or session is None:
        return
    try:
        from jarvis.agent import registry

        await registry.execute("browser_new_tab", {"url": url},
                               adapter, session, context)
        _logger.info("web_search.source_opened", query=query[:80])
    except Exception as e:                                   # noqa: BLE001
        # Membuka sumber adalah bonus. Kegagalannya tidak boleh menggagalkan
        # hasil pencarian yang sudah benar.
        _logger.warning("web_search.source_open_failed", error=str(e)[:120])

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
    wants_context = True
    timeout_s = 45

    async def run(self, query: str, max_results: int = 6,
                  mode: str = "text", _session=None, _adapter=None,
                  _context=None, **_) -> ToolResult:
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
                # §18 — bentuk lama membuang href sepenuhnya di mode news,
                # sehingga sumbernya tidak terlihat bahkan sebagai teks.
                card_lines = [
                    (f"{r.get('title', '')} — "
                     f"{r.get('href') or r.get('url', '')}".rstrip(" —")
                     + f"  [{r.get('source', '')} {r.get('date', '')}]".rstrip())
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
        # §18 — tampilkan sumbernya, bukan hanya menyebutkannya.
        task = str(getattr(_session, "task", "") or "")
        if _wants_sources(_open_sources_mode(), task, query):
            await _open_top_source(rows, _session, _adapter, _context, query)
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
