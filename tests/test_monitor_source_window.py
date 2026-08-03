"""17F: Monitor source sheet is desktop palette-only wiring."""
from __future__ import annotations
from pathlib import Path


def test_window_creates_hidden_source_sheet_and_palette_command():
    source = Path("jarvis/ui/window.py").read_text(encoding="utf-8")
    assert "MonitorSourceSheet" in source
    assert "monitor_source_sheet.hide()" in source
    assert '"action_id": "manage_monitor_sources"' in source
    assert '"manage_monitor_sources":' in source


def test_source_sheet_window_wiring_has_no_remote_voice_or_fetch_authority():
    source = Path("jarvis/ui/window.py").read_text(encoding="utf-8")
    start = source.index("MonitorSourceSheet")
    segment = source[start:start + 900]
    for forbidden in ("send_from_anywhere", "voice_", "fetch_source", "MonitorScheduler", "webbrowser"):
        assert forbidden not in segment
