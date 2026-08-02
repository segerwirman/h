"""UI U2 shared privacy denylist contract."""
from __future__ import annotations


def test_privacy_denylist_matches_title_or_app_case_insensitively():
    from jarvis.core.privacy_denylist import is_denylisted

    assert is_denylisted("Vault - KeePass", "KeePass", terms=["keepass"])
    assert is_denylisted("Password manager", "", terms=["PASSWORD"])
    assert is_denylisted("", "1Password", terms=["1password"])
    assert not is_denylisted("JARVIS", "Jarvis", terms=["keepass"])


def test_privacy_denylist_uses_awareness_config_when_terms_omitted(monkeypatch):
    from jarvis.core import privacy_denylist

    monkeypatch.setattr(privacy_denylist.config, "get", lambda path, default: ["incognito"] if path == "awareness.privacy.denylist" else default)
    assert privacy_denylist.is_denylisted("Chrome — Incognito", "Chrome")
    assert not privacy_denylist.is_denylisted("Chrome", "Chrome")


def test_privacy_denylist_has_no_capture_persistence_or_transport_authority():
    from jarvis.core import privacy_denylist

    source = open(privacy_denylist.__file__, encoding="utf-8").read().lower()
    for forbidden in ("imagegrab", "pytesseract", "path(", "requests", "webbrowser", "subprocess", "bus.publish"):
        assert forbidden not in source


def test_legacy_awareness_delegates_to_shared_privacy_denylist(monkeypatch):
    from jarvis.core import screen_awareness

    seen = []
    monkeypatch.setattr(screen_awareness, "is_denylisted", lambda title, app: seen.append((title, app)) or True)
    assert screen_awareness._is_denylisted("Private", "Vault") is True
    assert seen == [("Private", "Vault")]


def test_awareness_watcher_construction_remains_default_off_without_thread():
    from jarvis.core.screen_awareness import ScreenAwareness

    watcher = ScreenAwareness()
    try:
        assert watcher.running is False
        assert watcher.paused is False
    finally:
        watcher.stop()
