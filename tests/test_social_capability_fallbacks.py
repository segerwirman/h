"""Offline contracts for official social lanes and fail-closed fallbacks."""
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.integrations.comments.base import (
    CommentEvent,
    CommentManager,
    PlatformAdapter,
    PlatformCapabilities,
    ReplyResult,
)
from jarvis.integrations.comments.deterministic_reply import DeterministicReplyPolicy
from jarvis.integrations.comments.facebook import FacebookAdapter
from jarvis.integrations.comments.factory import build_adapters, build_runtime
from jarvis.integrations.comments.facebook_messaging import FacebookMessagingAdapter
from jarvis.integrations.comments.instagram import InstagramAdapter
from jarvis.integrations.comments.instagram_messaging import InstagramMessagingAdapter
from jarvis.integrations.comments.runtime import DeterministicReplyHandler
from jarvis.integrations.comments.tiktok_probe import (
    TikTokCapabilityProof,
    TikTokProbeAdapter,
)
from jarvis.integrations.comments.youtube import YouTubeAdapter
from jarvis.integrations.comments.youtube_comments import YouTubeCommentsAdapter


class _Audit:
    def __init__(self) -> None:
        self.events: list[dict] = []

    def record(self, **fields) -> None:
        self.events.append(dict(fields))


class _MetaClient:
    def __init__(self, permissions: set[str]) -> None:
        self.permissions = permissions
        self.permission_calls = 0
        self.poll_calls = 0
        self.send_calls = 0

    def granted_permissions(self, token: str) -> set[str]:
        assert token == "offline-meta-token"
        self.permission_calls += 1
        return set(self.permissions)

    def poll_messages(self, account_id: str, token: str) -> list[dict]:
        assert account_id in {"page-1", "ig-1"}
        assert token == "offline-meta-token"
        self.poll_calls += 1
        return [
            {
                "id": "message-1",
                "author_id": "author-1",
                "author_name": "Offline User",
                "text": "halo",
                "timestamp": 10.0,
                "conversation_id": "conversation-1",
            }
        ]

    def send_message(
        self,
        account_id: str,
        recipient_id: str,
        text: str,
        token: str,
    ) -> dict:
        assert account_id in {"page-1", "ig-1"}
        assert recipient_id == "author-1"
        assert text == "Halo juga!"
        assert token == "offline-meta-token"
        self.send_calls += 1
        return {"ok": True, "id": "reply-1"}


def test_meta_messaging_lanes_are_separate_and_permission_proven():
    facebook_client = _MetaClient({"pages_messaging"})
    instagram_client = _MetaClient({"instagram_manage_messages"})
    facebook = FacebookMessagingAdapter(
        page_id="page-1",
        enabled=True,
        token_getter=lambda: "offline-meta-token",
        client=facebook_client,
    )
    instagram = InstagramMessagingAdapter(
        account_id="ig-1",
        enabled=True,
        token_getter=lambda: "offline-meta-token",
        client=instagram_client,
    )

    assert facebook.name == "facebook_messaging"
    assert instagram.name == "instagram_messaging"
    assert facebook.name != FacebookAdapter.name
    assert instagram.name != InstagramAdapter.name
    assert facebook.capabilities() == PlatformCapabilities(
        True,
        True,
        False,
        "official Meta Page Messaging API; current pages_messaging permission proven",
    )
    assert instagram.capabilities() == PlatformCapabilities(
        True,
        True,
        False,
        "official Instagram Messaging API; current instagram_manage_messages permission proven",
    )

    assert facebook.poll_comments() == []
    assert instagram.poll_comments() == []
    facebook_event = CommentEvent(
        "facebook_messaging",
        "message-2",
        "author-1",
        "Offline User",
        "halo",
        11.0,
    )
    instagram_event = CommentEvent(
        "instagram_messaging",
        "message-2",
        "author-1",
        "Offline User",
        "halo",
        11.0,
    )
    assert facebook.send_reply(facebook_event, "Halo juga!").ok is True
    assert instagram.send_reply(instagram_event, "Halo juga!").ok is True
    assert facebook_client.poll_calls == facebook_client.send_calls == 1
    assert instagram_client.poll_calls == instagram_client.send_calls == 1


