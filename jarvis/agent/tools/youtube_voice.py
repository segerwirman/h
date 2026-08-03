"""Native YouTube search entrypoint for the Gemini Live voice lane."""
from __future__ import annotations

from urllib.parse import quote_plus

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult


class _YouTubeSearchParams(BaseModel):
    query: str = Field(min_length=1, description="Kueri video YouTube")


class YouTubeSearch(Tool):
    """Open native agent browser on a YouTube result page.

    Playback is deliberately separate: model must obtain ``browser_snapshot``
    then use ``browser_click``/``browser_media``.  This avoids claiming a
    particular video was played before target evidence exists.
    """

    name = "youtube_search"
    description = (
        "Cari video YouTube di browser agent native. Setelah hasil terbuka, "
        "panggil browser_snapshot lalu pilih ref video; jangan mengaku video "
        "sudah diputar sebelum browser_media memberi hasil sukses."
    )
    params_schema = _YouTubeSearchParams
    wants_context = True
    timeout_s = 90

    async def run(self, query: str, _session=None, **_) -> ToolResult:
        from jarvis.agent.tools.browser import BrowserNavigate

        clean = " ".join(str(query or "").split())
        if not clean:
            return ToolResult.fail("kueri YouTube kosong")
        url = "https://www.youtube.com/results?search_query=" + quote_plus(clean)
        return await BrowserNavigate().run(url=url, _session=_session)


__all__ = ["YouTubeSearch"]
