"""Fase 16D: local briefing composer + delivery (Calendar + Gmail summaries).

Compose a bounded, privacy-aware spoken briefing from already-summarized
Calendar agenda and Gmail unread data. Sensitive email subjects are never
included. Boot briefing, email content in briefing, and remote boot delivery
default OFF. Delivery routes to local TTS and the Task Result drawer; a TTS
failure never blocks or crashes the briefing.
"""
from __future__ import annotations

from collections.abc import Callable

from jarvis.core import config, log

_logger = log.get("core.briefing")

_MAX_BRIEFING_CHARS = 600


def boot_briefing_enabled() -> bool:
    return bool(config.get("briefing.on_boot.calendar", False))


def boot_email_content_enabled() -> bool:
    return bool(config.get("briefing.on_boot.email_content", False))


def boot_monitor_enabled() -> bool:
    """Monitor summaries are opt-in; never fetch a source at boot."""
    return bool(config.get("briefing.on_boot.monitor", False))


def remote_boot_delivery_enabled() -> bool:
    return bool(config.get("briefing.telegram.send_summary", False))


def compose_briefing(*, agenda: dict | None = None, gmail: dict | None = None,
                     monitor: dict | None = None, include_email_content: bool = False,
                     include_monitor: bool = False) -> str:
    """Compose a bounded spoken briefing; sensitive email subjects excluded."""
    parts: list[str] = []
    agenda = agenda or {}
    gmail = gmail or {}

    count = int(agenda.get("count", 0))
    if count:
        items = agenda.get("items") or []
        titles = "; ".join(f"{it['title']} pukul {it['time']}" for it in items[:3])
        parts.append(f"Ada {count} acara. {titles}.")

    unread = int(gmail.get("unread_count", 0))
    if unread:
        line = f"Ada {unread} email belum dibaca."
        if include_email_content:
            safe = [it.get("subject", "") for it in (gmail.get("items") or [])[:3]
                    if not it.get("sensitive")]
            if safe:
                line += " Beberapa di antaranya: " + "; ".join(safe) + "."
        parts.append(line)

    if include_monitor and isinstance(monitor, dict):
        source = str(monitor.get("source") or "").strip()[:80]
        raw_items = monitor.get("items")
        safe_titles: list[str] = []
        if isinstance(raw_items, list):
            for item in raw_items[:3]:
                if not isinstance(item, dict) or set(item) - {"title", "url", "published", "hash"}:
                    continue
                title = str(item.get("title") or "").strip()[:200]
                if title:
                    safe_titles.append(title)
        if source and safe_titles:
            parts.append(f"Update monitor {source}: " + "; ".join(safe_titles) + ".")

    if not parts:
        return "Tidak ada agenda atau email baru saat ini."
    return " ".join(parts)[:_MAX_BRIEFING_CHARS]


def deliver_briefing(text: str, *, speak: Callable[[str], None] | None = None,
                     drawer: Callable[[str], None] | None = None) -> None:
    """Route a briefing to local TTS and the Task Result drawer, fail-open."""
    value = str(text or "").strip()
    if not value:
        return
    if drawer is not None:
        try:
            drawer(value)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("briefing.drawer_failed", error=type(exc).__name__)
    if speak is not None:
        try:
            speak(value)
        except Exception as exc:  # noqa: BLE001
            _logger.warning("briefing.tts_failed", error=type(exc).__name__)


__all__ = ["compose_briefing", "deliver_briefing", "boot_briefing_enabled",
           "boot_email_content_enabled", "boot_monitor_enabled",
           "remote_boot_delivery_enabled"]