@pytest.mark.parametrize(
    ("adapter_type", "account_id", "permission"),
    [
        (FacebookMessagingAdapter, "page-1", "pages_messaging"),
        (InstagramMessagingAdapter, "ig-1", "instagram_manage_messages"),
    ],
)
def test_meta_messaging_first_poll_watermarks_history_then_emits_only_new_inbound(
    adapter_type,
    account_id,
    permission,
):
    class _HistoryClient(_MetaClient):
        def __init__(self) -> None:
            super().__init__({permission})
            self.responses = [
                [
                    {
                        "id": "history-inbound",
                        "author_id": "author-1",
                        "author_name": "Offline User",
                        "text": "bagus",
                        "timestamp": 10.0,
                        "conversation_id": "conversation-1",
                    },
                    {
                        "id": "history-outbound",
                        "author_id": account_id,
                        "author_name": "Managed Account",
                        "text": "Terima kasih kembali!",
                        "timestamp": 11.0,
                        "conversation_id": "conversation-1",
                    },
                ],
                [
                    {
                        "id": "history-inbound",
                        "author_id": "author-1",
                        "author_name": "Offline User",
                        "text": "bagus",
                        "timestamp": 10.0,
                        "conversation_id": "conversation-1",
                    },
                    {
                        "id": "new-outbound",
                        "author_id": account_id,
                        "author_name": "Managed Account",
                        "text": "Terima kasih kembali!",
                        "timestamp": 12.0,
                        "conversation_id": "conversation-1",
                    },
                    {
                        "id": "new-inbound",
                        "author_id": "author-2",
                        "author_name": "New User",
                        "text": "halo",
                        "timestamp": 13.0,
                        "conversation_id": "conversation-2",
                    },
                ],
            ]

        def poll_messages(self, requested_account_id: str, token: str) -> list[dict]:
            assert requested_account_id == account_id
            assert token == "offline-meta-token"
            self.poll_calls += 1
            return self.responses.pop(0)

    client = _HistoryClient()
    kwargs = {
        "enabled": True,
        "token_getter": lambda: "offline-meta-token",
        "client": client,
        "clock": lambda: 12.0,
    }
    if adapter_type is FacebookMessagingAdapter:
        kwargs["page_id"] = account_id
    else:
        kwargs["account_id"] = account_id
    adapter = adapter_type(**kwargs)

    assert adapter.poll_comments() == [], "startup history must be watermark-only"
    events = adapter.poll_comments()

    assert [event.comment_id for event in events] == ["new-inbound"]
    assert events[0].author_id == "author-2"
    assert events[0].timestamp == 13.0


