"""Phase 21 contract — fixture script & canary registration belum ada (RED)."""
from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "content_studio_desktop_safe_acceptance.py"


def _fixture_module():
    spec = importlib.util.spec_from_file_location("content_studio_acceptance", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_content_studio_acceptance_script_exists_and_exposes_main():
    # RED: script fixture belum ada → FileNotFoundError
    module = _fixture_module()
    assert callable(module.main)


def test_accept_payload_requires_title_and_reorder_verified_blocks():
    module = _fixture_module()
    ok = {
        "accepted": True,
        "title": {"executed": True, "verified": True},
        "reorder": {"executed": True, "verified": True},
    }
    assert module._accept(ok) is True
    assert module._accept({"accepted": True}) is False
    assert module._accept({**ok, "title": {"executed": True, "verified": False}}) is False
    assert module._accept({**ok, "reorder": {"executed": False, "verified": False}}) is False
