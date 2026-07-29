"""Framework maturity Phase 0 — declared native boundaries stay explicit."""
from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pytest_root_collects_hanya_suite_jarvis():
    config = ROOT / "pytest.ini"
    assert config.exists()
    assert "testpaths = tests" in config.read_text(encoding="utf-8")


def test_inventory_menyatakan_legacy_helper_dan_bridge_native_only():
    inventory = ROOT / "docs" / "ARCHITECTURE_INVENTORY.md"
    text = inventory.read_text(encoding="utf-8")
    assert "actions/dev_agent.py" in text
    assert "active" in text
    assert "jarvis/integrations/hermes" in text
    assert "disabled by default" in text


def test_inventory_mencatat_entry_dan_frozen_contract():
    text = (ROOT / "docs" / "ARCHITECTURE_INVENTORY.md").read_text(
        encoding="utf-8")
    assert "python -m jarvis.main" in text
    assert "config/frozen_manifest.json" in text
    assert "main.py" in text