@pytest.mark.parametrize(
    ("adapter_type", "account_id", "permission"),
    [
        (FacebookMessagingAdapter, "page-1", "pages_messaging"),
        (InstagramMessagingAdapter, "ig-1", "instagram_manage_messages"),
    ],
)
def test_meta_messaging_cutoff_rejects_unseen_history_and_ambiguous_timestamps(
    adapter_type,
    account_id,
    permission,
):
    class _CutoffClient(_MetaClient):
        def __init__(self) -> None:
            super().__init__({permission})
            self.responses = [
                [
                    {
                        "id": "startup-visible",
                        "author_id": "author-1",
                        "author_name": "Offline User",
                        "text": "halo",
                        "timestamp": 90.0,
                        "conversation_id": "conversation-1",
                    }
                ],
                [
                    {
                        "id": "new-inbound",
                        "author_id": "author-2",
                        "author_name": "New User",
                        "text": "halo",
                        "timestamp": 101.0,
                        "conversation_id": "conversation-2",
                    },
                    {
                        "id": "old-unseen-history",
                        "author_id": "author-2",
                        "author_name": "New User",
                        "text": "bagus",
                        "timestamp": 80.0,
                        "conversation_id": "conversation-2",
                    },
                    {
                        "id": "at-cutoff",
                        "author_id": "author-3",
                        "author_name": "Boundary User",
                        "text": "halo",
                        "timestamp": 100.0,
                        "conversation_id": "conversation-3",
                    },
                    {
                        "id": "missing-timestamp",
                        "author_id": "author-4",
                        "author_name": "Unknown Time",
                        "text": "halo",
                        "conversation_id": "conversation-4",
                    },
                    {
                        "id": "invalid-timestamp",
                        "author_id": "author-5",
                        "author_name": "Invalid Time",
                        "text": "halo",
                        "timestamp": "not-a-timestamp",
                        "conversation_id": "conversation-5",
                    },
                    {
                        "id": "non-finite-timestamp",
                        "author_id": "author-6",
                        "author_name": "Infinite Time",
                        "text": "halo",
                        "timestamp": float("inf"),
                        "conversation_id": "conversation-6",
                    },
                    {
                        "id": "new-self-message",
                        "author_id": account_id,
                        "author_name": "Managed Account",
                        "text": "Terima kasih kembali!",
                        "timestamp": 102.0,
                        "conversation_id": "conversation-2",
                    },
                    {
                        "id": "startup-visible",
                        "author_id": "author-1",
                        "author_name": "Offline User",
                        "text": "halo",
                        "timestamp": 103.0,
                        "conversation_id": "conversation-1",
                    },
                ],
                [
                    {
                        "id": "old-unseen-history",
                        "author_id": "author-2",
                        "author_name": "New User",
                        "text": "bagus",
                        "timestamp": 80.0,
                        "conversation_id": "conversation-2",
                    },
                    {
                        "id": "newer-inbound",
                        "author_id": "author-7",
                        "author_name": "Newest User",
                        "text": "halo",
                        "timestamp": 104.0,
                        "conversation_id": "conversation-7",
                    },
                ],
            ]

        def poll_messages(self, requested_account_id: str, token: str) -> list[dict]:
            assert requested_account_id == account_id
            assert token == "offline-meta-token"
            self.poll_calls += 1
            return self.responses.pop(0)

    kwargs = {
        "enabled": True,
        "token_getter": lambda: "offline-meta-token",
        "client": _CutoffClient(),
        "clock": lambda: 100.0,
    }
    if adapter_type is FacebookMessagingAdapter:
        kwargs["page_id"] = account_id
    else:
        kwargs["account_id"] = account_id
    adapter = adapter_type(**kwargs)

    assert adapter.poll_comments() == []
    second = adapter.poll_comments()
    third = adapter.poll_comments()

    assert [event.comment_id for event in second] == ["new-inbound"]
    assert [event.comment_id for event in third] == ["newer-inbound"]


@pytest.mark.parametrize(
    ("adapter_type", "account_id", "permission"),
    [
        (FacebookMessagingAdapter, "page-1", "pages_messaging"),
        (InstagramMessagingAdapter, "ig-1", "instagram_manage_messages"),
    ],
)
def test_meta_messaging_failed_first_poll_does_not_commit_startup_cutoff(
    adapter_type,
    account_id,
    permission,
):
    class _RecoveringClient(_MetaClient):
        def __init__(self) -> None:
            super().__init__({permission})
            self.poll_attempts = 0

        def poll_messages(self, requested_account_id: str, token: str) -> list[dict]:
            assert requested_account_id == account_id
            assert token == "offline-meta-token"
            self.poll_attempts += 1
            if self.poll_attempts == 1:
                raise RuntimeError("offline first poll failure")
            if self.poll_attempts == 2:
                return [
                    {
                        "id": "recovery-history",
                        "author_id": "author-1",
                        "author_name": "Offline User",
                        "text": "bagus",
                        "timestamp": 150.0,
                        "conversation_id": "conversation-1",
                    }
                ]
            return [
                {
                    "id": "post-recovery",
                    "author_id": "author-2",
                    "author_name": "New User",
                    "text": "halo",
                    "timestamp": 201.0,
                    "conversation_id": "conversation-2",
                }
            ]

    clock_values = iter((100.0, 200.0, 300.0))
    kwargs = {
        "enabled": True,
        "token_getter": lambda: "offline-meta-token",
        "client": _RecoveringClient(),
        "clock": lambda: next(clock_values),
    }
    if adapter_type is FacebookMessagingAdapter:
        kwargs["page_id"] = account_id
    else:
        kwargs["account_id"] = account_id
    adapter = adapter_type(**kwargs)

    assert adapter.poll_comments() == []
    assert adapter.poll_comments() == [], "first successful poll stays watermark-only"
    assert [event.comment_id for event in adapter.poll_comments()] == ["post-recovery"]


