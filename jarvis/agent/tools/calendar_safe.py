"""Fase 16C: calendar_safe — agenda summary + local-approved event creation.

Read side returns a bounded agenda summary. Create side builds a fully-rendered
proposal (all fields + elevated-risk flags), requires confirmation, and only
calls the Google Calendar API after a valid proposal is built; a missing
timezone or invalid time fails before any network call.
"""
from __future__ import annotations

import asyncio

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.integrations import calendar_service, google_api, google_auth


def available() -> bool:
    return bool(google_auth.has_read_scope("calendar")
                or google_auth.has_write_scope("calendar"))


def _insert_event(body: dict) -> dict:
    write_scope = google_auth.SCOPES["calendar"]["write"]
    svc = google_api.service("calendar", "v3", [write_scope])
    return svc.events().insert(
        calendarId="primary", body=body, sendUpdates="none").execute()


class _CreateParams(BaseModel):
    summary: str = Field(min_length=1, description="Judul acara")
    start: str = Field(description="Waktu mulai ISO-8601")
    end: str = Field(description="Waktu selesai ISO-8601")
    timezone: str = Field(description="Timezone wajib, mis. Asia/Jakarta")
    location: str = ""
    attendees: list[str] = Field(default_factory=list)
    calendar_id: str = "primary"
    recurrence: str = ""
    reminder_minutes: int = Field(10, ge=0, le=40320)


class CalendarCreateProposed(Tool):
    name = "gcal_create_proposed"
    description = (
        "Buat acara Google Calendar melalui proposal lengkap yang wajib "
        "dikonfirmasi lokal; menandai risiko tinggi (attendee eksternal, "
        "acara berulang, kalender shared) sebelum dibuat."
    )
    params_schema = _CreateParams
    requires_confirmation = True
    timeout_s = 30

    def is_available(self) -> bool:
        return bool(google_auth.has_write_scope("calendar"))

    def confirmation_text(self, **kwargs) -> str:
        try:
            proposal = calendar_service.build_event_proposal(**self._proposal_kwargs(kwargs))
        except ValueError as exc:
            return f"Proposal Calendar tidak valid: {exc}"
        return calendar_service.proposal_text(proposal)

    @staticmethod
    def _proposal_kwargs(kwargs: dict) -> dict:
        return {
            "summary": kwargs.get("summary", ""),
            "start": kwargs.get("start", ""),
            "end": kwargs.get("end", ""),
            "timezone": kwargs.get("timezone", ""),
            "location": kwargs.get("location", ""),
            "attendees": kwargs.get("attendees", []),
            "calendar_id": kwargs.get("calendar_id", "primary"),
            "recurrence": kwargs.get("recurrence", ""),
            "reminder_minutes": kwargs.get("reminder_minutes", 10),
        }

    async def run(self, summary: str, start: str, end: str, timezone: str,
                  location: str = "", attendees: list[str] | None = None,
                  calendar_id: str = "primary", recurrence: str = "",
                  reminder_minutes: int = 10, **_) -> ToolResult:
        try:
            proposal = calendar_service.build_event_proposal(
                summary=summary, start=start, end=end, timezone=timezone,
                location=location, attendees=attendees or [],
                calendar_id=calendar_id, recurrence=recurrence,
                reminder_minutes=reminder_minutes)
        except ValueError as exc:
            return ToolResult.fail(f"Proposal Calendar tidak valid: {exc}")
        body = calendar_service.to_api_body(proposal)
        try:
            event = await asyncio.to_thread(_insert_event, body)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        text = f"Acara '{event.get('summary') or summary}' berhasil dibuat."
        return ToolResult.success(
            {"event_id": event.get("id", ""), "summary": event.get("summary", summary),
             "elevated_risk": proposal["elevated_risk"]},
            display=text)


__all__ = ["CalendarCreateProposed"]
