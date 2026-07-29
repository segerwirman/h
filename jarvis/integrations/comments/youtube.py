"""YouTube live-chat adapter (redesign §15).

Uses the real YouTube Data API v3 (``liveChatMessages.list``/``.insert``)
over plain ``requests`` — no extra SDK dependency beyond what the project
already ships. Reading and replying both require an OAuth2 access token
with the ``youtube`` scope (a bare API key is not sufficient for live chat
message access); the token is read from ``jarvis.core.secrets_store``
(OS keyring), never from config.yaml.

Without a configured token or a resolvable ``liveChatId``, ``capabilities()``
reports the honest unsupported state instead of pretending to work — no
network call is attempted until both are present.

This adapter cannot be smoke-tested against the live API from this
environment (no credentials/network here); the endpoint shapes below match
the published YouTube Data API v3 reference.
"""
from __future__ import annotations

import time

from jarvis.core import config, log, secrets_store
from jarvis.integrations.comments.base import (CommentEvent, PlatformAdapter,
                                               PlatformCapabilities, ReplyResult)

_logger = log.get("comments.youtube")

_API_BASE = "https://www.googleapis.com/youtube/v3"
_TOKEN_KEY = "YOUTUBE_OAUTH_TOKEN"


class YouTubeAdapter(PlatformAdapter):
    name = "youtube"

    def __init__(self, live_chat_id: str = ""):
        self._live_chat_id = live_chat_id or str(config.get("live_comments.platforms.youtube.live_chat_id", ""))
        self._next_page_token: str | None = None
        self._last_error = ""
        self._last_poll_ok: bool | None = None

    def _token(self) -> str | None:
        # Prefer the refreshing provider (handles OAuth token expiry); fall back
        # to a bare token stored directly under the keyring key.
        try:
            from jarvis.integrations.comments import youtube_oauth
            tok = youtube_oauth.access_token()
            if tok:
                return tok
        except Exception:
            pass
        return secrets_store.get(_TOKEN_KEY)

    def is_authenticated(self) -> bool:
        return bool(self._token())

    def capabilities(self) -> PlatformCapabilities:
        if not bool(config.get("live_comments.platforms.youtube.enabled", False)):
            return PlatformCapabilities(False, False, True,
                                        "disabled in config (live_comments.platforms.youtube.enabled)")
        if not self._token():
            return PlatformCapabilities(False, False, True,
                                        "no OAuth token in keyring (YOUTUBE_OAUTH_TOKEN) — "
                                        "run OAuth setup before enabling")
        if not self._live_chat_id:
            return PlatformCapabilities(False, False, True,
                                        "no liveChatId configured — resolve one via "
                                        "videos.list(part=liveStreamingDetails) first")
        return PlatformCapabilities(True, True, False,
                                    "liveChatMessages.list/.insert — replies post as the "
                                    "authenticated channel/moderator")

    def poll_comments(self) -> list[CommentEvent]:
        caps = self.capabilities()
        if not caps.can_read:
            return []
        try:
            import requests
        except ImportError:
            self._last_error = "requests not installed"
            self._last_poll_ok = False
            return []
        try:
            params = {
                "liveChatId": self._live_chat_id,
                "part": "snippet,authorDetails",
                "access_token": self._token(),
            }
            if self._next_page_token:
                params["pageToken"] = self._next_page_token
            resp = requests.get(f"{_API_BASE}/liveChat/messages", params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            self._next_page_token = data.get("nextPageToken")
            events = []
            for item in data.get("items", []):
                snippet = item.get("snippet", {})
                author = item.get("authorDetails", {})
                text = snippet.get("displayMessage", "")
                if not text:
                    continue
                events.append(CommentEvent(
                    platform=self.name,
                    comment_id=item.get("id", ""),
                    author_id=author.get("channelId", ""),
                    author_name=author.get("displayName", ""),
                    text=text,
                    timestamp=time.time(),
                    stream_id=self._live_chat_id,
                    is_moderator=bool(author.get("isChatModerator")),
                    is_paid=snippet.get("type") in ("superChatEvent", "superStickerEvent"),
                    meta={"type": snippet.get("type", "")},
                ))
            self._last_poll_ok = True
            self._last_error = ""
            return events
        except Exception as e:
            self._last_error = str(e)[:200]
            self._last_poll_ok = False
            _logger.warning("youtube.poll_failed", error=self._last_error)
            return []

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        caps = self.capabilities()
        if not caps.can_reply:
            return ReplyResult(False, caps.notes)
        try:
            import requests
        except ImportError:
            return ReplyResult(False, "requests not installed")
        try:
            token = self._token()
            resp = requests.post(
                f"{_API_BASE}/liveChat/messages",
                params={"part": "snippet", "access_token": token},
                json={"snippet": {
                    "liveChatId": self._live_chat_id,
                    "type": "textMessageEvent",
                    "textMessageDetails": {"messageText": text},
                }}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return ReplyResult(True, "sent", reply_id=data.get("id", ""))
        except Exception as e:
            return ReplyResult(False, str(e)[:200])

    def connection_health(self) -> dict:
        return {"platform": self.name, "connected": bool(self._last_poll_ok),
               "authenticated": self.is_authenticated(), "detail": self._last_error}
