"""Regression coverage for zero-network native action paths."""
from __future__ import annotations

import asyncio
import sys
import time
import types

from actions import open_app as open_app_action
from jarvis.core import quiet
from jarvis.agent import tool_selection
from jarvis.agent.tools.app_control import OpenApp
from jarvis.agent.tools.capability_status import CapabilityStatus
from jarvis.agent.tools.local_ui import CameraClose, CameraOpen
from jarvis.core import app_registry, native_actions
from jarvis.core.router import Intent, IntentRouter


def test_natural_prefixes_reach_core_native_intents(monkeypatch):
    monkeypatch.setattr(app_registry, "resolve", lambda _name: None)
    router = IntentRouter()

    opened = router.classify("Jarvis, coba buka WhatsApp")
    camera = router.classify("Jarvis buka kamera")
    browser = router.classify("tolong buka browser")

    assert opened.intent is Intent.OPEN_APP
    assert opened.slots["app"].casefold() == "whatsapp"
    assert camera.intent is Intent.SYSTEM
    assert camera.slots["action"] == "vision_open"
    assert browser.intent is Intent.OPEN_BROWSER_AGENT


def test_windows_url_uses_native_shell(monkeypatch):
    seen = []
    monkeypatch.setattr(native_actions.platform, "system", lambda: "Windows")
    monkeypatch.setattr(
        native_actions.os,
        "startfile",
        lambda target: seen.append(target),
        raising=False,
    )
    result = native_actions.open_external_url("https://example.com")
    assert result.ok
    assert seen == ["https://example.com"]


def test_open_app_windows_start_fallback_records_failure(monkeypatch):
    events = []
    monkeypatch.setattr(open_app_action, "_SYSTEM", "Windows")
    monkeypatch.setattr(open_app_action.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        open_app_action.subprocess,
        "Popen",
        lambda *args, **kwargs: (_ for _ in ()).throw(OSError("start failed")),
    )
    monkeypatch.setattr(
        open_app_action.time,
        "sleep",
        lambda _seconds: None,
    )
    monkeypatch.setitem(sys.modules, "pyautogui", types.ModuleType("pyautogui"))
    monkeypatch.setattr(
        sys.modules["pyautogui"],
        "press",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            OSError("start menu unavailable")
        ),
        raising=False,
    )
    monkeypatch.setattr(
        sys.modules["pyautogui"],
        "write",
        lambda *_args, **_kwargs: None,
        raising=False,
    )
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )

    assert open_app_action._launch_windows("ms-settings:") is False
    assert len(events) == 1
    assert events[0][0] == "actions.open_app.windows_start_failed"
    assert isinstance(events[0][1], OSError)


def test_app_registry_launches_resolved_start_menu_target(monkeypatch):
    seen = []
    monkeypatch.setattr(app_registry, "_SYSTEM", "Windows")
    monkeypatch.setattr(
        app_registry.os,
        "startfile",
        lambda target: seen.append(target),
        raising=False,
    )
    match = app_registry.AppMatch(
        "whatsapp",
        "WhatsApp",
        r"C:\Start Menu\WhatsApp.lnk",
        "start_menu",
    )
    assert app_registry.launch_match(match)
    assert seen == [match.target]


def test_app_lookup_does_not_wait_for_background_refresh(monkeypatch):
    monkeypatch.setattr(app_registry, "_index", {})
    monkeypatch.setattr(app_registry, "_index_built_at", 0.0)
    monkeypatch.setattr(app_registry, "_refreshing", True)
    started = time.perf_counter()
    assert app_registry.resolve("spotify") is None
    assert time.perf_counter() - started < 0.05


def test_launch_application_prefers_exact_native_match(monkeypatch):
    match = app_registry.AppMatch(
        "spotify", "Spotify", r"C:\Apps\Spotify.lnk", "start_menu")
    monkeypatch.setattr(app_registry, "resolve", lambda _name: match)
    monkeypatch.setattr(app_registry, "launch_match", lambda _match: True)

    outcome = open_app_action.launch_application("Spotify")
    assert outcome.ok
    assert outcome.source == "native:start_menu"


def test_whatsapp_without_desktop_opens_explicit_web_surface(monkeypatch):
    monkeypatch.setattr(app_registry, "resolve", lambda _name: None)
    monkeypatch.setattr(
        open_app_action,
        "_open_whatsapp_web",
        lambda: open_app_action.AppLaunchOutcome(
            True, "Opened WhatsApp Web.", "whatsapp_web"),
    )
    monkeypatch.setitem(
        open_app_action._OS_LAUNCHERS,
        "Windows",
        lambda _name: (_ for _ in ()).throw(
            AssertionError("blind Start search must not run for WhatsApp")),
    )

    outcome = open_app_action.launch_application("WhatsApp")
    assert outcome.ok
    assert outcome.source == "whatsapp_web"


def test_native_agent_exposes_open_app_tool(monkeypatch):
    monkeypatch.setattr(
        open_app_action,
        "launch_application",
        lambda name: open_app_action.AppLaunchOutcome(
            True, f"Opened {name}.", "native:test"),
    )
    result = asyncio.run(OpenApp().run(name="WhatsApp"))
    assert result.ok
    assert result.meta["source"] == "native:test"


def test_whatsapp_tool_shortlist_includes_native_open_app(monkeypatch):
    monkeypatch.setattr(tool_selection.config, "get", lambda _key, default=None: default)
    selected = tool_selection.select_tool_names(
        "buka WhatsApp lalu periksa statusnya",
        {
            "open_app": OpenApp(),
            "capability_status": CapabilityStatus(),
        },
    )
    assert selected == ["capability_status", "open_app"]


def test_camera_tools_use_ui_adapter_without_model_or_network():
    class Adapter:
        def __init__(self):
            self.actions = []

        async def native_action(self, action, **_):
            self.actions.append(action)
            return True

    adapter = Adapter()
    opened = asyncio.run(CameraOpen().run(_adapter=adapter))
    closed = asyncio.run(CameraClose().run(_adapter=adapter))
    assert opened.ok and closed.ok
    assert adapter.actions == ["camera_open", "camera_close"]
