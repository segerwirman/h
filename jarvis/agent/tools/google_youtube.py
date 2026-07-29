"""YouTube Data API read tools — MK50 REFRESHED HYBRID.

Refreshed to support BOTH modes:
- API Key mode (jarvis/youtube/data_api_v3): public search, video info, trending — NO OAuth needed
- OAuth mode (Google unified): subscriptions, my channel stats, latest from subscriptions — full features

This fixes the issue where tools were hidden when OAuth not connected, even though API key was valid.
Different from playback browser tools (§10.5).
"""
from __future__ import annotations

import asyncio
import re

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.core import config, log
from jarvis.integrations import google_api, google_auth

_logger = log.get("agent.tools.youtube")

READ_SCOPE = google_auth.SCOPES["youtube"]["read"]
WRITE_SCOPE = google_auth.SCOPES["youtube"]["write"]


def _get_api_key() -> str | None:
    try:
        from jarvis.core import secrets_store
        secrets_store.initialize()
        k = secrets_store.get("jarvis/youtube/data_api_v3")
        if k and k.strip():
            return k.strip()
        # also try legacy adapter
        try:
            from jarvis.integrations.comments import youtube_oauth
            lk = youtube_oauth.api_key()
            if lk:
                return lk.strip()
        except Exception:
            pass
    except Exception:
        pass
    return None


def available() -> bool:
    """Tool available if either API key OR OAuth connected — hybrid mode."""
    has_key = bool(_get_api_key())
    has_oauth = False
    try:
        has_oauth = google_auth.has_read_scope("youtube")
    except Exception:
        pass
    return has_key or has_oauth


def _has_oauth() -> bool:
    try:
        return google_auth.has_read_scope("youtube")
    except Exception:
        return False


def _scope() -> str:
    return WRITE_SCOPE if google_auth.has_scope(WRITE_SCOPE) else READ_SCOPE


def _service():
    return google_api.service("youtube", "v3", [_scope()])


def _video_line(item: dict) -> str:
    snippet = item.get("snippet") or {}
    resource = snippet.get("resourceId") or {}
    ident = item.get("id") or {}
    video_id = resource.get("videoId") or (
        ident.get("videoId") if isinstance(ident, dict) else "")
    channel = snippet.get("channelTitle") or "channel tidak dikenal"
    title = snippet.get("title") or "Video tanpa judul"
    suffix = f" — https://youtu.be/{video_id}" if video_id else ""
    return f"{title} ({channel}){suffix}"


def _api_key_service_search(query: str, limit: int = 5, order: str = "relevance") -> list[dict]:
    """Fallback search using API key via plain requests"""
    import requests
    key = _get_api_key()
    if not key:
        return []
    try:
        params = {
            "part": "snippet",
            "q": query,
            "type": "video",
            "order": order,
            "maxResults": max(1, min(int(limit), 25)),
            "regionCode": str(config.get("locale.region", "ID")),
            "relevanceLanguage": str(config.get("locale.language", "id")),
            "key": key
        }
        r = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=15)
        if r.status_code != 200:
            _logger.warning("youtube.api_key_search_failed", status=r.status_code)
            return []
        return r.json().get("items", [])
    except Exception as e:
        _logger.warning("youtube.api_key_search_error", error=str(e)[:100])
        return []


def _api_key_video_info(video_id: str) -> dict | None:
    import requests
    key = _get_api_key()
    if not key or not video_id:
        return None
    try:
        params = {
            "part": "snippet,statistics,contentDetails",
            "id": video_id,
            "key": key
        }
        r = requests.get("https://www.googleapis.com/youtube/v3/videos", params=params, timeout=12)
        if r.status_code != 200:
            return None
        items = r.json().get("items", [])
        return items[0] if items else None
    except Exception:
        return None


class _SubscriptionsParams(BaseModel):
    limit: int = Field(10, ge=1, le=50)


class YtSubscriptions(Tool):
    name = "yt_subscriptions"
    description = "Bacakan daftar channel YouTube yang dilanggani user. (Butuh OAuth Google — Settings > Google Cloud > Connect Google)"
    params_schema = _SubscriptionsParams
    read_only = True
    timeout_s = 30

    async def run(self, limit: int = 10, **_) -> ToolResult:
        if not _has_oauth():
            return ToolResult.fail("Fitur langganan butuh OAuth Google. Buka Settings → Google Cloud → aktifkan YouTube Data — read → Connect Google, sir.")
        def work():
            return _service().subscriptions().list(
                part="snippet", mine=True,
                maxResults=max(1, min(int(limit), 50))).execute()
        try:
            response = await asyncio.to_thread(work)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        rows = []
        for item in response.get("items") or []:
            snippet = item.get("snippet") or {}
            resource = snippet.get("resourceId") or {}
            rows.append(f"{snippet.get('title') or 'Tanpa nama'} "
                        f"({resource.get('channelId') or '-'})")
        text = (f"Ada {len(rows)} langganan: " + "; ".join(rows)
                if rows else "Daftar langganan YouTube kosong.")
        return ToolResult.success(text, display=text)


