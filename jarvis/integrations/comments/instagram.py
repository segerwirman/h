"""Instagram live-video comments adapter (redesign §15).

Uses the real Meta Graph API shape for Instagram professional (Business/
Creator) accounts connected to a Facebook Page: ``GET /{ig_media_id}/comments``
to read, ``POST /{comment_id}/replies`` to reply. This requires:
  * an Instagram professional account linked to a Facebook Page,
  * a Page/IG access token with ``instagram_manage_comments``,
  * Meta App Review approval for that permission in production.

Personal Instagram accounts are not supported by this API surface at all —
there is no path to make that "work" honestly, so this adapter never
attempts it. Token lives in ``jarvis.core.secrets_store`` (OS keyring),
never config.yaml. Without a token and a configured media id,
``capabilities()`` reports manual-approval-required. Cannot be
smoke-tested here (no credentials/network in this environment).
"""
from __future__ import annotations

import time

from jarvis.core import config, log, secrets_store
from jarvis.integrations.comments.base import (CommentEvent, PlatformAdapter,
                                               PlatformCapabilities, ReplyResult)
from jarvis.integrations.comments.meta_graph import GRAPH_API_BASE

_logger = log.get("comments.instagram")
_TOKEN_KEY = "INSTAGRAM_ACCESS_TOKEN"


class InstagramAdapter(PlatformAdapter):
    name = "instagram"

    def __init__(self, media_id: str = ""):
        self._media_id = media_id or str(
            config.get("live_comments.platforms.instagram.media_id", ""))
        self._last_error = ""
        self._last_poll_ok: bool | None = None
        self._seen_ids: set[str] = set()

    def _token(self) -> str | None:
        return secrets_store.get(_TOKEN_KEY)

    def is_authenticated(self) -> bool:
        return bool(self._token())

    def capabilities(self) -> PlatformCapabilities:
        if not bool(config.get("live_comments.platforms.instagram.enabled", False)):
            return PlatformCapabilities(False, False, True,
                                        "disabled in config (live_comments.platforms.instagram.enabled)")
        if not self._token():
            return PlatformCapabilities(False, False, True,
                                        "no access token in keyring (INSTAGRAM_ACCESS_TOKEN) — "
                                        "requires a professional account linked to a Facebook "
                                        "Page + App Review for instagram_manage_comments. "
                                        "Personal accounts are not supported by this API at all.")
        if not self._media_id:
            return PlatformCapabilities(False, False, True, "no media_id configured")
        return PlatformCapabilities(True, True, False,
                                    "Graph API media comments — professional accounts only")

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
            resp = requests.get(
                f"{GRAPH_API_BASE}/{self._media_id}/comments",
                params={"access_token": self._token(), "fields": "id,username,text,timestamp"},
                timeout=10)
            resp.raise_for_status()
            data = resp.json()
            events = []
            for item in data.get("data", []):
                cid = item.get("id", "")
                if not cid or cid in self._seen_ids:
                    continue
                self._seen_ids.add(cid)
                text = item.get("text", "")
                if not text:
                    continue
                events.append(CommentEvent(
                    platform=self.name, comment_id=cid,
                    author_id=item.get("username", ""), author_name=item.get("username", ""),
                    text=text, timestamp=time.time(), stream_id=self._media_id))
            self._last_poll_ok = True
            self._last_error = ""
            return events
        except Exception as e:
            self._last_error = str(e)[:200]
            self._last_poll_ok = False
            _logger.warning("instagram.poll_failed", error=self._last_error)
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
                f"{GRAPH_API_BASE}/{comment.comment_id}/replies",
                data={"message": text, "access_token": self._token()}, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return ReplyResult(True, "sent", reply_id=data.get("id", ""))
        except Exception as e:
            return ReplyResult(False, str(e)[:200])

    def connection_health(self) -> dict:
        return {"platform": self.name, "connected": bool(self._last_poll_ok),
               "authenticated": self.is_authenticated(), "detail": self._last_error}
