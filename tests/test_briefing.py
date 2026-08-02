"""Fase 16D: briefing TTS lokal (Calendar + Gmail), opt-in dan privacy-aware."""
from __future__ import annotations


def test_config_defaults_are_privacy_safe(monkeypatch):
    from jarvis.core import briefing

    # Simulate absent config -> defaults must be OFF for sensitive paths.
    monkeypatch.setattr(briefing.config, "get", lambda key, default=None: default)

    assert briefing.boot_briefing_enabled() is False
    assert briefing.boot_email_content_enabled() is False
    assert briefing.remote_boot_delivery_enabled() is False


def test_compose_briefing_combines_calendar_and_unread_count():
    from jarvis.core import briefing

    agenda = {"count": 2, "items": [
        {"title": "Standup", "time": "01 Aug 10:00"},
        {"title": "Review", "time": "01 Aug 14:00"}]}
    gmail = {"unread_count": 3, "items": []}

    text = briefing.compose_briefing(agenda=agenda, gmail=gmail, include_email_content=False)

    assert "2 acara" in text
    assert "Standup" in text
    assert "3 email" in text
    # count only, no subjects when include_email_content False
    assert "Rapat" not in text


def test_compose_briefing_empty_is_honest():
    from jarvis.core import briefing

    text = briefing.compose_briefing(
        agenda={"count": 0, "items": []}, gmail={"unread_count": 0, "items": []})

    assert "tidak ada" in text.lower()


def test_compose_never_includes_sensitive_email_subjects():
    from jarvis.core import briefing

    gmail = {"unread_count": 1, "items": [
        {"subject": "[disensor: pesan sensitif]", "sensitive": True, "sender": "x@y.com", "time": "t"}]}

    text = briefing.compose_briefing(
        agenda={"count": 0, "items": []}, gmail=gmail, include_email_content=True)

    assert "disensor" not in text
    assert "1 email" in text


def test_speak_briefing_routes_to_tts_and_drawer():
    from jarvis.core import briefing

    spoken, drawer = [], []
    briefing.deliver_briefing(
        "Selamat pagi. Ada 2 acara.",
        speak=lambda t: spoken.append(t),
        drawer=lambda t: drawer.append(t))

    assert spoken == ["Selamat pagi. Ada 2 acara."]
    assert drawer == ["Selamat pagi. Ada 2 acara."]


def test_deliver_briefing_non_blocking_when_tts_fails():
    from jarvis.core import briefing

    drawer = []
    # TTS raises; briefing must still deliver to drawer and not crash.
    briefing.deliver_briefing(
        "Agenda hari ini.",
        speak=lambda t: (_ for _ in ()).throw(RuntimeError("no audio device")),
        drawer=lambda t: drawer.append(t))

    assert drawer == ["Agenda hari ini."]


def test_briefing_speech_is_bounded():
    from jarvis.core import briefing

    agenda = {"count": 10, "items": [{"title": f"Acara {i}", "time": "t"} for i in range(10)]}
    gmail = {"unread_count": 20, "items": []}

    text = briefing.compose_briefing(agenda=agenda, gmail=gmail)

    assert len(text) <= 600
