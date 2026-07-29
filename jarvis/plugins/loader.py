"""Discovery for trusted local plugins. Validate before import; no auto-load."""
from __future__ import annotations

import json
from pathlib import Path

from jarvis.plugins.manifest import validate


def discover(paths, disabled: set[str] | None = None) -> list[dict]:
    disabled = set(disabled or ())
    records: list[dict] = []
    for raw in paths:
        folder = Path(raw)
        manifest_path = folder / "plugin.json"
        try:
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            records.append({"id": folder.name, "enabled": False,
                            "error": "manifest tidak dapat dibaca"})
            continue
        plugin_id = str(data.get("id", folder.name))
        if plugin_id in disabled:
            records.append({"id": plugin_id, "enabled": False, "error": "disabled"})
            continue
        ok, error = validate(data)
        records.append({"id": plugin_id, "enabled": ok, "error": error})
    return records