class _OfflineMetaResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return self._payload


def test_facebook_comments_v26_contract_preserves_request_shape(monkeypatch):
    import requests

    calls: list[tuple[str, str, dict]] = []

    def fake_get(url: str, **kwargs):
        calls.append(("GET", url, kwargs))
        return _OfflineMetaResponse({"data": []})

    def fake_post(url: str, **kwargs):
        calls.append(("POST", url, kwargs))
        return _OfflineMetaResponse({"id": "offline-reply-1"})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    adapter = FacebookAdapter(live_video_id="offline-live-1")
    monkeypatch.setattr(
        adapter,
        "capabilities",
        lambda: PlatformCapabilities(True, True, False, "offline contract"),
    )
    monkeypatch.setattr(adapter, "_token", lambda: "offline-meta-token")
    comment = CommentEvent(
        "facebook",
        "offline-comment-1",
        "offline-author-1",
        "Offline User",
        "halo",
        1.0,
    )

    assert adapter.poll_comments() == []
    assert adapter.send_reply(comment, "Halo juga!").ok is True

    assert calls == [
        (
            "GET",
            "https://graph.facebook.com/v26.0/offline-live-1/comments",
            {
                "params": {
                    "access_token": "offline-meta-token",
                    "fields": "id,from,message,created_time",
                },
                "timeout": 10,
            },
        ),
        (
            "POST",
            "https://graph.facebook.com/v26.0/offline-comment-1/comments",
            {
                "data": {
                    "message": "Halo juga!",
                    "access_token": "offline-meta-token",
                },
                "timeout": 10,
            },
        ),
    ]
    assert all("/v19.0/" not in url for _, url, _ in calls)


def test_instagram_comments_v26_contract_preserves_request_shape(monkeypatch):
    import requests

    calls: list[tuple[str, str, dict]] = []

    def fake_get(url: str, **kwargs):
        calls.append(("GET", url, kwargs))
        return _OfflineMetaResponse({"data": []})

    def fake_post(url: str, **kwargs):
        calls.append(("POST", url, kwargs))
        return _OfflineMetaResponse({"id": "offline-reply-1"})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    adapter = InstagramAdapter(media_id="offline-media-1")
    monkeypatch.setattr(
        adapter,
        "capabilities",
        lambda: PlatformCapabilities(True, True, False, "offline contract"),
    )
    monkeypatch.setattr(adapter, "_token", lambda: "offline-meta-token")
    comment = CommentEvent(
        "instagram",
        "offline-comment-1",
        "offline-author-1",
        "Offline User",
        "halo",
        1.0,
    )

    assert adapter.poll_comments() == []
    assert adapter.send_reply(comment, "Halo juga!").ok is True

    assert calls == [
        (
            "GET",
            "https://graph.facebook.com/v26.0/offline-media-1/comments",
            {
                "params": {
                    "access_token": "offline-meta-token",
                    "fields": "id,username,text,timestamp",
                },
                "timeout": 10,
            },
        ),
        (
            "POST",
            "https://graph.facebook.com/v26.0/offline-comment-1/replies",
            {
                "data": {
                    "message": "Halo juga!",
                    "access_token": "offline-meta-token",
                },
                "timeout": 10,
            },
        ),
    ]
    assert all("/v19.0/" not in url for _, url, _ in calls)


