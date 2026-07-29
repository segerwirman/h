"""Facebook Page live-video comments adapter (redesign §15).

Uses the real Meta Graph API shape: ``GET /{live_video_id}/comments`` to
read, ``POST /{comment_id}/comments`` to reply. This requires:
  * a Facebook Page (not a personal profile — the Graph API does not expose
    live-video comments for personal timelines to third-party apps),
  * a Page Access Token with ``pages_read_engagement`` (read) and
    ``pages_manage_engagement`` (reply) permissions,
  * App Review approval from Meta for those permissions in production
    (test-mode tokens work only for the app's own Pages/testers).

The token lives in ``jarvis.core.secrets_store`` (OS keyring), never in
config.yaml. Without a token and a configured live-video id,
``capabilities()`` reports manual-approval-required — no request is made.
Cannot be smoke-tested here (no credentials/network in this environment);
the endpoint shapes match the published Graph API reference.
"""
from __future__ import annotations

import time

from jarvis.core import config, log, secrets_store
from jarvis.integrations.comments.base import (CommentEvent, PlatformAdapter,
                                               PlatformCapabilities, ReplyResult)

_logger = log.get("comments.facebook")
_GRAPH_BASE = "https://graph.facebook.com/v19.0"
_TOKEN_KEY = "FACEBOOK_PAGE_ACCESS_TOKEN"


class FacebookAdapter(PlatformAdapter):
    name = "facebook"

    def __init__(self, live_video_id: str = ""):
        self._live_video_id = live_video_id or str(
            config.get("live_comments.platforms.facebook.live_video_id", ""))
        self._since: float | None = None
        self._last_error = ""
        self._last_poll_ok: bool | None = None

    def _token(self) -> str | None:
        return secrets_store.get(_TOKEN_KEY)

    def is_authenticated(self) -> bool:
        return bool(self._token())

    def capabilities(self) -> PlatformCapabilities:
        if not bool(config.get("live_comments.platforms.facebook.enabled", False)):
            return PlatformCapabilities(False, False, True,
                                        "disabled in config (live_comments.platforms.facebook.enabled)")
        if not self._token():
            return PlatformCapabilities(False, False, True,
                                        "no Page access token in keyring "
                                        "(FACEBOOK_PAGE_ACCESS_TOKEN) — requires a Facebook "
                                        "Page + App Review for pages_read_engagement/"
                                        "pages_manage_engagement")
        if not self._live_video_id:
            return PlatformCapabilities(False, False, True,
                                        "no live_video_id configured")
        return PlatformCapabilities(True, True, False,
                                    "Graph API live-video comments — Page-owned content only")

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
            params = {"access_token": self._token(), "fields": "id,from,message,created_time"}
            if self._since:
                params["since"] = int(self._since)
            resp = requests.get(f"{_GRAPH_BASE}/{self._live_video_id}/comments",
                               params=params, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            events = []
            for item in data.get("data", []):
                text = item.get("message", "")
                if not text:
                    continue
                author = item.get("from", {}) or {}
                events.append(CommentEvent(
                    platform=self.name, comment_id=item.get("id", ""),
                    author_id=author.get("id", ""), author_name=author.get("name", ""),
                    text=text, timestamp=time.time(), stream_id=self._live_video_id))
            self._since = time.time()
            self._last_poll_ok = True
            self._last_error = ""
            return events
        except Exception as e:
            self._last_error = str(e)[:200]
            self._last_poll_ok = False
            _logger.warning("facebook.poll_failed", error=self._last_error)
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
            resp = requests.post(
                f"{_GRAPH_BASE}/{comment.comment_id}/comments",
                data={"message": text, "access_token": self._token()}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return ReplyResult(True, "sent", reply_id=data.get("id", ""))
        except Exception as e:
            return ReplyResult(False, str(e)[:200])

    def connection_health(self) -> dict:
        return {"platform": self.name, "connected": bool(self._last_poll_ok),
               "authenticated": self.is_authenticated(), "detail": self._last_error}
