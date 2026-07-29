"""Framework maturity Phase 7 — plugin runtime applies only validated contributions."""
from __future__ import annotations


def _manifest(plugin_id: str, tools: list[str]) -> dict:
    return {
        "id": plugin_id, "name": plugin_id.title(), "version": "1.0.0",
        "entrypoint": "plugin:register", "required_toolsets": ["research"],
        "contributions": {"tools": tools}, "permissions": ["tools"],
    }


def test_runtime_menolak_manifest_tidak_valid_tanpa_reservasi_tool(tmp_path):
    from jarvis.plugins.runtime import PluginRuntime

    runtime = PluginRuntime(tmp_path / "plugins.json")
    result = runtime.activate({"id": "invalid", "contributions": {"tools": ["web_search"]}})

    assert result == {"id": "invalid", "enabled": False, "error": "field wajib kosong: name"}
    assert runtime.active_tools() == []
    assert not runtime.path.exists()


def test_runtime_rejects_duplicate_tool_contribution(tmp_path):
    from jarvis.plugins.runtime import PluginRuntime

    runtime = PluginRuntime(tmp_path / "plugins.json")
    assert runtime.activate(_manifest("one", ["web_search"]))["enabled"] is True
    result = runtime.activate(_manifest("two", ["web_search"]))

    assert result == {"id": "two", "enabled": False, "error": "tool_collision"}


def test_runtime_disable_removes_plugin_tools(tmp_path):
    from jarvis.plugins.runtime import PluginRuntime

    runtime = PluginRuntime(tmp_path / "plugins.json")
    runtime.activate(_manifest("one", ["web_search"]))
    runtime.disable("one")

    assert runtime.active_tools() == []


def test_runtime_persist_enable_state_dan_restore(tmp_path):
    from jarvis.plugins.runtime import PluginRuntime

    path = tmp_path / "plugins.json"
    first = PluginRuntime(path)
    first.activate(_manifest("one", ["web_search"]))

    restored = PluginRuntime(path)
    assert restored.active_tools() == ["web_search"]
    restored.disable("one")
    assert PluginRuntime(path).active_tools() == []


def test_runtime_restore_mengabaikan_manifest_tidak_valid(tmp_path):
    import json
    from jarvis.plugins.runtime import PluginRuntime

    path = tmp_path / "plugins.json"
    path.write_text(json.dumps([
        {"id": "stale", "contributions": {"tools": ["web_search"]}},
        _manifest("valid", ["web_search"]),
    ]), encoding="utf-8")

    assert PluginRuntime(path).active_tools() == ["web_search"]