def test_facebook_messaging_v26_contract_preserves_request_shape(monkeypatch):
    import requests

    from jarvis.integrations.comments import facebook_messaging

    calls: list[tuple[str, str, dict]] = []

    def fake_get(url: str, **kwargs):
        calls.append(("GET", url, kwargs))
        if url.endswith("/me/permissions"):
            return _OfflineMetaResponse(
                {"data": [{"permission": "pages_messaging", "status": "granted"}]}
            )
        return _OfflineMetaResponse({"data": []})

    def fake_post(url: str, **kwargs):
        calls.append(("POST", url, kwargs))
        return _OfflineMetaResponse({"message_id": "offline-message-1"})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    client = facebook_messaging._GraphMessagingClient()

    assert client.granted_permissions("offline-meta-token") == {"pages_messaging"}
    assert client.poll_messages("offline-page-1", "offline-meta-token") == []
    assert client.send_message(
        "offline-page-1",
        "offline-author-1",
        "Halo juga!",
        "offline-meta-token",
    ) == {"ok": True, "id": "offline-message-1"}

    assert calls == [
        (
            "GET",
            "https://graph.facebook.com/v26.0/me/permissions",
            {"params": {"access_token": "offline-meta-token"}, "timeout": 10},
        ),
        (
            "GET",
            "https://graph.facebook.com/v26.0/offline-page-1/conversations",
            {
                "params": {
                    "access_token": "offline-meta-token",
                    "fields": "id,messages.limit(25){id,from,message,created_time}",
                },
                "timeout": 10,
            },
        ),
        (
            "POST",
            "https://graph.facebook.com/v26.0/offline-page-1/messages",
            {
                "params": {"access_token": "offline-meta-token"},
                "json": {
                    "recipient": {"id": "offline-author-1"},
                    "message": {"text": "Halo juga!"},
                },
                "timeout": 10,
            },
        ),
    ]
    assert all("/v19.0/" not in url for _, url, _ in calls)


def test_instagram_messaging_v26_contract_preserves_request_shape(monkeypatch):
    import requests

    from jarvis.integrations.comments import instagram_messaging

    calls: list[tuple[str, str, dict]] = []

    def fake_get(url: str, **kwargs):
        calls.append(("GET", url, kwargs))
        if url.endswith("/me/permissions"):
            return _OfflineMetaResponse(
                {
                    "data": [
                        {
                            "permission": "instagram_manage_messages",
                            "status": "granted",
                        }
                    ]
                }
            )
        return _OfflineMetaResponse({"data": []})

    def fake_post(url: str, **kwargs):
        calls.append(("POST", url, kwargs))
        return _OfflineMetaResponse({"message_id": "offline-message-1"})

    monkeypatch.setattr(requests, "get", fake_get)
    monkeypatch.setattr(requests, "post", fake_post)
    client = instagram_messaging._InstagramMessagingClient()

    assert client.granted_permissions("offline-meta-token") == {
        "instagram_manage_messages"
    }
    assert client.poll_messages("offline-ig-1", "offline-meta-token") == []
    assert client.send_message(
        "offline-ig-1",
        "offline-author-1",
        "Halo juga!",
        "offline-meta-token",
    ) == {"ok": True, "id": "offline-message-1"}

    assert calls == [
        (
            "GET",
            "https://graph.facebook.com/v26.0/me/permissions",
            {"params": {"access_token": "offline-meta-token"}, "timeout": 10},
        ),
        (
            "GET",
            "https://graph.facebook.com/v26.0/offline-ig-1/conversations",
            {
                "params": {
                    "access_token": "offline-meta-token",
                    "platform": "instagram",
                    "fields": "id,messages.limit(25){id,from,message,created_time}",
                },
                "timeout": 10,
            },
        ),
        (
            "POST",
            "https://graph.facebook.com/v26.0/offline-ig-1/messages",
            {
                "params": {"access_token": "offline-meta-token"},
                "json": {
                    "recipient": {"id": "offline-author-1"},
                    "message": {"text": "Halo juga!"},
                },
                "timeout": 10,
            },
        ),
    ]
    assert all("/v19.0/" not in url for _, url, _ in calls)


