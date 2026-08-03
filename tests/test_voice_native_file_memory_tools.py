"""Phase 2 Slice C keeps voice file/memory operations native and read-only."""
from __future__ import annotations


def test_voice_schema_exposes_native_file_and_memory_read_tools_only():
    from jarvis.integrations import voice_native_tools

    names = {item["name"] for item in voice_native_tools.declarations()}

    assert {"file_read", "file_search", "file_list", "memory_search"} <= names
    assert "file_write" not in names
    assert "memory_write" not in names


def test_voice_file_memory_read_tools_are_native_registry_owned():
    from jarvis.integrations import voice_native_tools

    assert {"file_read", "file_search", "file_list", "memory_search"} <= (
        voice_native_tools.native_tool_names()
    )


def test_voice_installer_retires_only_replaced_legacy_file_and_memory_tools():
    from types import SimpleNamespace

    from jarvis.integrations import voice_native_tools

    class _Live:
        async def _execute_tool(self, _call):
            return None

    legacy = SimpleNamespace(
        TOOL_DECLARATIONS=[
            {"name": "file_controller"},
            {"name": "file_processor"},
            {"name": "save_memory"},
        ],
        _load_system_prompt=lambda: "base",
        JarvisLive=_Live,
    )

    voice_native_tools.install(legacy)

    names = {item["name"] for item in legacy.TOOL_DECLARATIONS}
    assert "file_controller" not in names
    assert "save_memory" not in names
    assert "file_processor" in names
    assert {"file_read", "file_search", "file_list", "memory_search"} <= names


def test_voice_rules_forbid_unapproved_file_or_memory_writes():
    from jarvis.integrations import voice_native_tools

    rules = voice_native_tools.rules()

    assert "file_write dan memory_write" in rules
    assert "Jangan panggil file_processor" in rules
