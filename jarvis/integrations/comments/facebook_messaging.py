"""Official Facebook Page messaging lane, separate from Page comments."""
from __future__ import annotations

import time

from jarvis.core import config, log, secrets_store
from jarvis.integrations.comments.base import (
    CommentEvent,
    PlatformAdapter,
    PlatformCapabilities,
    ReplyResult,
)

_logger = log.get("comments.facebook_messaging")
_GRAPH_BASE = "https://graph.facebook.com/v19.0"
_TOKEN_KEY = "jarvis/facebook_messaging/page_access_token"
_PERMISSION = "pages_messaging"


class _GraphMessagingClient:
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
                        "author_name": author.get("name", ""),
                        "text": item.get("message", ""),
                        "timestamp": time.time(),
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


class FacebookMessagingAdapter(PlatformAdapter):
    """Capability-gated official Facebook Page DM adapter."""

    name = "facebook_messaging"

    def __init__(
        self,
        page_id: str = "",
        *,
        enabled: bool | None = None,
        token_getter=None,
        client=None,
    ) -> None:
        self._page_id = page_id or str(
            config.get("integrations.facebook_messaging.page_id", "")
        )
        self._enabled = enabled
        self._token_getter = token_getter or (lambda: secrets_store.get(_TOKEN_KEY))
        self._client = client or _GraphMessagingClient()
        self._seen_ids: set[str] = set()
        self._last_error = ""
        self._last_poll_ok: bool | None = None

    def _token(self) -> str | None:
        return self._token_getter()

    def _is_enabled(self) -> bool:
        if self._enabled is not None:
            return bool(self._enabled)
        return bool(
            config.get("integrations.facebook_messaging.enabled", False)
        )

    def is_authenticated(self) -> bool:
        return bool(self._token())

    def capabilities(self) -> PlatformCapabilities:
        if not self._is_enabled():
            return PlatformCapabilities(
                False,
                False,
                True,
                "disabled in config (integrations.facebook_messaging.enabled)",
            )
        token = self._token()
        if not token:
            return PlatformCapabilities(
                False,
                False,
                True,
                "no Page access token in keyring; manual draft only",
            )
        if not self._page_id:
            return PlatformCapabilities(False, False, True, "no Page id configured")
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
                "current pages_messaging permission is not proven; manual draft only",
            )
        return PlatformCapabilities(
            True,
            True,
            False,
            "official Meta Page Messaging API; current pages_messaging permission proven",
        )

    def poll_comments(self) -> list[CommentEvent]:
        capabilities = self.capabilities()
        if not capabilities.can_read:
            return []
        try:
            raw = self._client.poll_messages(self._page_id, self._token())
            events = []
            for item in raw:
                message_id = str(item.get("id", ""))
                text = str(item.get("text", ""))
                if not message_id or message_id in self._seen_ids or not text:
                    continue
                self._seen_ids.add(message_id)
                events.append(
                    CommentEvent(
                        platform=self.name,
                        comment_id=message_id,
                        author_id=str(item.get("author_id", "")),
                        author_name=str(item.get("author_name", "")),
                        text=text,
                        timestamp=float(item.get("timestamp", time.time())),
                        stream_id=str(item.get("conversation_id", "")),
                    )
                )
            self._last_poll_ok = True
            self._last_error = ""
            return events
        except Exception as exc:
            self._last_error = type(exc).__name__
            self._last_poll_ok = False
            _logger.warning("facebook_messaging.poll_failed", error=self._last_error)
            return []

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        capabilities = self.capabilities()
        if not capabilities.can_reply:
            return ReplyResult(False, capabilities.notes)
        try:
            result = self._client.send_message(
                self._page_id,
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


__all__ = ["FacebookMessagingAdapter"]
