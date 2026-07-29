"""Main-content extraction from browser-sourced HTML (Part 3.2).

trafilatura preferred, readability-lxml fallback, crude tag-strip last resort.
Runs off the UI thread — extraction can take hundreds of ms on big pages.
"""
from __future__ import annotations

import re

from jarvis.core import config, log

_logger = log.get("browser.extract")

try:
    import trafilatura
    _HAS_TRAFILATURA = True
except ImportError:
    trafilatura = None
    _HAS_TRAFILATURA = False

try:
    from readability import Document as _ReadabilityDoc
    _HAS_READABILITY = True
except ImportError:
    _ReadabilityDoc = None
    _HAS_READABILITY = False

_TAG_RE = re.compile(r"<(script|style|nav|header|footer|aside)[^>]*>.*?</\1>",
                     re.IGNORECASE | re.DOTALL)
_ANY_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def extract_main_content(html: str, url: str = "") -> str:
    """Return the readable main text of an HTML document ('' if none)."""
    max_chars = int(config.get("browser.extract_max_chars", 18000))

    if _HAS_TRAFILATURA:
        try:
            text = trafilatura.extract(
                html, url=url or None, include_comments=False,
                include_tables=True, favor_recall=True)
            if text and text.strip():
                return text.strip()[:max_chars]
        except Exception as e:
            _logger.warning("extract.trafilatura_failed", error=str(e)[:120])

    if _HAS_READABILITY:
        try:
            doc = _ReadabilityDoc(html)
            body = _ANY_TAG_RE.sub(" ", doc.summary())
            body = _WS_RE.sub(" ", body).strip()
            if body:
                return body[:max_chars]
        except Exception as e:
            _logger.warning("extract.readability_failed", error=str(e)[:120])

    # last resort: strip tags
    body = _TAG_RE.sub(" ", html)
    body = _ANY_TAG_RE.sub(" ", body)
    return _WS_RE.sub(" ", body).strip()[:max_chars]


def fetch_and_extract(url: str) -> str:
    """Direct fetch + extract (used when no embedded browser is available)."""
    if _HAS_TRAFILATURA:
        try:
            downloaded = trafilatura.fetch_url(url)
            if downloaded:
                return extract_main_content(downloaded, url)
        except Exception as e:
            _logger.warning("extract.fetch_failed", url=url, error=str(e)[:120])
    try:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            return extract_main_content(
                resp.read().decode("utf-8", errors="replace"), url)
    except Exception as e:
        _logger.error("extract.urllib_failed", url=url, error=str(e)[:120])
        return ""