@pytest.mark.parametrize(
    ("client_type", "account_id", "author_name"),
    [
        ("facebook", "page-1", "Offline Page User"),
        ("instagram", "ig-1", "Offline IG User"),
    ],
)
def test_meta_graph_clients_preserve_created_time_and_fail_closed_when_invalid(
    monkeypatch,
    client_type,
    account_id,
    author_name,
):
    from jarvis.integrations.comments import (
        facebook_messaging,
        instagram_messaging,
    )

    class _Response:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict:
            author = {"id": "author-1", "name": author_name}
            if client_type == "instagram":
                author["username"] = author_name
            return {
                "data": [
                    {
                        "id": "conversation-1",
                        "messages": {
                            "data": [
                                {
                                    "id": "message-1",
                                    "from": author,
                                    "message": "halo",
                                    "created_time": "2026-08-28T10:00:00+0000",
                                },
                                {
                                    "id": "message-missing-time",
                                    "from": author,
                                    "message": "missing",
                                },
                                {
                                    "id": "message-invalid-time",
                                    "from": author,
                                    "message": "invalid",
                                    "created_time": "not-a-timestamp",
                                },
                            ]
                        },
                    }
                ]
            }

    def fake_get(*_args, **_kwargs):
        return _Response()

    import requests

    monkeypatch.setattr(requests, "get", fake_get)
    if client_type == "facebook":
        client = facebook_messaging._GraphMessagingClient()
    else:
        client = instagram_messaging._InstagramMessagingClient()

    messages = client.poll_messages(account_id, "offline-meta-token")

    assert messages[0]["timestamp"] == 1787911200.0
    assert messages[1]["timestamp"] is None
    assert messages[2]["timestamp"] is None


def test_meta_messaging_fails_closed_without_current_permission_or_token():
    client = _MetaClient(set())
    no_permission = FacebookMessagingAdapter(
        page_id="page-1",
        enabled=True,
        token_getter=lambda: "offline-meta-token",
        client=client,
    )
    no_token = InstagramMessagingAdapter(
        account_id="ig-1",
        enabled=True,
        token_getter=lambda: None,
        client=client,
    )
    comment = CommentEvent(
        "facebook_messaging",
        "message-1",
        "author-1",
        "Offline User",
        "halo",
        10.0,
    )

    denied = no_permission.capabilities()
    assert denied.can_read is False
    assert denied.can_reply is False
    assert denied.requires_manual_approval is True
    assert "not proven" in denied.notes
    assert no_permission.poll_comments() == []
    assert no_permission.send_reply(comment, "Halo juga!").ok is False

    missing = no_token.capabilities()
    assert missing.can_read is False
    assert missing.can_reply is False
    assert missing.requires_manual_approval is True
    assert client.poll_calls == 0
    assert client.send_calls == 0


def test_youtube_ordinary_comments_are_a_separate_capability_gated_lane():
    replies: list[tuple[str, str]] = []
    adapter = YouTubeCommentsAdapter(
        video_id="video-1",
        enabled=True,
        api_key_getter=lambda: "offline-api-key",
        token_getter=lambda: "offline-oauth-token",
        reader=lambda video_id: [
            {
                "comment_id": "comment-1",
                "author_id": "channel-1",
                "author": "Offline Channel",
                "text": "halo",
                "timestamp": 12.0,
            }
        ],
        replier=lambda comment_id, text: (
            replies.append((comment_id, text))
            or {"ok": True, "id": "youtube-reply-1"}
        ),
    )

    assert adapter.name == "youtube_comments"
    assert adapter.name != YouTubeAdapter.name
    assert adapter.capabilities().can_read is True
    assert adapter.capabilities().can_reply is True
    event = adapter.poll_comments()[0]
    assert event.platform == "youtube_comments"
    assert event.stream_id == "video-1"
    result = adapter.send_reply(event, "Halo juga!")
    assert result == ReplyResult(True, "sent", "youtube-reply-1")
    assert replies == [("comment-1", "Halo juga!")]


