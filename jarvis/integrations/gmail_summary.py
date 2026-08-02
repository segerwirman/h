"""Fase 16B: privacy-tiered Gmail summary — pure, no network.

Turns raw Gmail metadata into a bounded, redacted summary safe for remote/voice
delivery. Senders are masked, sensitive mail (OTP/password-reset/payment/bank)
is redacted, bodies are never summarized unless explicitly allowed, and
attachment metadata is never auto-delivered.
"""
from __future__ import annotations

import re

_SENSITIVE_PATTERNS = (
    re.compile(r"\botp\b", re.I),
    re.compile(r"one[- ]?time (?:code|password)", re.I),
    re.compile(r"kode\s+(?:otp|verifikasi|rahasia)", re.I),
    re.compile(r"password\s+reset|reset\s+(?:your\s+)?password|setel\s+ulang\s+(?:kata\s+sandi|password)", re.I),
    re.compile(r"\bpayment\b|\bpembayaran\b|\binvoice\b|\btagihan\b", re.I),
    re.compile(r"\bbank\b|saldo|transaksi|transfer", re.I),
    re.compile(r"verification code|verify your", re.I),
)

_SUBJECT_REDACTED = "[disensor: pesan sensitif]"
_BODY_REDACTED = "[disensor: konten sensitif tidak dibacakan]"


def _is_sensitive(text: str) -> bool:
    value = str(text or "")
    return any(p.search(value) for p in _SENSITIVE_PATTERNS)


def _mask_sender(raw: str) -> str:
    """Keep a short hint of the local part and the full domain; drop the rest."""
    value = str(raw or "").strip()
    match = re.search(r"[\w.+-]+@[\w.-]+", value)
    if not match:
        return "pengirim tidak dikenal"
    email = match.group(0)
    local, _, domain = email.partition("@")
    hint = (local[:2] + "…") if len(local) > 2 else "…"
    return f"{hint}@{domain}"


def summarize_unread(messages: list[dict], *, tier: str = "default") -> dict:
    """Summarize unread messages under a privacy tier.

    tier="count_only": only the count, no per-message data.
    tier="default": masked sender + subject/time, with sensitive redaction.
    """
    count = len(messages or [])
    if str(tier) == "count_only":
        return {"unread_count": count, "items": []}
    items: list[dict] = []
    for message in messages or []:
        subject = str(message.get("subject") or "")
        sender_raw = str(message.get("from") or message.get("sender") or "")
        sensitive = _is_sensitive(subject) or _is_sensitive(sender_raw)
        items.append({
            "sender": _mask_sender(sender_raw),
            "subject": _SUBJECT_REDACTED if sensitive else (subject or "(tanpa subjek)"),
            "time": str(message.get("date") or message.get("time") or ""),
            "sensitive": sensitive,
        })
    return {"unread_count": count, "items": items}


def summarize_body(body: str, *, allow_body: bool = False,
                   sensitive: bool = False, max_chars: int = 600) -> str:
    """Return a bounded body summary only when explicitly allowed."""
    if not allow_body:
        return ""
    if sensitive:
        return _BODY_REDACTED
    text = " ".join(str(body or "").split())
    cap = max(1, int(max_chars))
    return text[:cap]


def briefing_text(summary: dict) -> str:
    """Short TTS-ready brief, distinct from the display summary."""
    count = int(summary.get("unread_count", 0))
    if count == 0:
        return "Tidak ada email baru yang belum dibaca."
    items = summary.get("items") or []
    safe_subjects = [it["subject"] for it in items[:3] if not it.get("sensitive")]
    lead = f"Ada {count} email belum dibaca."
    if safe_subjects:
        lead += " Beberapa di antaranya: " + "; ".join(safe_subjects) + "."
    return lead[:400]


__all__ = ["summarize_unread", "summarize_body", "briefing_text"]
