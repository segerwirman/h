"""UI U1: awareness icon retired from the default action panel."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_default_action_panel_config_excludes_awareness_icon():
    from jarvis.core import config

    icons = list(config.get("action_panel.icons", []))
    assert "awareness" not in icons
    # Studio and Focus surfaces remain available in the default panel.
    assert "studio" in icons
    assert "focus_mode" in icons


def test_default_panel_builds_without_awareness_button_but_keeps_studio():
    _app()
    from jarvis.ui.actionpanel import ActionPanel
    from PyQt6.QtWidgets import QWidget

    parent = QWidget()
    panel = ActionPanel(parent)
    assert "awareness" not in panel._buttons
    assert "studio" in panel._buttons
    assert "focus_mode" in panel._buttons
    parent.close()


def test_awareness_signal_and_toggle_remain_available_when_explicitly_configured():
    # The watcher itself is not deleted; opt-in via config still renders the icon.
    _app()
    from jarvis.ui.actionpanel import ActionPanel
    from jarvis.core import config

    assert hasattr(ActionPanel, "awareness_clicked")
    data = config._load()
    original = data.get("action_panel", {}).get("icons")
    try:
        data.setdefault("action_panel", {})["icons"] = ["awareness", "studio"]
        from PyQt6.QtWidgets import QWidget
        parent = QWidget()
        panel = ActionPanel(parent)
        assert "awareness" in panel._buttons
        parent.close()
    finally:
        if original is not None:
            data["action_panel"]["icons"] = original