class _LatestParams(BaseModel):
    channel: str = Field(
        "", description="Nama/@handle channel; kosong=channel langganan")
    limit: int = Field(5, ge=1, le=10)


def _channel_rows_oauth(service, channel: str, limit: int) -> list[dict]:
    if channel:
        if channel.strip().startswith("@"):
            response = service.channels().list(
                part="snippet,contentDetails",
                forHandle=channel.strip()).execute()
            return list(response.get("items") or [])[:1]
        found = service.search().list(
            part="snippet", q=channel, type="channel", maxResults=1
        ).execute().get("items") or []
        ids = [str((item.get("id") or {}).get("channelId") or "")
               for item in found]
    else:
        subscriptions = service.subscriptions().list(
            part="snippet", mine=True,
            maxResults=max(1, min(limit * 2, 20))).execute()
        ids = [str((((item.get("snippet") or {}).get("resourceId") or {})
                   .get("channelId") or ""))
               for item in subscriptions.get("items") or []]
    ids = [value for value in ids if value]
    if not ids:
        return []
    response = service.channels().list(
        part="snippet,contentDetails", id=",".join(ids[:20])).execute()
    return list(response.get("items") or [])


def _latest_oauth(channel: str, limit: int) -> list[dict]:
    service = _service()
    videos: list[dict] = []
    for row in _channel_rows_oauth(service, channel, limit):
        uploads = (((row.get("contentDetails") or {})
                    .get("relatedPlaylists") or {}).get("uploads"))
        if not uploads:
            continue
        response = service.playlistItems().list(
            part="snippet,contentDetails", playlistId=uploads,
            maxResults=1).execute()
        videos.extend(response.get("items") or [])
    videos.sort(key=lambda item: str(
        (item.get("snippet") or {}).get("publishedAt") or ""), reverse=True)
    return videos[:limit]


