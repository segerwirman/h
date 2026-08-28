"""Official Instagram messaging lane, separate from media comments."""
from __future__ import annotations

from datetime import datetime
import math
import time

from jarvis.core import config, log, secrets_store
from jarvis.integrations.comments.base import (
    CommentEvent,
    PlatformAdapter,
    PlatformCapabilities,
    ReplyResult,
)

_logger = log.get("comments.instagram_messaging")
_GRAPH_BASE = "https://graph.facebook.com/v19.0"
_TOKEN_KEY = "jarvis/instagram_messaging/access_token"
_PERMISSION = "instagram_manage_messages"


class _InstagramMessagingClient:
    def granted_permissions(self, token: str) -> set[str]:
        import requests

        response = requests.get(
            f"{_GRAPH_BASE}/me/permissions",
            params={"access_token": token},
            timeout=10,
        )
        response.raise_for_status()
        return {
            str(item.get("permission", ""))
            for item in response.json().get("data", [])
            if item.get("status") == "granted"
        }

    def poll_messages(self, account_id: str, token: str) -> list[dict]:
        import requests

        response = requests.get(
            f"{_GRAPH_BASE}/{account_id}/conversations",
            params={
                "access_token": token,
                "platform": "instagram",
                "fields": "id,messages.limit(25){id,from,message,created_time}",
            },
            timeout=10,
        )
        response.raise_for_status()
        messages: list[dict] = []
        for conversation in response.json().get("data", []):
            conversation_id = str(conversation.get("id", ""))
            for item in (conversation.get("messages", {}) or {}).get("data", []):
                author = item.get("from", {}) or {}
                messages.append(
                    {
                        "id": item.get("id", ""),
                        "author_id": author.get("id", ""),
                        "author_name": author.get("username", author.get("name", "")),
                        "text": item.get("message", ""),
                        "timestamp": _timestamp(item.get("created_time")),
                        "conversation_id": conversation_id,
                    }
                )
        return messages

    def send_message(
        self,
        account_id: str,
        recipient_id: str,
        text: str,
        token: str,
    ) -> dict:
        import requests

        response = requests.post(
            f"{_GRAPH_BASE}/{account_id}/messages",
            params={"access_token": token},
            json={"recipient": {"id": recipient_id}, "message": {"text": text}},
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
        return {"ok": True, "id": data.get("message_id", "")}


class InstagramMessagingAdapter(PlatformAdapter):
    """Capability-gated official Instagram professional-account DM adapter."""

    name = "instagram_messaging"

    def __init__(
        self,
        account_id: str = "",
        *,
        enabled: bool | None = None,
        token_getter=None,
        client=None,
        clock=time.time,
    ) -> None:
        self._account_id = account_id or str(
            config.get("integrations.instagram_messaging.account_id", "")
        )
        self._enabled = enabled
        self._token_getter = token_getter or (lambda: secrets_store.get(_TOKEN_KEY))
        self._client = client or _InstagramMessagingClient()
        self._clock = clock
        self._seen_ids: set[str] = set()
        self._startup_cutoff: float | None = None
        self._last_error = ""
        self._last_poll_ok: bool | None = None

    def _token(self) -> str | None:
        return self._token_getter()

    def _is_enabled(self) -> bool:
        if self._enabled is not None:
            return bool(self._enabled)
        return bool(
            config.get("integrations.instagram_messaging.enabled", False)
        )

    def is_authenticated(self) -> bool:
        return bool(self._token())

    def capabilities(self) -> PlatformCapabilities:
        if not self._is_enabled():
            return PlatformCapabilities(
                False,
                False,
                True,
                "disabled in config (integrations.instagram_messaging.enabled)",
            )
        token = self._token()
        if not token:
            return PlatformCapabilities(
                False,
                False,
                True,
                "no Instagram access token in keyring; manual draft only",
            )
        if not self._account_id:
            return PlatformCapabilities(False, False, True, "no account id configured")
        try:
            permissions = self._client.granted_permissions(token)
        except Exception as exc:
            self._last_error = type(exc).__name__
            return PlatformCapabilities(
                False,
                False,
                True,
                "current official Meta permissions could not be proven; manual draft only",
            )
        if _PERMISSION not in permissions:
            return PlatformCapabilities(
                False,
                False,
                True,
                "current instagram_manage_messages permission is not proven; manual draft only",
            )
        return PlatformCapabilities(
            True,
            True,
            False,
            "official Instagram Messaging API; current instagram_manage_messages permission proven",
        )

    def poll_comments(self) -> list[CommentEvent]:
        capabilities = self.capabilities()
        if not capabilities.can_read:
            return []
        try:
            poll_started_at = _finite_timestamp(self._clock())
            if poll_started_at is None:
                raise ValueError("invalid poll clock")
            raw = self._client.poll_messages(self._account_id, self._token())
            events = []
            watermark_only = self._startup_cutoff is None
            cutoff = poll_started_at if watermark_only else self._startup_cutoff
            for item in raw:
                message_id = str(item.get("id", ""))
                author_id = str(item.get("author_id", ""))
                text = str(item.get("text", ""))
                if not message_id or message_id in self._seen_ids:
                    continue
                self._seen_ids.add(message_id)
                timestamp = _finite_timestamp(item.get("timestamp"))
                if (
                    watermark_only
                    or author_id == self._account_id
                    or not text
                    or timestamp is None
                    or timestamp <= cutoff
                ):
                    continue
                events.append(
                    CommentEvent(
                        platform=self.name,
                        comment_id=message_id,
                        author_id=author_id,
                        author_name=str(item.get("author_name", "")),
                        text=text,
                        timestamp=timestamp,
                        stream_id=str(item.get("conversation_id", "")),
                    )
                )
            if watermark_only:
                self._startup_cutoff = poll_started_at
            self._last_poll_ok = True
            self._last_error = ""
            return events
        except Exception as exc:
            self._last_error = type(exc).__name__
            self._last_poll_ok = False
            _logger.warning("instagram_messaging.poll_failed", error=self._last_error)
            return []

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        capabilities = self.capabilities()
        if not capabilities.can_reply:
            return ReplyResult(False, capabilities.notes)
        try:
            result = self._client.send_message(
                self._account_id,
                comment.author_id,
                text,
                self._token(),
            )
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


def _timestamp(value) -> float | None:
    if isinstance(value, str) and value:
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return _finite_timestamp(value)


def _finite_timestamp(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        timestamp = float(value)
    except (TypeError, ValueError):
        return None
    return timestamp if math.isfinite(timestamp) else None


__all__ = ["InstagramMessagingAdapter"]
