"""The orb-hides-for-camera decision and the lit on/off indicators on the
awareness / focus-mode panel icons.

Headless: uses the pure ``camera_owns_stage`` seam and lightweight widgets
(ActionPanel / ContentStage) so nothing needs a real display.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

from PyQt6.QtWidgets import QApplication, QWidget

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


# ── orb hides while the camera owns the stage ───────────────────────────────

def test_camera_owns_stage_tracks_vision_content():
    _app()
    from jarvis.ui.stage import ContentStage
    from jarvis.ui.window import camera_owns_stage
    stage = ContentStage()
    stage.register("vision", QWidget())
    stage.register("info", QWidget())

    assert camera_owns_stage(stage) is False        # empty stage → orb visible
    stage.begin_loading("vision")
    assert camera_owns_stage(stage) is True          # loading camera → orb hides
    stage.activate("vision")
    assert camera_owns_stage(stage) is True          # camera active → orb hidden
    stage.activate("info")
    assert camera_owns_stage(stage) is False          # other content → orb back
    stage.hide_all()
    assert camera_owns_stage(stage) is False


# ── lit on/off indicators on the panel icons ────────────────────────────────

def test_awareness_and_focus_mode_are_glyph_buttons_with_indicator():
    _app()
    from jarvis.ui.actionpanel import ActionPanel, GlyphButton
    parent = QWidget()               # hold a ref so Qt doesn't GC the buttons
    panel = ActionPanel(parent)
    for name in ("awareness", "focus_mode"):
        assert isinstance(panel._buttons[name], GlyphButton)
        assert panel._buttons[name]._active is False
        panel.set_indicator(name, True)
        assert panel._buttons[name]._active is True
        panel.set_indicator(name, False)
        assert panel._buttons[name]._active is False


def test_glyph_button_paints_active_lamp_without_raising():
    from PyQt6.QtGui import QPixmap
    _app()
    from jarvis.ui.actionpanel import ActionPanel
    parent = QWidget()               # hold a ref so Qt doesn't GC the buttons
    panel = ActionPanel(parent)
    btn = panel._buttons["awareness"]
    btn.resize(44, 40)
    for active in (False, True):
        panel.set_indicator("awareness", active)
        pm = QPixmap(btn.size())
        pm.fill()
        btn.render(pm)      # raises through if paintEvent throws
