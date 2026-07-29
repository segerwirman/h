"""SocialMediaMonitoring — poll configured feeds, surface ambient
notifications on the stage. Rate-limit aware (per-feed backoff on 429/errors).

RSS/Atom over urllib keeps this dependency-free; X/Reddit API integrations
plug in as additional fetchers when credentials are configured.
"""
from __future__ import annotations

import threading
import time
import urllib.request
import xml.etree.ElementTree as ET

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.nlp.base import Context, Response

_logger = log.get("nlp.social")


class SocialMediaMonitoring:
    name = "SocialMediaMonitoring"

    def __init__(self) -> None:
        s = config.section("nlp.social")
        self._interval = float(s.get("poll_interval_s", 300))
        self._feeds: list[str] = [str(u) for u in (s.get("feeds") or [])]
        self._seen: set[str] = set()
        self._backoff: dict[str, float] = {}       # feed → next allowed poll
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self.last_items: list[dict] = []

    # ── polling service ──────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._feeds:
            _logger.info("social.no_feeds_configured")
            return
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._loop, daemon=True,
                                        name="social-poll")
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _loop(self) -> None:
        while not self._stop.wait(2.0):
            now = time.time()
            for feed in self._feeds:
                if now < self._backoff.get(feed, 0):
                    continue
                self._backoff[feed] = now + self._interval
                try:
                    fresh = self._poll_feed(feed)
                    for item in fresh[:3]:
                        BUS.publish("notify", title=item["source"],
                                    body=item["title"])
                except Exception as e:
                    # rate-limit / failure: double the wait for this feed
                    self._backoff[feed] = now + self._interval * 2
                    _logger.warning("social.poll_failed", feed=feed,
                                    error=str(e)[:120])
            # sleep in small steps so stop() is responsive
            for _ in range(int(self._interval / 2)):
                if self._stop.wait(2.0):
                    return

    def _poll_feed(self, url: str) -> list[dict]:
        req = urllib.request.Request(url, headers={"User-Agent": "JARVIS/49"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            if resp.status == 429:
                raise RuntimeError("rate limited")
            root = ET.fromstring(resp.read())
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = []
        for item in root.iter("item"):                       # RSS
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            items.append({"title": title, "link": link, "source": url})
        for entry in root.iter("{http://www.w3.org/2005/Atom}entry"):  # Atom
            title = (entry.findtext("atom:title", namespaces=ns) or "").strip()
            items.append({"title": title, "link": "", "source": url})
        fresh = [i for i in items if i["title"] and i["title"] not in self._seen]
        for i in fresh:
            self._seen.add(i["title"])
        self.last_items = items[:20]
        return fresh

    # ── NLPModule protocol ───────────────────────────────────────────────────

    def can_handle(self, text: str, ctx: Context) -> float:
        t = text.lower()
        if any(k in t for k in ("pantau", "monitor", "feed", "rss",
                                "media sosial", "social media", "timeline")):
            return 0.75
        return 0.0

    async def handle(self, text: str, ctx: Context) -> Response:
        if not self._feeds:
            return Response(
                "Belum ada feed yang dikonfigurasi. Tambahkan URL RSS di "
                "config.yaml → nlp.social.feeds.", source=self.name)
        lines = [f"• {i['title']}" for i in self.last_items[:8]]
        body = ("Pantauan terbaru:\n" + "\n".join(lines)) if lines else \
            "Feed terpantau, belum ada item baru."
        return Response(body, show_on_stage=True, source=self.name)
