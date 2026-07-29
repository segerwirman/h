"""Fase 8 — capability groups are surface-safe and inspectable."""
from __future__ import annotations

import importlib


def test_voice_surface_hanya_mendapat_toolset_voice_safe():
    try:
        toolsets = importlib.import_module("jarvis.agent.toolsets")
    except ModuleNotFoundError:
        toolsets = None

    assert toolsets is not None
    assert toolsets.allowed_for_surface("voice") == frozenset({"voice-safe"})
    assert toolsets.tool_allowed("terminal", "voice") is False
    assert toolsets.tool_allowed("session_search", "voice") is True


def test_desktop_toolsets_use_current_native_tool_names():
    toolsets = importlib.import_module("jarvis.agent.toolsets")

    assert toolsets.tool_allowed("open_app", "desktop")
    assert toolsets.tool_allowed("camera_open", "desktop")
    assert toolsets.tool_allowed("browser_navigate", "desktop")
    assert toolsets.tool_allowed("file_patch", "desktop")
    assert toolsets.tool_allowed("cron_delete", "desktop")
    assert not toolsets.tool_allowed("patch_file", "desktop")
    assert not toolsets.tool_allowed("cron_remove", "desktop")
