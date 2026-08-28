"""YouTube ordinary video-comments lane, separate from live chat."""
from __future__ import annotations

from datetime import datetime
import time

from jarvis.core import config
from jarvis.integrations.comments import youtube_api, youtube_oauth
from jarvis.integrations.comments.base import (
    CommentEvent,
    PlatformAdapter,
    PlatformCapabilities,
    ReplyResult,
)


class YouTubeCommentsAdapter(PlatformAdapter):
    """Adapt ordinary commentThreads/comments APIs to PlatformAdapter."""

    name = "youtube_comments"

    def __init__(
        self,
        video_id: str = "",
        *,
        enabled: bool | None = None,
        api_key_getter=None,
        token_getter=None,
        reader=None,
        replier=None,
    ) -> None:
        self._video_id = video_id or str(
            config.get("live_comments.platforms.youtube_comments.video_id", "")
        )
        self._enabled = enabled
        self._api_key_getter = api_key_getter or youtube_oauth.api_key
        self._token_getter = token_getter or youtube_oauth.access_token
        self._reader = reader or youtube_api.read_video_comments
        self._replier = replier or youtube_api.reply_video_comment
        self._seen_ids: set[str] = set()
        self._last_error = ""
        self._last_poll_ok: bool | None = None

    def _is_enabled(self) -> bool:
        if self._enabled is not None:
            return bool(self._enabled)
        return bool(
            config.get("live_comments.platforms.youtube_comments.enabled", False)
        )

    def is_authenticated(self) -> bool:
        return bool(self._token_getter())

    def capabilities(self) -> PlatformCapabilities:
        if not self._is_enabled():
            return PlatformCapabilities(
                False,
                False,
                True,
                "disabled in config (live_comments.platforms.youtube_comments.enabled)",
            )
        if not self._video_id:
            return PlatformCapabilities(False, False, True, "no video id configured")
        if not self._api_key_getter():
            return PlatformCapabilities(
                False,
                False,
                True,
                "no YouTube Data API key in keyring; manual draft only",
            )
        if not self._token_getter():
            return PlatformCapabilities(
                True,
                False,
                True,
                "ordinary comments are readable; OAuth reply permission is not proven",
            )
        return PlatformCapabilities(
            True,
            True,
            False,
            "official YouTube commentThreads.list/comments.insert permissions available",
        )

    def poll_comments(self) -> list[CommentEvent]:
        capabilities = self.capabilities()
        if not capabilities.can_read:
            return []
        try:
            events = []
            for item in self._reader(self._video_id):
                comment_id = str(item.get("comment_id", ""))
                text = str(item.get("text", ""))
                if not comment_id or comment_id in self._seen_ids or not text:
                    continue
                self._seen_ids.add(comment_id)
                events.append(
                    CommentEvent(
                        platform=self.name,
                        comment_id=comment_id,
                        author_id=str(item.get("author_id", "")),
                        author_name=str(item.get("author", "")),
                        text=text,
                        timestamp=_timestamp(item.get("timestamp")),
                        stream_id=self._video_id,
                        meta={"likes": int(item.get("likes", 0) or 0)},
                    )
                )
            self._last_poll_ok = True
            self._last_error = ""
            return events
        except Exception as exc:
            self._last_error = type(exc).__name__
            self._last_poll_ok = False
            return []

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        capabilities = self.capabilities()
        if not capabilities.can_reply:
            return ReplyResult(False, capabilities.notes)
        try:
            result = self._replier(comment.comment_id, text)
        except Exception as exc:
            return ReplyResult(False, type(exc).__name__)
        if result.get("ok"):
            return ReplyResult(True, "sent", reply_id=str(result.get("id", "")))
        return ReplyResult(False, str(result.get("error", "send failed"))[:200])

    def connection_health(self) -> dict:
        return {
            "platform": self.name,
            "connected": bool(self._last_poll_ok),
            "authenticated": self.is_authenticated(),
            "detail": self._last_error,
        }


def _timestamp(value) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            pass
    return time.time()


__all__ = ["YouTubeCommentsAdapter"]
