"""Persistent state for validated trusted-local plugin contributions."""
from __future__ import annotations

import json
from pathlib import Path

from jarvis.agent.paths import data_dir
from jarvis.plugins.manifest import validate


class PluginRuntime:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else data_dir() / "plugins.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._plugins: dict[str, dict] = {}
        self._tools: dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            saved = []
        for manifest in saved if isinstance(saved, list) else []:
            if isinstance(manifest, dict):
                self.activate(manifest, persist=False)

    def _save(self) -> None:
        items = [item["manifest"] for item in self._plugins.values() if item["enabled"]]
        self.path.write_text(json.dumps(items, ensure_ascii=False), encoding="utf-8")

    def activate(self, manifest: dict, *, persist: bool = True) -> dict:
        plugin_id = str(manifest.get("id") or "")
        valid, error = validate(manifest)
        if not valid:
            return {"id": plugin_id, "enabled": False, "error": error}
        tools = [str(name) for name in (manifest.get("contributions") or {}).get("tools", [])]
        if not plugin_id:
            return {"id": "", "enabled": False, "error": "invalid_plugin"}
        if any(name in self._tools and self._tools[name] != plugin_id for name in tools):
            return {"id": plugin_id, "enabled": False, "error": "tool_collision"}
        self._plugins[plugin_id] = {"manifest": manifest, "enabled": True}
        for name in tools:
            self._tools[name] = plugin_id
        if persist:
            self._save()
        return {"id": plugin_id, "enabled": True, "error": ""}

    def disable(self, plugin_id: str) -> None:
        item = self._plugins.get(str(plugin_id))
        if item is None:
            return
        item["enabled"] = False
        self._tools = {name: owner for name, owner in self._tools.items() if owner != plugin_id}
        self._save()

    def active_tools(self) -> list[str]:
        return sorted(self._tools)


RUNTIME = PluginRuntime()