def test_youtube_api_key_only_reads_but_never_attempts_reply():
    reply_attempts: list[tuple[str, str]] = []
    adapter = YouTubeCommentsAdapter(
        video_id="video-1",
        enabled=True,
        api_key_getter=lambda: "offline-api-key",
        token_getter=lambda: None,
        reader=lambda _video_id: [],
        replier=lambda comment_id, text: (
            reply_attempts.append((comment_id, text)) or {"ok": True}
        ),
    )
    comment = CommentEvent(
        "youtube_comments",
        "comment-1",
        "channel-1",
        "Offline Channel",
        "halo",
        12.0,
    )

    capabilities = adapter.capabilities()
    assert capabilities.can_read is True
    assert capabilities.can_reply is False
    assert capabilities.requires_manual_approval is True
    assert adapter.send_reply(comment, "Halo juga!").ok is False
    assert reply_attempts == []


class _TikTokClient:
    def __init__(self, proof: TikTokCapabilityProof) -> None:
        self.proof = proof
        self.probe_calls = 0
        self.poll_calls = 0
        self.send_calls = 0

    def probe(self, token: str) -> TikTokCapabilityProof:
        assert token == "offline-tiktok-token"
        self.probe_calls += 1
        return self.proof

    def poll_comments(self, token: str) -> list[dict]:
        self.poll_calls += 1
        return []

    def send_reply(self, comment_id: str, text: str, token: str) -> dict:
        self.send_calls += 1
        return {"ok": True, "id": "reply-1"}


def test_tiktok_requires_official_api_and_current_read_reply_permission_proof():
    unproven_client = _TikTokClient(
        TikTokCapabilityProof(
            official_api=True,
            can_read=True,
            can_reply=False,
            permissions=frozenset({"comments.read"}),
        )
    )
    adapter = TikTokProbeAdapter(
        enabled=True,
        token_getter=lambda: "offline-tiktok-token",
        client=unproven_client,
    )
    comment = CommentEvent(
        "tiktok",
        "comment-1",
        "author-1",
        "Offline User",
        "halo",
        1.0,
    )

    capabilities = adapter.capabilities()
    assert capabilities.can_read is False
    assert capabilities.can_reply is False
    assert capabilities.requires_manual_approval is True
    assert "official read and reply permissions are not proven" in capabilities.notes
    assert adapter.poll_comments() == []
    assert adapter.send_reply(comment, "Halo juga!").ok is False
    assert unproven_client.poll_calls == 0
    assert unproven_client.send_calls == 0

    proven_client = _TikTokClient(
        TikTokCapabilityProof(
            official_api=True,
            can_read=True,
            can_reply=True,
            permissions=frozenset({"comments.read", "comments.reply"}),
        )
    )
    proven = TikTokProbeAdapter(
        enabled=True,
        token_getter=lambda: "offline-tiktok-token",
        client=proven_client,
    )
    assert proven.capabilities().can_read is True
    assert proven.capabilities().can_reply is True


def test_tiktok_default_probe_has_no_browser_or_unofficial_fallback():
    adapter = TikTokProbeAdapter(
        enabled=True,
        token_getter=lambda: "offline-tiktok-token",
    )
    comment = CommentEvent(
        "tiktok",
        "comment-1",
        "author-1",
        "Offline User",
        "halo",
        1.0,
    )

    capabilities = adapter.capabilities()
    assert capabilities.can_read is False
    assert capabilities.can_reply is False
    assert capabilities.requires_manual_approval is True
    assert adapter.poll_comments() == []
    assert adapter.send_reply(comment, "Halo juga!").ok is False

    source = (
        Path(__file__).parents[1]
        / "jarvis/integrations/comments/tiktok_probe.py"
    ).read_text(encoding="utf-8").casefold()
    for forbidden in ("playwright", "selenium", "browser", "pyautogui"):
        assert forbidden not in source


class _SharedAdapter(PlatformAdapter):
    def __init__(self, name: str, *, manual: bool = False) -> None:
        self.name = name
        self.manual = manual
        self.sent: list[tuple[str, str]] = []

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(True, True, self.manual, "offline fake")

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        self.sent.append((comment.comment_id, text))
        return ReplyResult(True, "sent")


