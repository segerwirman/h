"""Fase 16C: Calendar create proposal builder — pure, no network.

Renders every event field explicitly for local desktop approval and flags
elevated-risk cases (external attendees, recurrence, shared/non-primary
calendar) so a remote/voice request can never silently create risky events.
"""
from __future__ import annotations

from datetime import datetime


def _parse(value: str) -> datetime:
    text = str(value or "").strip()
    if not text:
        raise ValueError("waktu wajib diisi (ISO-8601)")
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("waktu harus ISO-8601 (YYYY-MM-DDTHH:MM:SS)") from exc


def build_event_proposal(*, summary: str, start: str, end: str, timezone: str,
                         location: str = "", attendees: list[str] | None = None,
                         calendar_id: str = "primary", recurrence: str = "",
                         reminder_minutes: int = 10) -> dict:
    """Build a fully-rendered event proposal with explicit elevated-risk flags."""
    if not str(summary or "").strip():
        raise ValueError("judul acara wajib diisi")
    if not str(timezone or "").strip():
        raise ValueError("timezone wajib diisi untuk acara Calendar")
    begin, finish = _parse(start), _parse(end)
    if finish <= begin:
        raise ValueError("waktu selesai harus setelah waktu mulai")

    attendees = [str(a).strip() for a in (attendees or []) if str(a).strip()]
    reasons: list[str] = []
    if attendees:
        reasons.append("mengundang attendee eksternal — email undangan akan terkirim")
    if str(recurrence or "").strip():
        reasons.append("acara berulang (recurring) memengaruhi banyak tanggal")
    if str(calendar_id or "primary") != "primary":
        reasons.append("kalender bukan primary (kemungkinan shared/team)")

    return {
        "summary": str(summary).strip(),
        "start": str(start).strip(),
        "end": str(end).strip(),
        "timezone": str(timezone).strip(),
        "location": str(location or "").strip(),
        "attendees": attendees,
        "calendar_id": str(calendar_id or "primary"),
        "recurrence": str(recurrence or "").strip(),
        "reminder_minutes": max(0, int(reminder_minutes)),
        "elevated_risk": bool(reasons),
        "risk_reasons": reasons,
    }


def proposal_text(proposal: dict) -> str:
    """Human-readable desktop confirmation text listing every field."""
    lines = [
        "Buat acara Google Calendar?",
        f"Judul: {proposal['summary']}",
        f"Mulai: {proposal['start']} ({proposal['timezone']})",
        f"Selesai: {proposal['end']}",
        f"Kalender: {proposal['calendar_id']}",
    ]
    if proposal.get("location"):
        lines.append(f"Lokasi: {proposal['location']}")
    if proposal.get("attendees"):
        lines.append(f"Peserta: {', '.join(proposal['attendees'])}")
    if proposal.get("recurrence"):
        lines.append(f"Pengulangan: {proposal['recurrence']}")
    lines.append(f"Pengingat: {proposal['reminder_minutes']} menit sebelum")
    if proposal.get("elevated_risk"):
        lines.append("PERHATIAN (risiko lebih tinggi): "
                     + "; ".join(proposal.get("risk_reasons") or []))
    return "\n".join(lines)


def to_api_body(proposal: dict) -> dict:
    """Shape a validated proposal into a Google Calendar insert body."""
    tz = proposal["timezone"]
    body: dict = {
        "summary": proposal["summary"],
        "start": {"dateTime": proposal["start"], "timeZone": tz},
        "end": {"dateTime": proposal["end"], "timeZone": tz},
        "reminders": {
            "useDefault": False,
            "overrides": [{"method": "popup",
                           "minutes": int(proposal["reminder_minutes"])}],
        },
    }
    if proposal.get("location"):
        body["location"] = proposal["location"]
    if proposal.get("attendees"):
        body["attendees"] = [{"email": a} for a in proposal["attendees"]]
    if proposal.get("recurrence"):
        body["recurrence"] = [proposal["recurrence"]]
    return body


__all__ = ["build_event_proposal", "proposal_text", "to_api_body",
           "agenda_summary", "agenda_briefing"]


def _event_time_label(event: dict) -> str:
    start = event.get("start") or {}
    raw = start.get("dateTime") or start.get("date") or ""
    if "T" in raw:
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00")).strftime("%d %b %H:%M")
        except ValueError:
            return raw
    return raw or "sepanjang hari"


def agenda_summary(events: list[dict]) -> dict:
    """Bounded agenda summary from Calendar list items."""
    items = [{
        "title": str(e.get("summary") or "Acara tanpa judul"),
        "time": _event_time_label(e),
    } for e in (events or [])]
    return {"count": len(items), "items": items}


def agenda_briefing(summary: dict) -> str:
    """Short TTS-ready agenda brief, distinct from the display summary."""
    count = int(summary.get("count", 0))
    if count == 0:
        return "Tidak ada acara di kalender pada rentang tersebut."
    items = summary.get("items") or []
    lead = f"Ada {count} acara. "
    lead += "; ".join(f"{it['title']} pukul {it['time']}" for it in items[:3])
    return lead[:400]