class YtLatest(Tool):
    name = "yt_latest"
    description = ("Bacakan video terbaru dari channel langganan atau channel "
                   "tertentu. Untuk langganan perlu OAuth; untuk channel tertentu bisa pakai API key.")
    params_schema = _LatestParams
    read_only = True
    timeout_s = 45

    async def run(self, channel: str = "", limit: int = 5, **_) -> ToolResult:
        # If specific channel given and OAuth missing, use API key method
        if channel and not _has_oauth():
            try:
                import requests
                key = _get_api_key()
                if not key:
                    return ToolResult.fail("YouTube API key tidak tersedia, sir.")
                
                # Search channel by name
                params = {"part": "snippet", "q": channel, "type": "channel", "maxResults": 1, "key": key}
                r = requests.get("https://www.googleapis.com/youtube/v3/search", params=params, timeout=12)
                if r.status_code != 200:
                    return ToolResult.fail(f"YouTube API error HTTP {r.status_code}")
                items = r.json().get("items", [])
                if not items:
                    return ToolResult.success(f"Tidak menemukan channel '{channel}'")
                channel_id = (items[0].get("id") or {}).get("channelId")
                if not channel_id:
                    return ToolResult.success(f"Tidak menemukan channel '{channel}'")

                # Get uploads playlist
                r2 = requests.get("https://www.googleapis.com/youtube/v3/channels", params={"part":"contentDetails","id":channel_id,"key":key}, timeout=12)
                if r2.status_code != 200:
                    return ToolResult.fail("Gagal mengambil channel details")
                citems = r2.json().get("items", [])
                if not citems:
                    return ToolResult.success("Channel tidak ditemukan")
                uploads = ((citems[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
                if not uploads:
                    return ToolResult.success("Tidak ada playlist upload")

                r3 = requests.get("https://www.googleapis.com/youtube/v3/playlistItems", params={"part":"snippet","playlistId":uploads,"maxResults":limit,"key":key}, timeout=12)
                vitems = r3.json().get("items", []) if r3.status_code==200 else []
                rows = [_video_line(v) for v in vitems]
                text = f"Video terbaru dari {channel}: {'; '.join(rows)}" if rows else f"Tidak ada video terbaru dari {channel}"
                return ToolResult.success(text, display=text, route="youtube_api_key")
            except Exception as exc:
                return ToolResult.fail(f"Error: {exc}")

        if not _has_oauth():
            if not channel:
                return ToolResult.fail("Untuk video terbaru dari langganan butuh OAuth. Sebutkan nama channel spesifik atau hubungkan OAuth di Settings > Google Cloud, sir.")
            # else handled above

        try:
            videos = await asyncio.to_thread(
                _latest_oauth, channel, max(1, min(int(limit), 10)))
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        rows = [_video_line(item) for item in videos]
        text = (f"Video terbaru: {'; '.join(rows)}" if rows else
                "Tidak menemukan video terbaru dari channel yang diminta.")
        return ToolResult.success(text, display=text,
                                  route="youtube_data_api")


class _SearchParams(BaseModel):
    query: str = Field(min_length=1)
    limit: int = Field(5, ge=1, le=25)
    order: str = Field("relevance", pattern="^(relevance|date|viewCount)$")


class YtSearchData(Tool):
    name = "yt_search_data"
    description = "Cari metadata video YouTube. Works with API key (public search) or OAuth (full). Mencari video berdasarkan query tanpa browser."
    params_schema = _SearchParams
    read_only = True
    timeout_s = 30

    async def run(self, query: str, limit: int = 5,
                  order: str = "relevance", **_) -> ToolResult:
        # Prefer OAuth if available (higher quota, more features)
        if _has_oauth():
            def work():
                return _service().search().list(
                    part="snippet", q=query, type="video", order=order,
                    maxResults=max(1, min(int(limit), 25)),
                    regionCode=str(config.get("locale.region", "ID")),
                    relevanceLanguage=str(config.get("locale.language", "id")),
                ).execute()
            try:
                response = await asyncio.to_thread(work)
            except Exception as exc:
                # Fallback to API key on OAuth error
                items = _api_key_service_search(query, limit, order)
                if items:
                    rows = [_video_line(item) for item in items]
                    text = "; ".join(rows) if rows else "Tidak ada hasil."
                    return ToolResult.success(text, display=text, route="youtube_api_key_fallback")
                return ToolResult.fail(google_api.safe_error(exc))
            rows = [_video_line(item) for item in response.get("items") or []]
            text = "; ".join(rows) if rows else "Tidak ada hasil YouTube Data API."
            return ToolResult.success(text, display=text,
                                      route="youtube_data_api")

        # API Key mode
        items = await asyncio.to_thread(_api_key_service_search, query, limit, order)
        if not items:
            key = _get_api_key()
            if not key:
                return ToolResult.fail("YouTube API key maupun OAuth belum tersedia. API key ada di secrets_store jarvis/youtube/data_api_v3, OAuth di Settings > Google Cloud, sir.")
            return ToolResult.fail("Tidak ada hasil YouTube untuk query tersebut, sir.")
        rows = [_video_line(item) for item in items]
        text = "; ".join(rows)
        return ToolResult.success(text, display=text, route="youtube_api_key")


class _VideoInfoParams(BaseModel):
    video_id: str = Field(description="YouTube video ID (11 chars) or full URL")
    

class YtVideoInfo(Tool):
    name = "yt_video_info"
    description = "Dapatkan info detail video YouTube (judul, channel, view, like, durasi) via API key atau OAuth. Support video ID atau URL."
    params_schema = _VideoInfoParams
    read_only = True
    timeout_s = 20

    async def run(self, video_id: str, **_) -> ToolResult:
        # Extract ID if full URL given
        raw = video_id.strip()
        match = re.search(r"(?:v=|\/v\/|youtu\.be\/|\/embed\/|\/shorts\/)([A-Za-z0-9_-]{11})", raw)
        vid = match.group(1) if match else raw
        if len(vid) != 11:
            return ToolResult.fail(f"Video ID tidak valid: {raw}. Harus 11 karakter atau URL YouTube, sir.")

        if _has_oauth():
            def work():
                return _service().videos().list(
                    part="snippet,statistics,contentDetails", id=vid).execute()
            try:
                resp = await asyncio.to_thread(work)
                items = resp.get("items", [])
                if not items:
                    return ToolResult.fail(f"Video {vid} tidak ditemukan")
                it = items[0]
                snippet = it.get("snippet", {})
                stats = it.get("statistics", {})
                details = it.get("contentDetails", {})
                txt = (
                    f"Title: {snippet.get('title','-')}\n"
                    f"Channel: {snippet.get('channelTitle','-')}\n"
                    f"Published: {snippet.get('publishedAt','-')[:10]}\n"
                    f"Views: {stats.get('viewCount','-')}\n"
                    f"Likes: {stats.get('likeCount','-')}\n"
                    f"Duration: {details.get('duration','-')}\n"
                    f"URL: https://youtu.be/{vid}"
                )
                return ToolResult.success(txt, display=txt)
            except Exception as e:
                # fallback to api key
                pass

        # API key fallback
        def api_key_work():
            return _api_key_video_info(vid)
        
        info = await asyncio.to_thread(api_key_work)
        if not info:
            return ToolResult.fail(f"Gagal mengambil info video {vid}, sir.")
        
        snippet = info.get("snippet", {})
        stats = info.get("statistics", {})
        details = info.get("contentDetails", {})
        txt = (
            f"Title: {snippet.get('title','-')}\n"
            f"Channel: {snippet.get('channelTitle','-')}\n"
            f"Published: {snippet.get('publishedAt','-')[:10]}\n"
            f"Views: {stats.get('viewCount','-')}\n"
            f"Likes: {stats.get('likeCount','-')}\n"
            f"Duration: {details.get('duration','-')}\n"
            f"URL: https://youtu.be/{vid}"
        )
        return ToolResult.success(txt, display=txt, route="youtube_api_key")


class _TrendingParams(BaseModel):
    region: str = Field("ID", description="Region code e.g. ID, US, JP")
    limit: int = Field(8, ge=1, le=20)


class YtTrending(Tool):
    name = "yt_trending"
    description = "Tampilkan video trending YouTube berdasarkan region. Works with API key (no OAuth needed)."
    params_schema = _TrendingParams
    read_only = True
    timeout_s = 20

    async def run(self, region: str = "ID", limit: int = 8, **_) -> ToolResult:
        def work_oauth():
            return _service().videos().list(
                part="snippet", chart="mostPopular",
                regionCode=region.upper(),
                maxResults=max(1, min(int(limit), 20))
            ).execute()

        if _has_oauth():
            try:
                resp = await asyncio.to_thread(work_oauth)
                rows = []
                for i, item in enumerate(resp.get("items", []), 1):
                    snippet = item.get("snippet", {})
                    rows.append(f"{i}. {snippet.get('title','-')} — {snippet.get('channelTitle','-')}")
                text = f"Trending {region.upper()}:\n" + "\n".join(rows) if rows else "Tidak ada trending"
                return ToolResult.success(text, display=text, route="youtube_data_api")
            except Exception:
                pass

        # API key method
        def work_key():
            import requests
            key = _get_api_key()
            if not key:
                return []
            params = {
                "part": "snippet",
                "chart": "mostPopular",
                "regionCode": region.upper(),
                "maxResults": max(1, min(int(limit), 20)),
                "key": key
            }
            r = requests.get("https://www.googleapis.com/youtube/v3/videos", params=params, timeout=12)
            if r.status_code != 200:
                return []
            return r.json().get("items", [])

        items = await asyncio.to_thread(work_key)
        if not items:
            return ToolResult.fail("Tidak bisa mengambil trending, sir. Periksa API key atau koneksi.")
        rows = []
        for i, item in enumerate(items, 1):
            snippet = item.get("snippet", {})
            rows.append(f"{i}. {snippet.get('title','-')} — {snippet.get('channelTitle','-')} (https://youtu.be/{item.get('id','')})")
        text = f"Trending {region.upper()}:\n" + "\n".join(rows)
        return ToolResult.success(text, display=text, route="youtube_api_key")


class _StatsParams(BaseModel):
    pass


class YtMyStats(Tool):
    name = "yt_my_stats"
    description = "Bacakan statistik channel YouTube milik user. (Butuh OAuth — Settings > Google Cloud)"
    params_schema = _StatsParams
    read_only = True
    timeout_s = 30

    async def run(self, **_) -> ToolResult:
        if not _has_oauth():
            return ToolResult.fail("Statistik channel butuh OAuth Google. Buka Settings → Google Cloud → aktifkan YouTube → Connect Google, sir.")
        def work():
            return _service().channels().list(
                part="snippet,statistics", mine=True).execute()
        try:
            response = await asyncio.to_thread(work)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        rows = []
        for item in response.get("items") or []:
            snippet, stats = item.get("snippet") or {}, item.get("statistics") or {}
            rows.append(
                f"{snippet.get('title') or 'Channel'}: "
                f"{stats.get('subscriberCount', 'disembunyikan')} subscriber, "
                f"{stats.get('videoCount', '0')} video, "
                f"{stats.get('viewCount', '0')} view")
        text = "; ".join(rows) if rows else "Channel YouTube user tidak ditemukan."
        return ToolResult.success(text, display=text)
