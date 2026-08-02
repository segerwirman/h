"""Fase 16C: calendar_safe agenda summary + local-approved create tool."""
from __future__ import annotations

import asyncio


def test_agenda_summary_bounded_and_briefing():
    from jarvis.integrations.calendar_service import agenda_summary, agenda_briefing

    events = [
        {"summary": "Standup", "start": {"dateTime": "2026-08-01T10:00:00+07:00"}},
        {"summary": "Review", "start": {"dateTime": "2026-08-01T14:00:00+07:00"}},
    ]
    out = agenda_summary(events)
    assert out["count"] == 2
    assert out["items"][0]["title"] == "Standup"
    assert out["items"][0]["time"]

    speech = agenda_briefing(out)
    assert "2" in speech
    assert len(speech) <= 400


def test_agenda_empty():
    from jarvis.integrations.calendar_service import agenda_summary, agenda_briefing

    out = agenda_summary([])
    assert out["count"] == 0
    assert "tidak ada" in agenda_briefing(out).lower()


def test_calendar_create_tool_requires_confirmation_and_timezone():
    from jarvis.agent.tools.calendar_safe import CalendarCreateProposed

    tool = CalendarCreateProposed()
    assert tool.requires_confirmation is True
    props = tool.json_schema()["properties"]
    assert "timezone" in props
    assert "summary" in props


def test_calendar_create_no_api_call_without_confirmation(monkeypatch):
    from jarvis.agent.tools import calendar_safe
    from jarvis.agent.tools.calendar_safe import CalendarCreateProposed

    called = {"insert": 0}
    monkeypatch.setattr(calendar_safe, "_insert_event",
                        lambda body: called.__setitem__("insert", called["insert"] + 1) or {"id": "x"})
    monkeypatch.setattr(calendar_safe.google_auth, "has_write_scope", lambda api: True)

    # confirmation gate is enforced by the registry via requires_confirmation.
    # Here we prove the tool builds a proposal and only inserts when run() executes,
    # and that a bad timezone fails before any API call.
    result = asyncio.run(CalendarCreateProposed().run(
        summary="Rapat", start="2026-08-01T10:00:00", end="2026-08-01T11:00:00",
        timezone=""))
    assert result.ok is False
    assert called["insert"] == 0


def test_calendar_create_inserts_via_proposal_body(monkeypatch):
    from jarvis.agent.tools import calendar_safe
    from jarvis.agent.tools.calendar_safe import CalendarCreateProposed

    captured = {}
    monkeypatch.setattr(calendar_safe, "_insert_event",
                        lambda body: captured.update(body=body) or {"id": "evt-1", "summary": "Rapat"})
    monkeypatch.setattr(calendar_safe.google_auth, "has_write_scope", lambda api: True)

    result = asyncio.run(CalendarCreateProposed().run(
        summary="Rapat", start="2026-08-01T10:00:00", end="2026-08-01T11:00:00",
        timezone="Asia/Jakarta", reminder_minutes=10))

    assert result.ok is True
    assert captured["body"]["summary"] == "Rapat"
    assert captured["body"]["start"]["timeZone"] == "Asia/Jakarta"
    assert "evt-1" in str(result.content)
