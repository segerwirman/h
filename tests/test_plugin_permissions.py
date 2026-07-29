"""Fase 11 — loader never imports disabled or invalid plugins."""
from __future__ import annotations

import importlib
import json


def test_loader_mencatat_invalid_manifest_tanpa_import(tmp_path):
    loader = importlib.import_module("jarvis.plugins.loader")
    folder = tmp_path / "broken"
    folder.mkdir()
    (folder / "plugin.json").write_text(json.dumps({"id": "broken"}), encoding="utf-8")
    (folder / "plugin.py").write_text("raise RuntimeError('must not import')", encoding="utf-8")

    records = loader.discover([folder])

    assert records == [{"id": "broken", "enabled": False,
                        "error": "field wajib kosong: name"}]


def test_loader_disabled_tidak_import_plugin(tmp_path):
    loader = importlib.import_module("jarvis.plugins.loader")
    folder = tmp_path / "off"
    folder.mkdir()
    (folder / "plugin.json").write_text(json.dumps({
        "id": "off", "name": "Off", "version": "1", "entrypoint": "plugin:register",
        "required_toolsets": ["research"], "contributions": {"tools": ["web_search"]},
        "permissions": ["tools"],
    }), encoding="utf-8")
    (folder / "plugin.py").write_text("raise RuntimeError('must not import')", encoding="utf-8")

    assert loader.discover([folder], disabled={"off"}) == [{"id": "off", "enabled": False,
                                                              "error": "disabled"}]
