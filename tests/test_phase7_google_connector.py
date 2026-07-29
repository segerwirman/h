"""Fase 7 / MK50 §10 — satu Google OAuth dan tool yang scope-gated."""
from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.agent import registry
from jarvis.core import config, secrets_store
from jarvis.integrations import google_auth, google_direct, google_voice


@pytest.fixture()
def google_env(monkeypatch):
    values = {
        "providers.google.enabled": False,
        "providers.google.apis.calendar.enabled": False,
        "providers.google.apis.calendar.write": False,
        "providers.google.apis.youtube.enabled": False,
        "providers.google.apis.youtube.write": False,
        "providers.google.apis.gmail.enabled": False,
        "providers.google.apis.gmail.write": False,
        "providers.google.apis.drive.enabled": False,
        "locale.region": "ID",
        "locale.language": "id",
        "locale.timezone": "Asia/Jakarta",
        "tools.disabled_groups": [],
    }
    stored: dict[str, str] = {}
    real_get = config.get

    def fake_get(key, default=None):
        return values.get(key, real_get(key, default))

    monkeypatch.setattr(config, "get", fake_get)
    monkeypatch.setattr(secrets_store, "available", lambda: True)
    monkeypatch.setattr(secrets_store, "backend_label",
                        lambda: "Test encrypted")
    monkeypatch.setattr(secrets_store, "get", lambda key: stored.get(key))
    monkeypatch.setattr(
        secrets_store, "set",
        lambda key, value: (stored.__setitem__(key, value), True)[1])
    monkeypatch.setattr(
        secrets_store, "delete",
        lambda key: (stored.pop(key, None), True)[1])
    yield values, stored
    registry.all_tools(refresh=True)


def _grant(values: dict, stored: dict, api: str, scopes: list[str],
           *, write: bool = False) -> None:
    values["providers.google.enabled"] = True
    values[f"providers.google.apis.{api}.enabled"] = True
    if api != "drive":
        values[f"providers.google.apis.{api}.write"] = write
    stored[google_auth.TOKEN_KEY] = json.dumps({
        "token": "access-test", "refresh_token": "refresh-test",
        "scopes": scopes,
    })


def test_calendar_only_registers_only_calendar_tools(google_env):
    values, stored = google_env
    _grant(values, stored, "calendar",
           [google_auth.SCOPES["calendar"]["read"]])
    tools = registry.all_tools(refresh=True)
    assert {"gcal_events", "gcal_next"}.issubset(tools)
    assert "gcal_create" not in tools
    assert not ({"gmail_list", "gmail_read", "gmail_send",
                 "yt_subscriptions", "yt_latest", "yt_search_data",
                 "yt_my_stats", "gdrive_search", "gdrive_read"} & tools.keys())
    voice_names = {item["name"] for item in google_voice.declarations()}
    assert voice_names == {"gcal_events", "gcal_next"}
    values["tools.disabled_groups"] = ["google_cloud"]
    assert google_voice.declarations() == []
    assert google_direct.enabled_by_tool_group("gcal_events") is False


def test_write_scopes_and_toggles_change_real_schema(google_env):
    values, stored = google_env
    cal_write = google_auth.SCOPES["calendar"]["write"]
    _grant(values, stored, "calendar", [cal_write], write=False)
    assert "gcal_create" not in registry.all_tools(refresh=True)
    values["providers.google.apis.calendar.write"] = True
    assert "gcal_create" in registry.all_tools(refresh=True)

    gmail_read = google_auth.SCOPES["gmail"]["read"]
    gmail_send = google_auth.SCOPES["gmail"]["write"]
    values["providers.google.apis.gmail.enabled"] = True
    values["providers.google.apis.gmail.write"] = False
    stored[google_auth.TOKEN_KEY] = json.dumps({
        "token": "x", "scopes": [cal_write, gmail_read, gmail_send]})
    assert "gmail_send" not in registry.all_tools(refresh=True)
    values["providers.google.apis.gmail.write"] = True
    tools = registry.all_tools(refresh=True)
    assert {"gmail_list", "gmail_read", "gmail_send"}.issubset(tools)


def test_drive_and_youtube_read_tools_are_scope_gated(google_env):
    values, stored = google_env
    _grant(values, stored, "drive", [google_auth.SCOPES["drive"]["read"]])
    assert {"gdrive_search", "gdrive_read"}.issubset(
        registry.all_tools(refresh=True))
    values["providers.google.apis.youtube.enabled"] = True
    stored[google_auth.TOKEN_KEY] = json.dumps({
        "token": "x", "scopes": [
            google_auth.SCOPES["drive"]["read"],
            google_auth.SCOPES["youtube"]["read"],
        ]})
    assert {"yt_subscriptions", "yt_latest", "yt_search_data",
            "yt_my_stats"}.issubset(registry.all_tools(refresh=True))


