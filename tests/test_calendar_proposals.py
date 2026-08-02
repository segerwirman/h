"""Fase 16C: calendar create proposal — render lengkap + elevated-risk sebelum approval."""
from __future__ import annotations

import pytest


def test_proposal_requires_timezone():
    from jarvis.integrations.calendar_service import build_event_proposal

    with pytest.raises(ValueError):
        build_event_proposal(summary="Rapat", start="2026-08-01T10:00:00",
                             end="2026-08-01T11:00:00", timezone="")


def test_proposal_renders_all_fields():
    from jarvis.integrations.calendar_service import build_event_proposal

    p = build_event_proposal(
        summary="Rapat JARVIS", start="2026-08-01T10:00:00",
        end="2026-08-01T11:00:00", timezone="Asia/Jakarta",
        location="Kantor", attendees=[], calendar_id="primary",
        recurrence="", reminder_minutes=15)

    assert p["summary"] == "Rapat JARVIS"
    assert p["start"] == "2026-08-01T10:00:00"
    assert p["end"] == "2026-08-01T11:00:00"
    assert p["timezone"] == "Asia/Jakarta"
    assert p["location"] == "Kantor"
    assert p["calendar_id"] == "primary"
    assert p["reminder_minutes"] == 15
    assert p["elevated_risk"] is False


def test_proposal_rejects_end_before_start():
    from jarvis.integrations.calendar_service import build_event_proposal

    with pytest.raises(ValueError):
        build_event_proposal(summary="X", start="2026-08-01T11:00:00",
                             end="2026-08-01T10:00:00", timezone="Asia/Jakarta")


def test_external_attendees_flag_elevated_risk():
    from jarvis.integrations.calendar_service import build_event_proposal

    p = build_event_proposal(
        summary="Sync", start="2026-08-01T10:00:00", end="2026-08-01T11:00:00",
        timezone="Asia/Jakarta", attendees=["orang@luar.com", "lain@vendor.com"])

    assert p["elevated_risk"] is True
    assert "attendee" in " ".join(p["risk_reasons"]).lower()
    assert p["attendees"] == ["orang@luar.com", "lain@vendor.com"]


def test_recurrence_and_nonprimary_calendar_flag_elevated_risk():
    from jarvis.integrations.calendar_service import build_event_proposal

    p = build_event_proposal(
        summary="Weekly", start="2026-08-01T10:00:00", end="2026-08-01T11:00:00",
        timezone="Asia/Jakarta", recurrence="RRULE:FREQ=WEEKLY",
        calendar_id="team@group.calendar.google.com")

    assert p["elevated_risk"] is True
    reasons = " ".join(p["risk_reasons"]).lower()
    assert "berulang" in reasons or "recurr" in reasons
    assert "kalender" in reasons or "shared" in reasons


def test_proposal_summary_text_is_human_readable():
    from jarvis.integrations.calendar_service import build_event_proposal, proposal_text

    p = build_event_proposal(
        summary="Rapat", start="2026-08-01T10:00:00", end="2026-08-01T11:00:00",
        timezone="Asia/Jakarta", location="Kantor", attendees=["a@ext.com"])
    text = proposal_text(p)

    assert "Rapat" in text
    assert "Asia/Jakarta" in text
    assert "Kantor" in text
    assert "PERHATIAN" in text or "risiko" in text.lower()


def test_to_api_body_shapes_google_event():
    from jarvis.integrations.calendar_service import build_event_proposal, to_api_body

    p = build_event_proposal(
        summary="Rapat", start="2026-08-01T10:00:00", end="2026-08-01T11:00:00",
        timezone="Asia/Jakarta", reminder_minutes=10)
    body = to_api_body(p)

    assert body["summary"] == "Rapat"
    assert body["start"] == {"dateTime": "2026-08-01T10:00:00", "timeZone": "Asia/Jakarta"}
    assert body["end"] == {"dateTime": "2026-08-01T11:00:00", "timeZone": "Asia/Jakarta"}
    assert body["reminders"]["overrides"][0]["minutes"] == 10
