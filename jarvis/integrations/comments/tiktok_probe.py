"""Fail-closed TikTok official-capability probe adapter."""
from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.core import config, secrets_store
from jarvis.integrations.comments.base import (
    CommentEvent,
    PlatformAdapter,
    PlatformCapabilities,
    ReplyResult,
)

_TOKEN_KEY = "jarvis/tiktok/comments_access_token"
_REQUIRED_PERMISSIONS = frozenset({"comments.read", "comments.reply"})


@dataclass(frozen=True)
class TikTokCapabilityProof:
    """Bounded current-account proof returned by an official API client."""

    official_api: bool = False
    can_read: bool = False
    can_reply: bool = False
    permissions: frozenset[str] = field(default_factory=frozenset)
    notes: str = ""


class TikTokProbeAdapter(PlatformAdapter):
    """Expose TikTok only after an injected official client proves both lanes."""

    name = "tiktok"

    def __init__(
        self,
        *,
        enabled: bool | None = None,
        token_getter=None,
        client=None,
    ) -> None:
        self._enabled = enabled
        self._token_getter = token_getter or (lambda: secrets_store.get(_TOKEN_KEY))
        self._client = client
        self._proof: TikTokCapabilityProof | None = None
        self._last_error = ""
        self._last_poll_ok: bool | None = None

    def _is_enabled(self) -> bool:
        if self._enabled is not None:
            return bool(self._enabled)
        return bool(config.get("live_comments.platforms.tiktok.enabled", False))

    def _token(self) -> str | None:
        return self._token_getter()

    def is_authenticated(self) -> bool:
        return bool(self._token())

    def capabilities(self) -> PlatformCapabilities:
        if not self._is_enabled():
            return PlatformCapabilities(
                False,
                False,
                True,
                "disabled in config (live_comments.platforms.tiktok.enabled)",
            )
        token = self._token()
        if not token:
            return PlatformCapabilities(
                False,
                False,
                True,
                "no TikTok token in keyring; official read and reply permissions are not proven",
            )
        if self._client is None:
            return PlatformCapabilities(
                False,
                False,
                True,
                "no supported official TikTok comments client; manual draft only",
            )
        try:
            proof = self._client.probe(token)
        except Exception as exc:
            self._last_error = type(exc).__name__
            self._proof = None
            return PlatformCapabilities(
                False,
                False,
                True,
                "official TikTok capability probe failed; manual draft only",
            )
        self._proof = proof
        proven = bool(
            proof.official_api
            and proof.can_read
            and proof.can_reply
            and _REQUIRED_PERMISSIONS <= frozenset(proof.permissions)
        )
        if not proven:
            return PlatformCapabilities(
                False,
                False,
                True,
                "official read and reply permissions are not proven; manual draft only",
            )
        return PlatformCapabilities(
            True,
            True,
            False,
            "official TikTok API and current comments.read/comments.reply permissions proven",
        )

    def poll_comments(self) -> list[CommentEvent]:
        capabilities = self.capabilities()
        if not capabilities.can_read:
            return []
        try:
            events = []
            for item in self._client.poll_comments(self._token()):
                comment_id = str(item.get("comment_id", item.get("id", "")))
                text = str(item.get("text", ""))
                if not comment_id or not text:
                    continue
                events.append(
                    CommentEvent(
                        platform=self.name,
                        comment_id=comment_id,
                        author_id=str(item.get("author_id", "")),
                        author_name=str(item.get("author_name", "")),
                        text=text,
                        timestamp=float(item.get("timestamp", 0.0) or 0.0),
                        stream_id=str(item.get("video_id", "")),
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
            result = self._client.send_reply(comment.comment_id, text, self._token())
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


__all__ = ["TikTokCapabilityProof", "TikTokProbeAdapter"]
