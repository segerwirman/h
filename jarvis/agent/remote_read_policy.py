"""Phase 15A: bounded, session-bound rendering for remote read-only results."""
from __future__ import annotations

import re

_FORBIDDEN_KEYS = frozenset({
    "token", "secret", "client_secret", "access_token", "refresh_token", "password",
    "path", "file", "attachment", "body", "raw", "ocr", "screenshot",
    "observation_id", "element_id", "runtime_id", "x", "y", "selector",
})

_SENSITIVE_LABEL = re.compile(
    r"(?i)\b(access\s*token|refresh\s*token|api\s*key|client\s*secret|"
    r"private\s*key|secret|password|passwd|authorization|bearer|credential)\b"
)

_PATH_LIKE = re.compile(
    r"(?i)([a-z]:[\\/]|\\\\|/home/|/users/|\.\./|/etc/|/var/|/proc/|/sys/)"
)

_REDACTED = "[REDACTED]"


def _redact(value) -> str:
    """Redact a value that embeds secrets or path-like material."""
    text = str(value or "")
    if _SENSITIVE_LABEL.search(text) or _PATH_LIKE.search(text):
        return _REDACTED
    return text


def _contains_forbidden(value) -> bool:
    if isinstance(value, dict):
        return any(str(k).lower() in _FORBIDDEN_KEYS or _contains_forbidden(v)
                   for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return any(_contains_forbidden(v) for v in value)
    return False


def render_remote_read(payload: dict, *, chat_id: str, expected_chat_id: str,
                       max_items: int = 5, max_chars: int = 1000) -> dict:
    """Render an already-sanitized read model without raw sensitive content."""
    if str(chat_id) != str(expected_chat_id):
        return {"ok": False, "reason": "remote_session_mismatch"}
    if not isinstance(payload, dict) or _contains_forbidden(payload):
        return {"ok": False, "reason": "remote_read_payload_rejected"}
    try:
        cap_items = max(0, min(int(max_items), 10))
        cap_chars = max(80, min(int(max_chars), 1000))
        lines: list[str] = []
        if "unread_count" in payload:
            count = max(0, int(payload.get("unread_count", 0)))
            items = payload.get("items") or []
            if not isinstance(items, (list, tuple)):
                raise ValueError("invalid items")
            lines.append(f"Email belum dibaca: {count}")
            for item in items[:cap_items]:
                if not isinstance(item, dict) or item.get("sensitive"):
                    continue
                sender = _redact(item.get("sender") or "pengirim disamarkan")
                subject = _redact(item.get("subject") or "(tanpa subjek)")
                when = _redact(item.get("time") or "")
                lines.append(f"• {sender} — {subject}" + (f" ({when})" if when else ""))
        elif "count" in payload:
            count = max(0, int(payload.get("count", 0)))
            items = payload.get("items") or []
            if not isinstance(items, (list, tuple)):
                raise ValueError("invalid items")
            lines.append(f"Agenda: {count} acara")
            for item in items[:cap_items]:
                if not isinstance(item, dict):
                    continue
                when = _redact(item.get("time") or "")
                title = _redact(item.get("title") or "Acara")
                lines.append(f"• {when} — {title}")
        elif "briefing" in payload:
            briefing = payload.get("briefing")
            if not isinstance(briefing, str):
                raise ValueError("invalid briefing")
            lines.append(_redact(briefing)[:cap_chars])
        else:
            raise ValueError("unknown payload")
    except (TypeError, ValueError, OverflowError):
        return {"ok": False, "reason": "remote_read_payload_rejected"}
    return {"ok": True, "content": "\n".join(lines)[:cap_chars]}


__all__ = ["render_remote_read"]