def test_google_oauth_combines_enabled_scopes_and_stores_no_plaintext(
        google_env, monkeypatch):
    values, stored = google_env
    values["providers.google.apis.calendar.enabled"] = True
    assert google_auth.save_client("desktop-id", "desktop-secret")
    captured = {}

    def authorize(**kwargs):
        captured.update(kwargs)
        return {"access_token": "access-secret",
                "refresh_token": "refresh-secret", "expires_in": 3600,
                "scope": google_auth.SCOPES["calendar"]["read"]}

    monkeypatch.setattr(google_auth.oauth_loopback, "authorize", authorize)
    monkeypatch.setattr(
        google_auth.config_write, "set_scalar",
        lambda key, value: (values.__setitem__(key, value), True)[1])
    monkeypatch.setattr(google_auth, "refresh_registry", lambda: None)
    result = google_auth.start_login(open_browser=False)
    assert result["connected"] is True
    assert captured["redirect_host"] == "127.0.0.1"
    assert captured["scope"] == google_auth.SCOPES["calendar"]["read"]
    assert "include_granted_scopes" not in captured["extra_params"]
    token = json.loads(stored[google_auth.TOKEN_KEY])
    assert token["refresh_token"] == "refresh-secret"
    assert token["scopes"] == [google_auth.SCOPES["calendar"]["read"]]
    creds = google_auth.credentials([google_auth.SCOPES["calendar"]["read"]])
    assert creds.token == "access-secret"
    config_text = config.CONFIG_PATH.read_text(encoding="utf-8")
    assert "desktop-secret" not in config_text
    assert "access-secret" not in config_text
    assert "refresh-secret" not in config_text


class _Execute:
    def __init__(self, value):
        self.value = value

    def execute(self):
        return self.value


class _CalendarService:
    def events(self):
        return self

    def list(self, **_):
        return _Execute({"items": [{
            "summary": "Rapat proyek",
            "start": {"dateTime": "2026-07-20T09:00:00+07:00"},
        }]})


def test_acara_hari_ini_returns_spoken_text(google_env, monkeypatch):
    values, stored = google_env
    _grant(values, stored, "calendar",
           [google_auth.SCOPES["calendar"]["read"]])
    from jarvis.agent.tools import google_calendar
    monkeypatch.setattr(google_calendar.google_api, "service",
                        lambda *args, **kwargs: _CalendarService())
    result = asyncio.run(google_calendar.GcalEvents().run())
    assert result.ok and "Rapat proyek" in result.display
    assert google_direct.match_command("apa agenda hari ini") == (
        "gcal_events", {"start": "", "end": ""})


class _YouTubeService:
    def subscriptions(self):
        return self

    def channels(self):
        return self

    def playlistItems(self):
        return self

    def list(self, **kwargs):
        if kwargs.get("mine"):
            return _Execute({"items": [{"snippet": {
                "resourceId": {"channelId": "channel-1"}}}]})
        if kwargs.get("id"):
            return _Execute({"items": [{
                "contentDetails": {"relatedPlaylists": {"uploads": "up-1"}},
                "snippet": {"title": "Channel Satu"},
            }]})
        if kwargs.get("playlistId"):
            return _Execute({"items": [{"snippet": {
                "title": "Video terbaru nyata", "channelTitle": "Channel Satu",
                "publishedAt": "2026-07-20T01:00:00Z",
                "resourceId": {"videoId": "vid-1"},
            }}]})
        raise AssertionError(kwargs)


def test_latest_subscription_is_data_api_result_not_browser(
        google_env, monkeypatch):
    values, stored = google_env
    _grant(values, stored, "youtube",
           [google_auth.SCOPES["youtube"]["read"]])
    from jarvis.agent.tools import google_youtube
    monkeypatch.setattr(google_youtube, "_service",
                        lambda: _YouTubeService())
    result = asyncio.run(google_youtube.YtLatest().run())
    assert result.ok and "Video terbaru nyata" in result.display
    assert result.meta["route"] == "youtube_data_api"
    assert google_direct.match_command("video terbaru langgananku") == (
        "yt_latest", {})


class _GmailMessages:
    def list(self, **_):
        return _Execute({"messages": [{"id": "m-1"}]})

    def get(self, **_):
        return _Execute({
            "id": "m-1", "payload": {"headers": [
                {"name": "Subject", "value": "Laporan baru"},
                {"name": "From", "value": "tim@example.com"},
            ]}})


class _GmailUsers:
    def __init__(self):
        self._messages = _GmailMessages()

    def messages(self):
        return self._messages


class _GmailService:
    def users(self):
        return _GmailUsers()


def test_email_new_returns_spoken_subject(google_env, monkeypatch):
    values, stored = google_env
    _grant(values, stored, "gmail",
           [google_auth.SCOPES["gmail"]["read"]])
    from jarvis.agent.tools import gmail
    monkeypatch.setattr(gmail, "_service", lambda *args: _GmailService())
    result = asyncio.run(gmail.GmailList().run())
    assert result.ok and "Laporan baru" in result.display
    assert google_direct.match_command("bacakan email baru") == (
        "gmail_list", {"query": "is:unread"})


def test_empty_provider_startup_is_safe_and_silent(google_env):
    assert google_auth.connected() is False
    tools = registry.all_tools(refresh=True)
    google_names = {item["name"] for item in google_voice.declarations()}
    assert not google_names
    assert not ({"gcal_events", "yt_latest", "gmail_list",
                 "gdrive_search"} & tools.keys())
    assert "belum aktif" in google_direct.unavailable_message("gmail_list")
