"""Phase 19 — Intent-specific bounded setter for Content Studio Judul Project only.

Only this exact intent is allowed: setting the project title field locally.
No generic text dispatch, no other field, no submit, no path/secret/network.
"""
from __future__ import annotations

import re
import unicodedata

_MAX_LEN = 120

_DENY_SUBSTRINGS = (
    "password", "passcode", "pin", "otp", "verification code",
    "credit card", "card number", "cvv", "payment", "checkout",
    "sign in", "log in", "login", "bank", "transfer", "permission",
    "send email", "compose", "chat", "terminal", "shell",
    "rm -rf", "exec", "sudo",
    "token", "api key", "bearer credential", "private key",
    "seed phrase", "recovery code", "access key", "client secret",
    "credential",
)

_URL_MARKERS = ("http://", "https://", "www.", "://")
_BARE_HOST = re.compile(
    r"(?<![a-z0-9-])(?:[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?\.)+"
    r"[a-z]{2,63}(?![a-z0-9-])",
    re.IGNORECASE,
)
_SECRET_PREFIX = re.compile(
    r"(?<![a-z0-9])(?:sk-(?:proj-)?|ghp_|github_pat_|xox[baprs]-|akia|aiza)"
    r"[a-z0-9_-]{8,}(?![a-z0-9_-])",
    re.IGNORECASE,
)

def _looks_like_url(text: str) -> bool:
    low = text.casefold()
    return any(marker in low for marker in _URL_MARKERS)


def _looks_like_bare_host(text: str) -> bool:
    return bool(_BARE_HOST.search(text))


def _looks_like_path(text: str) -> bool:
    return "/" in text or "\\" in text


def _compact_security_text(text: str) -> str:
    return re.sub(r"[\W_]+", "", text.casefold())


def _looks_like_secret(text: str) -> bool:
    return bool(_SECRET_PREFIX.search(text))

def admit_title(value: object) -> dict:
    """Admit only a bounded, non-sensitive project title string.

    Returns:
      {ok: True, title: <trimmed>} on allow
      {ok: False, reason: <safe_code>} on reject, never the raw input
    """
    if isinstance(value, bool) or not isinstance(value, str):
        return {"ok": False, "reason": "content_title_type_rejected"}

    trimmed = " ".join(unicodedata.normalize("NFKC", value).split())
    if not trimmed:
        return {"ok": False, "reason": "content_title_empty"}

    if len(trimmed) > _MAX_LEN:
        return {"ok": False, "reason": "content_title_length_rejected"}

    low = trimmed.casefold()

    if _looks_like_url(trimmed):
        return {"ok": False, "reason": "content_title_url_rejected"}

    if _looks_like_path(trimmed):
        return {"ok": False, "reason": "content_title_path_rejected"}

    if _looks_like_bare_host(trimmed):
        return {"ok": False, "reason": "content_title_url_rejected"}

    if _looks_like_secret(trimmed):
        return {"ok": False, "reason": "content_title_sensitive_rejected"}

    compact = _compact_security_text(trimmed)
    for term in _DENY_SUBSTRINGS:
        if term in low or _compact_security_text(term) in compact:
            return {"ok": False, "reason": "content_title_sensitive_rejected"}

    # Reject if it looks like an email composition instruction
    if "@" in trimmed and any(k in low for k in ("email", "compose", "send")):
        return {"ok": False, "reason": "content_title_sensitive_rejected"}

    return {"ok": True, "title": trimmed, "intent": "content_studio_title"}


__all__ = ["admit_title", "MAX_LEN"]

MAX_LEN = _MAX_LEN
