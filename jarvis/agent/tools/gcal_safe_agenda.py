"""Phase 15A: bounded Calendar agenda safe for paired remote reads."""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.integrations import calendar_service, google_auth


def available() -> bool:
    return bool(google_auth.has_read_scope("calendar"))


def _agenda_today(limit: int) -> dict:
    from jarvis.agent.tools import google_calendar
    events = google_calendar._list_events("today", "", limit)
    return calendar_service.agenda_summary(events)


class _Params(BaseModel):
    limit: int = Field(5, ge=1, le=10)


class GcalSafeAgenda(Tool):
    name = "gcal_safe_agenda"
    description = "Agenda Google Calendar hari ini secara read-only dan dibatasi."
    params_schema = _Params
    read_only = True
    timeout_s = 30

    def is_available(self) -> bool:
        return bool(google_auth.has_read_scope("calendar"))

    async def run(self, limit: int = 5, **_) -> ToolResult:
        try:
            agenda = await asyncio.to_thread(_agenda_today, limit)
        except Exception:
            return ToolResult.fail("calendar_safe_unavailable")
        return ToolResult.success(agenda, display=calendar_service.agenda_briefing(agenda))


__all__ = ["GcalSafeAgenda"]
