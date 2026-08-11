"""Spotify (§3.1.P) — Web API + OAuth PKCE, tanpa dependency tambahan.

Modul nonaktif otomatis bila SPOTIFY_CLIENT_ID kosong. Login pertama:
tool ``spotify_play``/dll. akan menyuruh user membuka URL otorisasi; server
callback lokal sekali-pakai menangkap kode; refresh token disimpan melalui
``secrets_store`` dan di-refresh otomatis.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse

from pydantic import BaseModel, Field

from jarvis.core import config, log, secrets_store
from jarvis.agent.base import Tool, ToolResult

_logger = log.get("agent.tools.spotify")
_API = "https://api.spotify.com/v1"
_lock = threading.Lock()


def _client_id() -> str:
    return os.environ.get("SPOTIFY_CLIENT_ID", "")


def _redirect_uri() -> str:
    return os.environ.get("SPOTIFY_REDIRECT_URI", "") \
        or str(config.get("agent.spotify.redirect_uri",
                          "http://127.0.0.1:8888/callback"))


def available() -> bool:
    return bool(_client_id())


def _load_tokens() -> dict:
    try:
        raw = secrets_store.get("jarvis/oauth/spotify")
        return json.loads(raw) if raw else {}
    except Exception:                                        # noqa: BLE001
        return {}


def _save_tokens(t: dict) -> bool:
    return secrets_store.set("jarvis/oauth/spotify", json.dumps(
        t, ensure_ascii=False, separators=(",", ":")))


def _access_token() -> str | None:
    """Token valid; refresh otomatis; None bila belum pernah login."""
    with _lock:
        t = _load_tokens()
        if not t.get("refresh_token"):
            return None
        if t.get("expires_at", 0) > time.time() + 30:
            return t.get("access_token")
        import requests
        r = requests.post("https://accounts.spotify.com/api/token", data={
            "grant_type": "refresh_token",
            "refresh_token": t["refresh_token"],
            "client_id": _client_id(),
        }, timeout=20)
        if r.status_code != 200:
            _logger.error("spotify.refresh_failed", status=r.status_code)
            return None
        data = r.json()
        t["access_token"] = data["access_token"]
        t["expires_at"] = time.time() + int(data.get("expires_in", 3600))
        if data.get("refresh_token"):
            t["refresh_token"] = data["refresh_token"]
        return t["access_token"] if _save_tokens(t) else None


_SCOPES = ("user-modify-playback-state user-read-playback-state "
           "user-read-currently-playing playlist-modify-public "
           "playlist-modify-private playlist-read-private user-library-read")


def begin_auth() -> str:
    """Bangun URL otorisasi PKCE + jalankan server callback sekali-pakai."""
    verifier = secrets.token_urlsafe(64)[:128]
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(16)
    params = {
        "client_id": _client_id(), "response_type": "code",
        "redirect_uri": _redirect_uri(), "scope": _SCOPES,
        "code_challenge_method": "S256", "code_challenge": challenge,
        "state": state,
    }
    url = ("https://accounts.spotify.com/authorize?"
           + urllib.parse.urlencode(params))
    threading.Thread(target=_callback_server, args=(verifier, state),
                     daemon=True, name="spotify-oauth").start()
    return url


def _callback_server(verifier: str, state: str) -> None:
    from http.server import BaseHTTPRequestHandler, HTTPServer

    parsed = urllib.parse.urlparse(_redirect_uri())
    port = parsed.port or 8888

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):                                    # noqa: N802
            q = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            code = (q.get("code") or [""])[0]
            ok = bool(code) and (q.get("state") or [""])[0] == state
            if ok:
                try:
                    import requests
                    r = requests.post(
                        "https://accounts.spotify.com/api/token", data={
                            "grant_type": "authorization_code",
                            "code": code,
                            "redirect_uri": _redirect_uri(),
                            "client_id": _client_id(),
                            "code_verifier": verifier,
                        }, timeout=20)
                    r.raise_for_status()
                    data = r.json()
                    ok = _save_tokens({
                        "access_token": data["access_token"],
                        "refresh_token": data.get("refresh_token", ""),
                        "expires_at": time.time()
                        + int(data.get("expires_in", 3600))})
                    if not ok:
                        raise RuntimeError(
                            "backend penyimpanan terenkripsi tidak tersedia")
                    _logger.info("spotify.authorized")
                except Exception as e:                       # noqa: BLE001
                    _logger.error("spotify.auth_failed", error=str(e)[:120])
                    ok = False
            body = ("<h2>Spotify terhubung — kembali ke JARVIS.</h2>" if ok
                    else "<h2>Otorisasi gagal.</h2>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)
            threading.Thread(target=self.server.shutdown,
                             daemon=True).start()

        def log_message(self, *a):                           # senyap
            pass

    try:
        HTTPServer(("127.0.0.1", port), Handler).serve_forever()
    except OSError as e:
        _logger.error("spotify.callback_bind_failed", error=str(e)[:80])


def _call(method: str, path: str, **kwargs):
    token = _access_token()
    if token is None:
        url = begin_auth()
        raise PermissionError(
            "Spotify belum terhubung. Minta user membuka URL ini untuk "
            f"login (berlaku sekali): {url}")
    import requests
    r = requests.request(method, f"{_API}{path}", timeout=20,
                         headers={"Authorization": f"Bearer {token}"},
                         **kwargs)
    if r.status_code == 403 and "PREMIUM" in r.text.upper():
        raise PermissionError("kontrol playback butuh Spotify Premium")
    if r.status_code >= 400:
        raise RuntimeError(f"Spotify {r.status_code}: {r.text[:180]}")
    return r.json() if r.text else {}


def _run_call(method: str, path: str, **kwargs) -> ToolResult:
    try:
        data = _call(method, path, **kwargs)
        return ToolResult.success(data if data else "ok")
    except PermissionError as e:
        return ToolResult.fail(str(e))
    except Exception as e:                                   # noqa: BLE001
        return ToolResult.fail(str(e)[:250])


class _SearchParams(BaseModel):
    query: str = Field(description="Kata kunci")
    type: str = Field("track", description="track|album|artist|playlist")


class SpotifySearch(Tool):
    name = "spotify_search"
    description = "Cari lagu/album/artis/playlist di Spotify. Return nama + URI."
    params_schema = _SearchParams
    read_only = True
    timeout_s = 30

    async def run(self, query: str, type: str = "track", **_) -> ToolResult:
        res = await asyncio.to_thread(
            _run_call, "GET", "/search",
            params={"q": query, "type": type, "limit": 8})
        if not res.ok:
            return res
        items = (res.content.get(type + "s") or {}).get("items", [])
        lines = []
        for it in items:
            artists = ", ".join(a["name"] for a in it.get("artists", [])) \
                if it.get("artists") else ""
            lines.append(f"{it.get('name')}"
                         + (f" — {artists}" if artists else "")
                         + f"  [{it.get('uri')}]")
        return ToolResult.success("\n".join(lines) or "tidak ada hasil",
                                  display=f"{len(lines)} hasil")


class _PlayParams(BaseModel):
    uri: str = Field("", description="spotify:track/album/playlist:… "
                                     "(kosong = resume)")


class SpotifyPlay(Tool):
    name = "spotify_play"
    description = "Putar/resume playback (butuh Spotify Premium + device aktif)."
    params_schema = _PlayParams
    timeout_s = 30

    async def run(self, uri: str = "", **_) -> ToolResult:
        body: dict = {}
        if uri.startswith("spotify:track:"):
            body = {"uris": [uri]}
        elif uri:
            body = {"context_uri": uri}
        return await asyncio.to_thread(
            _run_call, "PUT", "/me/player/play", json=body)


class SpotifyPause(Tool):
    name = "spotify_pause"
    description = "Pause playback."
    timeout_s = 30

    async def run(self, **_) -> ToolResult:
        return await asyncio.to_thread(_run_call, "PUT", "/me/player/pause")


class SpotifyNext(Tool):
    name = "spotify_next"
    description = "Lagu berikutnya."
    timeout_s = 30

    async def run(self, **_) -> ToolResult:
        return await asyncio.to_thread(_run_call, "POST", "/me/player/next")


class SpotifyPrev(Tool):
    name = "spotify_prev"
    description = "Lagu sebelumnya."
    timeout_s = 30

    async def run(self, **_) -> ToolResult:
        return await asyncio.to_thread(_run_call, "POST",
                                       "/me/player/previous")


class _VolParams(BaseModel):
    percent: int = Field(description="0-100")


class SpotifyVolume(Tool):
    name = "spotify_volume"
    description = "Atur volume playback Spotify (0-100)."
    params_schema = _VolParams
    timeout_s = 30

    async def run(self, percent: int, **_) -> ToolResult:
        pct = max(0, min(100, int(percent)))
        return await asyncio.to_thread(
            _run_call, "PUT", "/me/player/volume",
            params={"volume_percent": pct})


class SpotifyNowPlaying(Tool):
    name = "spotify_now_playing"
    description = "Lagu yang sedang diputar."
    read_only = True
    timeout_s = 30

    async def run(self, **_) -> ToolResult:
        res = await asyncio.to_thread(
            _run_call, "GET", "/me/player/currently-playing")
        if not res.ok:
            return res
        item = (res.content or {}).get("item") if \
            isinstance(res.content, dict) else None
        if not item:
            return ToolResult.success("tidak ada yang diputar")
        artists = ", ".join(a["name"] for a in item.get("artists", []))
        return ToolResult.success(
            f"{item.get('name')} — {artists} [{item.get('uri')}]")


class _PlaylistCreateParams(BaseModel):
    name: str = Field(description="Nama playlist")
    public: bool = Field(False)


class SpotifyPlaylistCreate(Tool):
    name = "spotify_playlist_create"
    description = "Buat playlist baru untuk user."
    params_schema = _PlaylistCreateParams
    timeout_s = 30

    async def run(self, name: str, public: bool = False, **_) -> ToolResult:
        me = await asyncio.to_thread(_run_call, "GET", "/me")
        if not me.ok:
            return me
        uid = me.content.get("id")
        res = await asyncio.to_thread(
            _run_call, "POST", f"/users/{uid}/playlists",
            json={"name": name, "public": bool(public)})
        if not res.ok:
            return res
        return ToolResult.success(
            f"playlist dibuat: {res.content.get('name')} "
            f"[{res.content.get('id')}]")


class _PlaylistAddParams(BaseModel):
    playlist_id: str = Field(description="ID playlist")
    uris: list[str] = Field(description="Daftar spotify:track:…")


class SpotifyPlaylistAdd(Tool):
    name = "spotify_playlist_add"
    description = "Tambah lagu ke playlist."
    params_schema = _PlaylistAddParams
    timeout_s = 30

    async def run(self, playlist_id: str, uris: list[str], **_) -> ToolResult:
        res = await asyncio.to_thread(
            _run_call, "POST", f"/playlists/{playlist_id}/tracks",
            json={"uris": list(uris)[:100]})
        if not res.ok:
            return res
        return ToolResult.success(f"{len(uris)} lagu ditambahkan")


class _LibraryParams(BaseModel):
    type: str = Field("saved_tracks",
                      description="saved_tracks | albums | playlists")


class SpotifyLibrary(Tool):
    name = "spotify_library"
    description = "Isi library user (lagu tersimpan / album / playlist)."
    params_schema = _LibraryParams
    read_only = True
    timeout_s = 30

    async def run(self, type: str = "saved_tracks", **_) -> ToolResult:
        path = {"saved_tracks": "/me/tracks", "albums": "/me/albums",
                "playlists": "/me/playlists"}.get(type)
        if path is None:
            return ToolResult.fail(f"type tidak dikenal: {type}")
        res = await asyncio.to_thread(_run_call, "GET", path,
                                      params={"limit": 20})
        if not res.ok:
            return res
        items = (res.content or {}).get("items", [])
        lines = []
        for it in items:
            obj = it.get("track") or it.get("album") or it
            name = obj.get("name", "?")
            artists = ", ".join(a["name"] for a in obj.get("artists", [])) \
                if obj.get("artists") else ""
            lines.append(f"{name}" + (f" — {artists}" if artists else "")
                         + f"  [{obj.get('uri', '')}]")
        return ToolResult.success("\n".join(lines) or "(kosong)",
                                  display=f"{len(lines)} item")
