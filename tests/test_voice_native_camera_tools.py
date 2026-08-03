"""Phase 2 Slice F keeps camera lifecycle native and capture-free."""
from __future__ import annotations


def test_voice_schema_exposes_camera_close_and_capability_status_only():
    from jarvis.integrations import voice_native_tools

    names = {item["name"] for item in voice_native_tools.declarations()}

    assert {"camera_close", "capability_status"} <= names
    assert "camera_open" not in names
    assert "vision_analyze" not in names


def test_voice_camera_slice_is_native_registry_owned():
    from jarvis.integrations import voice_native_tools

    assert {"camera_close", "capability_status"} <= voice_native_tools.native_tool_names()


def test_voice_installer_retires_only_legacy_close_camera():
    from types import SimpleNamespace

    from jarvis.integrations import voice_native_tools

    class _Live:
        async def _execute_tool(self, _call):
            return None

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=[
            {"name": "close_camera"},
            {"name": "screen_process"},
        ],
        _load_system_prompt=lambda: "base",
        JarvisLive=_Live,
    )

    voice_native_tools.install(legacy)

    names = {item["name"] for item in legacy.TOOL_DECLARATIONS}
    assert "close_camera" not in names
    assert "screen_process" in names


def test_camera_close_never_captures_or_uploads_frame():
    from jarvis.agent.tools.local_ui import CameraClose

    tool = CameraClose()
    assert tool.name == "camera_close"
    assert tool.read_only is False
    assert "frame" not in tool.description.lower()


def test_voice_rules_keep_open_and_analyze_camera_out_of_fast_path():
    from jarvis.integrations import voice_native_tools

    rules = voice_native_tools.rules()

    assert "camera_open" in rules
    assert "vision_analyze" in rules
    assert "camera_close" in rules
    assert "Jangan panggil" in rules
