"""OnlineSearch — wraps Part 3 (browser → extract → summarize)."""
from __future__ import annotations

import asyncio

from jarvis.core.bus import BUS
from jarvis.core.router import search_url
from jarvis.nlp.base import Context, Response

_TRIGGERS = ("cari", "carikan", "search", "googling", "browsing",
             "berita", "news", "look up", "find online")


class OnlineSearch:
    name = "OnlineSearch"

    def can_handle(self, text: str, ctx: Context) -> float:
        t = text.lower()
        if any(t.startswith(k) for k in _TRIGGERS):
            return 0.9
        if any(k in t for k in ("di internet", "on the web", "online")):
            return 0.7
        return 0.0

    async def handle(self, text: str, ctx: Context) -> Response:
        query = text
        for k in _TRIGGERS:
            if query.lower().startswith(k):
                query = query[len(k):].strip(" :,-")
                break
        query = query or text
        url = search_url(query)
        # The window subscribes to this topic and drives the embedded browser
        # (page immediately, orb docks in parallel, summary streams after).
        BUS.publish("intent", intent="SEARCH_WEB", text=text,
                    meta={"query": query, "url": url})
        ctx.last_url = url
        return Response(
            f"Mencari '{query}' — halaman terbuka di layar, ringkasan menyusul.",
            show_on_stage=False, source=self.name,
            meta={"query": query, "url": url})
