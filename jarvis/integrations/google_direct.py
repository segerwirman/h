"""Pemetaan deterministik T1 Google; menjalankan registry tanpa agent loop."""
from __future__ import annotations

import re


def match_command(text: str) -> tuple[str, dict] | None:
    normalized = " ".join(str(text or "").lower().split())
    if not normalized:
        return None
    if re.search(r"\b(?:acara|agenda|kalender|calendar)\s+berikut", normalized):
        return "gcal_next", {}
    if (re.search(r"\b(?:acara|agenda|kalender|calendar)\b", normalized)
            and re.search(r"\b(?:hari ini|today|besok|tomorrow)\b", normalized)):
        when = "besok" if re.search(r"\b(?:besok|tomorrow)\b", normalized) else ""
        return "gcal_events", {"start": when, "end": when}
    if (re.search(r"\bvideo\s+(?:yang\s+)?(?:terbaru|latest|paling baru)\b",
                  normalized)
            and re.search(r"\b(?:langganan(?:ku)?|subscriptions?)\b",
                          normalized)):
        return "yt_latest", {}
    if (re.search(r"\b(?:email|surel|gmail)\b", normalized)
            and re.search(r"\b(?:baru|unread|belum dibaca|masuk)\b", normalized)):
        return "gmail_list", {"query": "is:unread"}
    return None


def unavailable_message(tool_name: str) -> str:
    api = {
        "gcal_events": "Calendar",
        "gcal_next": "Calendar",
        "yt_latest": "YouTube Data",
        "gmail_list": "Gmail",
    }.get(tool_name, "Google")
    return (f"Google {api} belum aktif atau scope belum diberikan. "
            "Aktifkan di Settings Google Cloud lalu Connect ulang.")


def enabled_by_tool_group(tool_name: str) -> bool:
    """Hormati toggle Tools yang sudah ada juga pada jalur T1 langsung."""
    try:
        from jarvis.agent import toolgroups
        return tool_name not in toolgroups.disabled_tool_names()
    except Exception:
        return False
