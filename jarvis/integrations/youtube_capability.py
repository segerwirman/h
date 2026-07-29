"""YouTube credential capability model (this-prompt §20/§22).

The load-bearing distinction: an API key is NOT sufficient to post replies
or read authenticated live-chat operations — those require OAuth 2.0 with the
right scopes. This module reports, from what is actually stored in the OS
keyring (never config.yaml, never plaintext), exactly which operations are
currently permitted, so the UI can keep reply controls disabled until OAuth
is genuinely connected and never falsely claim "replying is configured"
because a key validated.

Secrets are read through ``jarvis.core.secrets_store`` (Windows Credential
Manager via keyring, env fallback). Only presence/scope is inspected here —
values are never logged or returned.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from jarvis.core import config, log, secrets_store
from jarvis.integrations import google_auth

_logger = log.get("integrations.youtube_capability")

# Minimum scopes for each write/authenticated-read capability.
_SCOPE_FORCE_SSL = "https://www.googleapis.com/auth/youtube.force-ssl"
_SCOPE_READONLY = "https://www.googleapis.com/auth/youtube.readonly"


@dataclass
class YouTubeCapabilities:
    api_key_present: bool = False
    oauth_connected: bool = False
    scopes: list[str] = field(default_factory=list)
    channel_id: str = ""
    channel_title: str = ""

    # derived, per §20 — never true from an API key alone
    can_read_public: bool = False        # public comment threads (key OR oauth)
    can_read_livechat: bool = False      # authenticated live-chat read (oauth)
    can_reply_comments: bool = False     # insert comment replies (oauth+scope)
    can_send_livechat: bool = False      # insert live-chat messages (oauth+scope)

    reason: str = ""

    def as_ui_status(self) -> dict:
        """Non-secret status dict safe for the settings panel / logs."""
        return {
            "api_key": "configured" if self.api_key_present else "not set",
            "oauth": ("connected" if self.oauth_connected else "not connected"),
            "channel": self.channel_title or "-",
            "read_public": self.can_read_public,
            "read_livechat": self.can_read_livechat,
            "reply_comments": self.can_reply_comments,
            "send_livechat": self.can_send_livechat,
            "reason": self.reason,
        }


def _secret_name(key: str, default: str) -> str:
    return str(config.get(f"integrations.youtube.{key}", default))


def resolve_capabilities(oauth_scopes: list[str] | None = None,
                         channel: tuple[str, str] | None = None
                         ) -> YouTubeCapabilities:
    """Inspect stored credentials and return the honest capability set.

    ``oauth_scopes``/``channel`` are injectable for tests and for callers that
    have already exchanged a token; when omitted, presence is inferred from the
    keyring token secret (its scope list, if the caller stored one, is passed
    in separately by the OAuth manager — this function never parses raw
    token material)."""
    caps = YouTubeCapabilities()

    api_key = secrets_store.get(_secret_name("api_key_secret_name",
                                             "jarvis/youtube/data_api_v3"))
    caps.api_key_present = bool(api_key)
    injected = oauth_scopes is not None
    caps.scopes = list(oauth_scopes if injected
                       else google_auth.token_scopes())
    caps.oauth_connected = (bool(caps.scopes) if injected else
                            bool(google_auth.connected()
                                 and google_auth.api_enabled("youtube")))
    if channel:
        caps.channel_id, caps.channel_title = channel

    # public read: an API key OR an OAuth session both work
    caps.can_read_public = caps.api_key_present or caps.oauth_connected

    if not caps.oauth_connected:
        caps.reason = ("API key gives read-only access; connect a Google "
                       "account (OAuth) to read live chat or reply.")
        return caps

    has_write = _SCOPE_FORCE_SSL in caps.scopes
    has_readonly = _SCOPE_READONLY in caps.scopes or has_write

    caps.can_read_livechat = has_readonly
    caps.can_reply_comments = has_write and (
        injected or google_auth.has_write_scope("youtube"))
    caps.can_send_livechat = caps.can_reply_comments
    if not caps.scopes:
        # OAuth token present but scopes not yet known to this caller —
        # report connected-but-unverified rather than assuming write access
        caps.reason = ("OAuth connected; grant the YouTube write scope to "
                       "enable replying and live-chat sending.")
    elif not has_write:
        caps.reason = "Connected without write scope — replying stays disabled."
    else:
        caps.reason = "OAuth write scope present — replying available."
    return caps
