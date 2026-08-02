"""Phase 19 — Intent-specific bounded setter for Content Studio Judul Project only.

Only this exact intent is allowed: setting the project title field locally.
No generic text dispatch, no other field, no submit, no path/secret/network.
"""
from __future__ import annotations

_MAX_LEN = 120

_DENY_SUBSTRINGS = (
    "password", "passcode", "pin", "otp", "verification code",
    "credit card", "card number", "cvv", "payment", "checkout",
    "sign in", "log in", "login", "bank", "transfer", "permission",
    "send email", "compose", "chat", "terminal", "shell",
    "rm -rf", "exec", "sudo",
)

_URL_MARKERS = ("http://", "https://", "www.", "://")

def _looks_like_url(text: str) -> bool:
    low = text.casefold()
    return any(marker in low for marker in _URL_MARKERS)

def admit_title(value: object) -> dict:
    """Admit only a bounded, non-sensitive project title string.

    Returns:
      {ok: True, title: <trimmed>} on allow
      {ok: False, reason: <safe_code>} on reject, never the raw input
    """
    if isinstance(value, bool) or not isinstance(value, str):
        return {"ok": False, "reason": "content_title_type_rejected"}

    trimmed = " ".join(value.split())
    if not trimmed:
        return {"ok": False, "reason": "content_title_empty"}

    if len(trimmed) > _MAX_LEN:
        return {"ok": False, "reason": "content_title_length_rejected"}

    low = trimmed.casefold()

    if _looks_like_url(trimmed):
        return {"ok": False, "reason": "content_title_url_rejected"}

    for term in _DENY_SUBSTRINGS:
        if term in low:
            return {"ok": False, "reason": "content_title_sensitive_rejected"}

    # Reject if it looks like an email composition instruction
    if "@" in trimmed and any(k in low for k in ("email", "compose", "send")):
        return {"ok": False, "reason": "content_title_sensitive_rejected"}

    # Reject path separators that hint at filesystem path intent
    # but allow normal single words; only reject when it looks like a path
    # Keep narrow: reject if contains backslash path or absolute refinement
    if "\\" in trimmed and ":" in trimmed:
        return {"ok": False, "reason": "content_title_path_rejected"}

    return {"ok": True, "title": trimmed, "intent": "content_studio_title"}


__all__ = ["admit_title", "MAX_LEN"]

MAX_LEN = _MAX_LEN
