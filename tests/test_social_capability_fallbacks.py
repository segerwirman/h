"""Offline contracts for official social lanes and fail-closed fallbacks."""
from __future__ import annotations

from pathlib import Path

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

    facebook_event = facebook.poll_comments()[0]
    instagram_event = instagram.poll_comments()[0]
    assert facebook_event.platform == "facebook_messaging"
    assert instagram_event.platform == "instagram_messaging"
    assert facebook.send_reply(facebook_event, "Halo juga!").ok is True
    assert instagram.send_reply(instagram_event, "Halo juga!").ok is True
    assert facebook_client.poll_calls == facebook_client.send_calls == 1
    assert instagram_client.poll_calls == instagram_client.send_calls == 1


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

    assert len(facebook.sent) == 1
    assert youtube.sent == [], "ambiguous text must remain draft with no send attempt"
    decisions = [event for event in audit.events if event.get("event") == "reply_decision"]
    assert [event["disposition"] for event in decisions] == ["auto", "draft"]
    assert all("reply" not in event and "text" not in event for event in decisions)
