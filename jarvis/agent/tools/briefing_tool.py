"""Fase 16D: on-request local morning briefing (Calendar + Gmail unread).

Read-only. Pulls a bounded Calendar agenda and Gmail unread summary, composes a
privacy-aware spoken briefing (email content OFF by default), and returns it.
A failure in one source degrades gracefully rather than aborting the briefing.
"""
from __future__ import annotations

import asyncio

from pydantic import BaseModel

from jarvis.agent.base import Tool, ToolResult
from jarvis.core import briefing


def available() -> bool:
    from jarvis.integrations import google_auth
    return bool(google_auth.has_read_scope("calendar")
                or google_auth.has_read_scope("gmail"))


def _agenda_today() -> dict:
    from jarvis.agent.tools import google_calendar
    from jarvis.integrations import calendar_service, google_auth
    if not google_auth.has_read_scope("calendar"):
        return {"count": 0, "items": []}
    events = google_calendar._list_events("today", "", 10)
    return calendar_service.agenda_summary(events)


def _gmail_unread() -> dict:
    from jarvis.agent.tools import gmail_safe
    from jarvis.integrations import gmail_summary, google_auth
    if not google_auth.has_read_scope("gmail"):
        return {"unread_count": 0, "items": []}
    messages = gmail_safe._fetch_unread_metadata(10)
    return gmail_summary.summarize_unread(messages, tier="default")


def _persistent_sources():
    """Open the metadata-only source registry; never fetch or schedule."""
    from jarvis.core import config
    from jarvis.monitoring.source_registry_store import PersistentSourceRegistry
    return PersistentSourceRegistry(config.base_dir() / "data" / "monitor_sources.sqlite")


def _monitor_store():
    """Open bounded monitor metadata store; never fetch or schedule."""
    from jarvis.core import config
    from jarvis.monitoring.store import MonitorStore
    return MonitorStore(config.base_dir() / "data" / "monitor_items.sqlite")


def _monitor_latest() -> dict:
    """Read selected source metadata only; no selection yields an empty result."""
    selected = _persistent_sources().selected()
    if selected is None:
        return {"source": "", "items": []}
    return {"source": selected.name, "items": _monitor_store().latest(selected.name)}


class _NoParams(BaseModel):
    pass


class BriefingTool(Tool):
    name = "morning_briefing"
    description = (
        "Susun briefing lokal singkat: agenda Calendar hari ini dan jumlah "
        "email belum dibaca. Isi email tidak dibacakan secara default."
    )
    params_schema = _NoParams
    read_only = True
    timeout_s = 45

    def is_available(self) -> bool:
        return available()

    async def run(self, **_) -> ToolResult:
        agenda = await self._safe(_agenda_today, {"count": 0, "items": []})
        gmail = await self._safe(_gmail_unread, {"unread_count": 0, "items": []})
        include_monitor = briefing.boot_monitor_enabled()
        monitor = await self._safe(_monitor_latest, {"source": "", "items": []}) if include_monitor else None
        text = briefing.compose_briefing(
            agenda=agenda, gmail=gmail, monitor=monitor,
            include_email_content=briefing.boot_email_content_enabled(),
            include_monitor=include_monitor)
        return ToolResult.success({"briefing": text}, display=text)

    @staticmethod
    async def _safe(fn, fallback):
        try:
            return await asyncio.to_thread(fn)
        except Exception:  # noqa: BLE001
            return fallback


__all__ = ["BriefingTool"]
