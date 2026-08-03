"""Phase 2 Slice D keeps voice weather/reminder/system calls native."""
from __future__ import annotations


def test_voice_schema_exposes_native_system_slice_tools():
    from jarvis.integrations import voice_native_tools

    names = {item["name"] for item in voice_native_tools.declarations()}

    assert {"weather_lookup", "reminder_create", "system_reflex"} <= names


def test_voice_system_slice_tools_are_native_registry_owned():
    from jarvis.integrations import voice_native_tools

    assert {"weather_lookup", "reminder_create", "system_reflex"} <= (
        voice_native_tools.native_tool_names()
    )


def test_voice_installer_retires_legacy_system_slice_only():
    from types import SimpleNamespace

    from jarvis.integrations import voice_native_tools

    class _Live:
        async def _execute_tool(self, _call):
            return None

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=[
            {"name": "weather_report"},
            {"name": "reminder"},
            {"name": "computer_settings"},
            {"name": "computer_control"},
        ],
        _load_system_prompt=lambda: "base",
        JarvisLive=_Live,
    )

    voice_native_tools.install(legacy)

    names = {item["name"] for item in legacy.TOOL_DECLARATIONS}
    assert {"weather_report", "reminder", "computer_settings"}.isdisjoint(names)
    assert "computer_control" in names


def test_native_reminder_and_wifi_actions_require_confirmation():
    from jarvis.agent.tools.native_voice_system import ReminderCreate, SystemReflex

    assert ReminderCreate().needs_confirmation(
        date="2030-01-01", time="09:00", message="Tes"
    ) is True
    assert SystemReflex().needs_confirmation(action="wifi_off") is True
    assert SystemReflex().needs_confirmation(action="volume_up") is False


def test_voice_rules_hold_cua_and_vision_legacy_until_safety_gate():
    from jarvis.integrations import voice_native_tools

    rules = voice_native_tools.rules()

    assert "computer_control" in rules
    assert "screen_process" in rules
    assert "Jangan panggil" in rules
