"""Fase 15A: Google direct mapping remote memakai wrapper privacy-tiered."""
from __future__ import annotations


def test_remote_email_maps_to_safe_summary_not_legacy_gmail_list():
    from jarvis.integrations.google_direct import match_command
    assert match_command("ada email baru?", remote=True) == ("gmail_safe_summary", {})
    assert match_command("ada email baru?", remote=False) == ("gmail_list", {"query": "is:unread"})


def test_remote_agenda_maps_to_safe_agenda_not_legacy_calendar():
    from jarvis.integrations.google_direct import match_command
    assert match_command("agenda hari ini", remote=True) == ("gcal_safe_agenda", {})
    assert match_command("agenda hari ini", remote=False) == ("gcal_events", {"start": "", "end": ""})


def test_remote_briefing_maps_to_bounded_briefing_tool():
    from jarvis.integrations.google_direct import match_command
    assert match_command("briefing pagi", remote=True) == ("morning_briefing", {})


def test_remote_cannot_map_calendar_create_through_direct_read_path():
    from jarvis.integrations.google_direct import match_command
    assert match_command("buat calendar event besok", remote=True) is None
