"""Native voice tool authority — Phase 2 slice A app actions."""
from __future__ import annotations


def test_phase2_voice_schema_replaces_legacy_app_actions_with_native_tools():
    from jarvis.integrations import voice_native_tools

    declared = {item["name"] for item in voice_native_tools.declarations()}

    assert {"open_app", "close_app"} <= declared


def test_phase2_voice_app_actions_are_owned_by_native_registry():
    from jarvis.integrations import voice_native_tools

    assert {"open_app", "close_app"} <= voice_native_tools.native_tool_names()


def test_phase2_voice_native_app_rules_require_verified_tool_result():
    from jarvis.integrations import voice_native_tools

    rules = voice_native_tools.rules()

    assert "open_app" in rules
    assert "close_app" in rules
    assert "Jangan mengaku berhasil sebelum hasil tool menyatakan sukses." in rules


def test_phase2_voice_schema_exposes_native_web_and_browser_tools():
    from jarvis.integrations import voice_native_tools

    declared = {item["name"] for item in voice_native_tools.declarations()}

    assert {"web_search", "browser_navigate", "browser_snapshot", "youtube_search"} <= declared


def test_phase2_voice_web_and_youtube_names_are_native_registry_owned():
    from jarvis.integrations import voice_native_tools

    assert {"web_search", "browser_navigate", "browser_snapshot", "youtube_search"} <= (
        voice_native_tools.native_tool_names()
    )


def test_phase2_install_removes_legacy_browser_and_youtube_declarations():
    from types import SimpleNamespace

    from jarvis.integrations import voice_native_tools

    class _Live:
        async def _execute_tool(self, _call):
            return None

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=[
            {"name": "browser_control"},
            {"name": "youtube_video"},
            {"name": "weather_report"},
        ],
        _load_system_prompt=lambda: "base",
        JarvisLive=_Live,
    )

    voice_native_tools.install(legacy)

    names = {item["name"] for item in legacy.TOOL_DECLARATIONS}
    assert "browser_control" not in names
    assert "youtube_video" not in names
    assert {"web_search", "browser_navigate", "browser_snapshot", "youtube_search"} <= names
