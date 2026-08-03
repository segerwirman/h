"""Phase 17A: public read-only source fetcher, no browser/login/cookies."""
from __future__ import annotations

import json
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from urllib.parse import urljoin

_MAX_TITLE = 200


def _http_get(url: str, timeout: int) -> bytes:
    import requests
    response = requests.get(url, timeout=timeout, headers={"User-Agent": "JarvisMonitor/1.0"})
    response.raise_for_status()
    return bytes(response.content)


def _item(title: str, url: str, published: str = "") -> dict:
    return {"title": str(title or "").strip()[:_MAX_TITLE], "url": str(url or "").strip(), "published": str(published or "")[:80]}


def _rss(raw: bytes, cap: int) -> list[dict]:
    root = ET.fromstring(raw)
    entries = root.findall(".//item") or root.findall("{*}entry")
    out = []
    for entry in entries[:cap]:
        title = entry.findtext("title") or entry.findtext("{*}title") or ""
        link = entry.findtext("link") or entry.findtext("{*}link") or ""
        if not link:
            element = entry.find("{*}link")
            link = element.get("href", "") if element is not None else ""
        published = (entry.findtext("pubDate") or entry.findtext("published")
                     or entry.findtext("{*}published") or "")
        if title and link:
            out.append(_item(title, link, published))
    return out


class _Links(HTMLParser):
    def __init__(self, base: str):
        super().__init__()
        self.base, self.current, self.items = base, "", []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.current = dict(attrs).get("href", "")
    def handle_data(self, data):
        if self.current and data.strip():
            self.items.append(_item(data, urljoin(self.base, self.current)))
            self.current = ""
    def handle_endtag(self, tag):
        if tag == "a": self.current = ""


def _html(raw: bytes, url: str, cap: int) -> list[dict]:
    parser = _Links(url)
    parser.feed(raw.decode("utf-8", errors="replace"))
    return [item for item in parser.items if item["url"].startswith("https://")][:cap]


def _api(raw: bytes, cap: int) -> list[dict] | None:
    try:
        rows = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(rows, list):
        return None
    out = []
    for row in rows[:cap]:
        if not isinstance(row, dict): continue
        title, url = row.get("title"), row.get("url") or row.get("link")
        if isinstance(title, str) and isinstance(url, str) and url.startswith("https://"):
            out.append(_item(title, url, str(row.get("published") or row.get("date") or "")))
    return out


def fetch_source(source, *, get=_http_get, max_items: int = 10) -> dict:
    """Fetch one public source; return safe items or a classified health reason."""
    cap = max(1, min(int(max_items), 20))
    try:
        raw = get(source.url, 20)
        if source.mode == "rss": items = _rss(raw, cap)
        elif source.mode == "html": items = _html(raw, source.url, cap)
        else:
            items = _api(raw, cap)
            if items is None: return {"ok": False, "source": source.name, "reason": "source_malformed"}
    except Exception:
        return {"ok": False, "source": source.name, "reason": "source_unavailable"}
    return {"ok": True, "source": source.name, "mode": source.mode, "items": items}


__all__ = ["fetch_source"]