def test_social_config_is_default_off_and_contains_no_credential_values():
    config_text = (
        Path(__file__).parents[1] / "config.yaml"
    ).read_text(encoding="utf-8").casefold()

    compact = "\n".join(line.strip() for line in config_text.splitlines())
    assert "facebook_messaging:\nenabled: false" in compact
    assert "instagram_messaging:\nenabled: false" in compact
    assert "youtube_comments:\nenabled: false" in compact
    assert "tiktok:\nenabled: false" in compact
    for forbidden in (
        "facebook_page_access_token",
        "instagram_access_token",
        "tiktok_access_token",
        "access_token:",
        "client_secret:",
    ):
        assert forbidden not in config_text


def test_social_runtime_boot_wiring_is_default_off_and_supervisor_owned():
    from jarvis.main import _start_social_comments_runtime

    class _Supervisor:
        def __init__(self) -> None:
            self.stops: list[tuple[str, object]] = []

        def add_stop(self, name: str, callback) -> None:
            self.stops.append((name, callback))

    class _Runtime:
        def __init__(self, started: bool) -> None:
            self.started = started
            self.start_calls = 0
            self.stop_calls = 0

        def start(self) -> bool:
            self.start_calls += 1
            return self.started

        def stop(self) -> None:
            self.stop_calls += 1

    disabled_supervisor = _Supervisor()
    disabled_factory_calls: list[bool] = []
    assert _start_social_comments_runtime(
        disabled_supervisor,
        enabled=False,
        runtime_factory=lambda: disabled_factory_calls.append(True),
    ) is None
    assert disabled_factory_calls == []
    assert disabled_supervisor.stops == []

    runtime = _Runtime(started=True)
    enabled_supervisor = _Supervisor()
    result = _start_social_comments_runtime(
        enabled_supervisor,
        enabled=True,
        runtime_factory=lambda: (object(), runtime),
    )
    assert result is runtime
    assert runtime.start_calls == 1
    assert enabled_supervisor.stops == [("social_comments", runtime.stop)]


def test_factory_keeps_all_lanes_separate_and_wires_one_shared_runtime():
    adapters = build_adapters()
    names = [adapter.name for adapter in adapters]

    assert names == [
        "facebook",
        "facebook_messaging",
        "instagram",
        "instagram_messaging",
        "youtube",
        "youtube_comments",
        "tiktok",
    ]
    manager, runtime = build_runtime(
        adapters=[_SharedAdapter("facebook_messaging")],
        policy=DeterministicReplyPolicy(),
        poll_interval_s=5.0,
    )
    assert manager.adapters[0].name == "facebook_messaging"
    assert runtime.start() is True
    runtime.stop()
    assert runtime.join(timeout=1.0) is True


def test_runtime_handler_shares_policy_rate_cooldown_and_audit_across_lanes():
    audit = _Audit()
    facebook = _SharedAdapter("facebook_messaging")
    youtube = _SharedAdapter("youtube_comments")
    manager = CommentManager(
        [facebook, youtube],
        audit=audit,
        activation_ttl_s=60,
        max_replies_per_min=2,
        author_cooldown_s=30,
    )
    manager.enable_auto_reply("facebook_messaging")
    manager.enable_auto_reply("youtube_comments")
    handler = DeterministicReplyHandler(manager, DeterministicReplyPolicy())

    handler(
        CommentEvent(
            "facebook_messaging",
            "message-1",
            "author-1",
            "Offline User",
            "halo",
            1.0,
        )
    )
    handler(
        CommentEvent(
            "youtube_comments",
            "comment-1",
            "author-2",
            "Offline User",
            "Tolong jelaskan produk ini",
            1.0,
        )
    )
    handler(
        CommentEvent(
            "youtube_comments",
            "comment-2",
            "author-3",
            "Offline User",
            "Thanks, my order is missing.",
            2.0,
        )
    )

    assert len(facebook.sent) == 1
    assert youtube.sent == [], "ambiguous text must remain draft with no send attempt"
    decisions = [event for event in audit.events if event.get("event") == "reply_decision"]
    assert [event["disposition"] for event in decisions] == ["auto", "draft", "draft"]
    assert all("reply" not in event and "text" not in event for event in decisions)
