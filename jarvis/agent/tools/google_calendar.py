"""Google Calendar tools (§10.4), satu credential Google terpadu."""
from __future__ import annotations

import asyncio
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from jarvis.agent.base import Tool, ToolResult
from jarvis.core import config
from jarvis.integrations import google_api, google_auth

READ_SCOPE = google_auth.SCOPES["calendar"]["read"]
WRITE_SCOPE = google_auth.SCOPES["calendar"]["write"]


def available() -> bool:
    return google_auth.has_read_scope("calendar")


def _zone() -> ZoneInfo:
    try:
        return ZoneInfo(str(config.get("locale.timezone", "Asia/Jakarta")))
    except Exception:
        return ZoneInfo("UTC")


def _parse_point(value: str, *, end: bool = False) -> datetime:
    text = str(value or "").strip()
    zone = _zone()
    if not text:
        today = datetime.now(zone).date()
        return datetime.combine(today + (timedelta(days=1) if end else
                                         timedelta()), time.min, zone)
    if text.lower() in ("today", "hari ini"):
        day = datetime.now(zone).date() + (timedelta(days=1) if end else
                                           timedelta())
        return datetime.combine(day, time.min, zone)
    if text.lower() in ("tomorrow", "besok"):
        day = datetime.now(zone).date() + timedelta(days=1 + int(end))
        return datetime.combine(day, time.min, zone)
    try:
        if len(text) == 10:
            parsed = datetime.combine(date.fromisoformat(text), time.min, zone)
        else:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=zone)
        return parsed
    except ValueError as exc:
        raise ValueError("tanggal harus YYYY-MM-DD atau ISO-8601") from exc


def _event_line(event: dict) -> str:
    start = event.get("start") or {}
    raw = start.get("dateTime") or start.get("date") or ""
    label = "sepanjang hari"
    if "T" in raw:
        try:
            dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
            label = dt.astimezone(_zone()).strftime("%d %b %H:%M")
        except ValueError:
            label = raw
    elif raw:
        label = raw
    return f"{label} — {event.get('summary') or 'Acara tanpa judul'}"


def _list_events(start: str, end: str, limit: int) -> list[dict]:
    begin = _parse_point(start)
    finish = _parse_point(end, end=True)
    if finish <= begin:
        raise ValueError("waktu akhir harus setelah waktu mulai")
    svc = google_api.service("calendar", "v3", [
        WRITE_SCOPE if google_auth.has_scope(WRITE_SCOPE) else READ_SCOPE])
    response = svc.events().list(
        calendarId="primary", timeMin=begin.isoformat(),
        timeMax=finish.isoformat(), singleEvents=True,
        orderBy="startTime", maxResults=max(1, min(int(limit), 50)),
        timeZone=str(_zone()),
    ).execute()
    return list(response.get("items") or [])


class _EventsParams(BaseModel):
    start: str = Field("", description="Awal YYYY-MM-DD/ISO; kosong=hari ini")
    end: str = Field("", description="Akhir eksklusif; kosong=akhir hari ini")
    limit: int = Field(10, ge=1, le=50)


class GcalEvents(Tool):
    name = "gcal_events"
    description = "Bacakan acara Google Calendar pada hari/rentang tertentu."
    params_schema = _EventsParams
    read_only = True
    timeout_s = 30

    async def run(self, start: str = "", end: str = "", limit: int = 10,
                  **_) -> ToolResult:
        try:
            events = await asyncio.to_thread(_list_events, start, end, limit)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        if not events:
            text = "Tidak ada acara Google Calendar pada rentang tersebut."
        else:
            lines = [_event_line(item) for item in events]
            text = f"Ada {len(lines)} acara: " + "; ".join(lines)
        return ToolResult.success(text, display=text)


class _NextParams(BaseModel):
    pass


class GcalNext(Tool):
    name = "gcal_next"
    description = "Bacakan acara Google Calendar berikutnya."
    params_schema = _NextParams
    read_only = True
    timeout_s = 30

    async def run(self, **_) -> ToolResult:
        def work():
            now = datetime.now(_zone())
            svc = google_api.service("calendar", "v3", [
                WRITE_SCOPE if google_auth.has_scope(WRITE_SCOPE)
                else READ_SCOPE])
            return svc.events().list(
                calendarId="primary", timeMin=now.isoformat(),
                singleEvents=True, orderBy="startTime", maxResults=1,
                timeZone=str(_zone())).execute()
        try:
            response = await asyncio.to_thread(work)
            events = list(response.get("items") or [])
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        text = ("Acara berikutnya: " + _event_line(events[0]) if events else
                "Tidak ada acara Google Calendar berikutnya.")
        return ToolResult.success(text, display=text)


class _CreateParams(BaseModel):
    summary: str = Field(min_length=1, description="Judul acara")
    start: str = Field(description="Waktu mulai ISO-8601")
    end: str = Field(description="Waktu selesai ISO-8601")
    description: str = ""
    location: str = ""


class GcalCreate(Tool):
    name = "gcal_create"
    description = "Buat acara Google Calendar; membutuhkan scope tulis."
    params_schema = _CreateParams
    requires_confirmation = True
    timeout_s = 30

    def is_available(self) -> bool:
        return google_auth.has_write_scope("calendar")

    async def run(self, summary: str, start: str, end: str,
                  description: str = "", location: str = "", **_) -> ToolResult:
        def work():
            begin, finish = _parse_point(start), _parse_point(end)
            if finish <= begin:
                raise ValueError("waktu akhir harus setelah waktu mulai")
            body = {
                "summary": summary,
                "start": {"dateTime": begin.isoformat(),
                          "timeZone": str(_zone())},
                "end": {"dateTime": finish.isoformat(),
                        "timeZone": str(_zone())},
            }
            if description:
                body["description"] = description
            if location:
                body["location"] = location
            svc = google_api.service("calendar", "v3", [WRITE_SCOPE])
            return svc.events().insert(
                calendarId="primary", body=body,
                sendUpdates="none").execute()
        try:
            event = await asyncio.to_thread(work)
        except Exception as exc:
            return ToolResult.fail(google_api.safe_error(exc))
        text = f"Acara '{event.get('summary') or summary}' berhasil dibuat."
        return ToolResult.success(text, display=text,
                                  event_id=event.get("id", ""))
