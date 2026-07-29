"""Fase 11 — trusted-local plugin manifests."""
from __future__ import annotations

import importlib


def test_manifest_menolak_tool_di_luar_toolset():
    try:
        manifest = importlib.import_module("jarvis.plugins.manifest")
    except ModuleNotFoundError:
        manifest = None

    assert manifest is not None
    ok, detail = manifest.validate({
        "id": "local-demo", "name": "Demo", "version": "1",
        "entrypoint": "plugin:register", "required_toolsets": ["research"],
        "contributions": {"tools": ["terminal"]}, "permissions": [],
    })
    assert not ok
    assert detail == "tool di luar required_toolsets"


def test_manifest_lokal_valid_tidak_mengizinkan_network_marketplace():
    manifest = importlib.import_module("jarvis.plugins.manifest")
    ok, detail = manifest.validate({
        "id": "local-demo", "name": "Demo", "version": "1",
        "entrypoint": "plugin:register", "required_toolsets": ["research"],
        "contributions": {"tools": ["web_search"]}, "permissions": ["tools"],
    })
    assert ok
    assert detail == ""
