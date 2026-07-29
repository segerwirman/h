"""X (Twitter) adapter (redesign §15) — honest capability report.

X's public API does not expose a "live video comments" surface comparable
to YouTube Live Chat or Meta's live-video comment endpoints: there is no
public, generally-available endpoint that streams comments attached to a
live broadcast. Reply-style interaction is possible through ordinary tweet
replies (POST /2/tweets with ``reply.in_reply_to_tweet_id``), but genuine
real-time comment *reading* at the volume this subsystem assumes requires
either the filtered stream endpoint (gated behind Elevated/Pro API access,
not the free tier) or polling search, which is rate-limited and not a
faithful substitute for "reading live comments."

Rather than approximate that with tweet search and call it "live comments,"
this adapter reports the real limitation through ``capabilities()`` so the
rest of the system treats X as manual-approval-required instead of
pretending an unsupported integration succeeded.
"""
from __future__ import annotations

from jarvis.core import config, secrets_store
from jarvis.integrations.comments.base import (CommentEvent, PlatformAdapter,
                                               PlatformCapabilities, ReplyResult)

_TOKEN_KEY = "X_BEARER_TOKEN"


class XAdapter(PlatformAdapter):
    name = "x"

    def is_authenticated(self) -> bool:
        return bool(secrets_store.get(_TOKEN_KEY))

    def capabilities(self) -> PlatformCapabilities:
        if not bool(config.get("live_comments.platforms.x.enabled", False)):
            return PlatformCapabilities(False, False, True,
                                        "disabled in config (live_comments.platforms.x.enabled)")
        return PlatformCapabilities(
            can_read=False, can_reply=False, requires_manual_approval=True,
            notes=("X has no general-availability endpoint for reading live video "
                  "comments; real-time coverage requires the filtered-stream API "
                  "(Elevated/Pro access tier), which this project does not assume "
                  "you have. Manual approval required — this platform is not "
                  "wired for automatic reading or replying."))

    def poll_comments(self) -> list[CommentEvent]:
        return []

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        return ReplyResult(False, self.capabilities().notes)

    def connection_health(self) -> dict:
        return {"platform": self.name, "connected": False,
               "authenticated": self.is_authenticated(),
               "detail": "unsupported — see capabilities().notes"}
