"""Construct default-off official social lanes for the shared runtime."""
from __future__ import annotations

from jarvis.core import config
from jarvis.integrations.comments.base import CommentManager
from jarvis.integrations.comments.deterministic_reply import DeterministicReplyPolicy
from jarvis.integrations.comments.facebook import FacebookAdapter
from jarvis.integrations.comments.facebook_messaging import FacebookMessagingAdapter
from jarvis.integrations.comments.instagram import InstagramAdapter
from jarvis.integrations.comments.instagram_messaging import InstagramMessagingAdapter
from jarvis.integrations.comments.runtime import CommentRuntime, DeterministicReplyHandler
from jarvis.integrations.comments.tiktok_probe import TikTokProbeAdapter
from jarvis.integrations.comments.youtube import YouTubeAdapter
from jarvis.integrations.comments.youtube_comments import YouTubeCommentsAdapter


def build_adapters(*, tiktok_client=None):
    """Build separate comment, messaging, live-chat, and ordinary-comment lanes."""
    return [
        FacebookAdapter(),
        FacebookMessagingAdapter(),
        InstagramAdapter(),
        InstagramMessagingAdapter(),
        YouTubeAdapter(),
        YouTubeCommentsAdapter(),
        TikTokProbeAdapter(client=tiktok_client),
    ]


def build_runtime(*, adapters=None, policy=None, audit=None, **runtime_kwargs):
    """Wire every lane through one manager, policy, audit, rate, and cooldown owner."""
    manager = CommentManager(adapters or build_adapters(), audit=audit)
    handler = DeterministicReplyHandler(
        manager,
        policy or DeterministicReplyPolicy(),
        audit=audit,
    )
    poll_interval_s = runtime_kwargs.pop(
        "poll_interval_s",
        float(config.get("live_comments.poll_interval_s", 5.0)),
    )
    runtime = CommentRuntime(
        manager,
        poll_interval_s=poll_interval_s,
        handler=handler,
        **runtime_kwargs,
    )
    return manager, runtime


__all__ = ["build_adapters", "build_runtime"]
