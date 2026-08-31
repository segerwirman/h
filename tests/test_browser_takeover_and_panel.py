"""The orb-hides-for-camera decision and the lit on/off indicators on the
awareness / focus-mode panel icons.

Headless: uses the pure ``camera_owns_stage`` seam and lightweight widgets
(ActionPanel / ContentStage) so nothing needs a real display.
"""
from __future__ import annotations

import os
from contextlib import contextmanager

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

from PyQt6.QtWidgets import QApplication, QWidget

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


@contextmanager
def _panel_with_awareness():
    """ActionPanel dengan ikon awareness di-opt-in eksplisit.

    UI U1 memensiunkan awareness dari panel DEFAULT (lihat
    ``test_actionpanel_awareness_retire.py``), tetapi ikonnya tetap didukung
    bila dikonfigurasi. Cakupan GlyphButton di bawah masih bernilai, jadi
    ikonnya diminta lewat config alih-alih dihapus dari test — pola yang sama
    dipakai test retire itu sendiri.
    """
    from jarvis.core import config
    from jarvis.ui.actionpanel import ActionPanel

    _app()
    data = config._load()
    section = data.setdefault("action_panel", {})
    original = section.get("icons")
    section["icons"] = ["awareness", "focus_mode", "studio"]
    parent = QWidget()               # hold a ref so Qt doesn't GC the buttons
    try:
        yield ActionPanel(parent)
    finally:
        if original is None:
            section.pop("icons", None)
        else:
            section["icons"] = original
        parent.close()


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
    from jarvis.ui.actionpanel import GlyphButton
    with _panel_with_awareness() as panel:
        for name in ("awareness", "focus_mode"):
            assert isinstance(panel._buttons[name], GlyphButton)
            assert panel._buttons[name]._active is False
            panel.set_indicator(name, True)
            assert panel._buttons[name]._active is True
            panel.set_indicator(name, False)
            assert panel._buttons[name]._active is False


def test_screen_control_uses_dedicated_painted_share_button():
    from jarvis.ui.actionpanel import ActionPanel, GlyphButton, ScreenShareButton

    _app()
    parent = QWidget()
    panel = ActionPanel(parent)
    button = panel._buttons["screen_control"]
    try:
        assert isinstance(button, ScreenShareButton)
        assert not isinstance(button, GlyphButton)
        assert "tab Chrome" in button.toolTip()
        assert "tab Chrome" in button.accessibleName()
        assert button.text() == ""

        panel.set_indicator("screen_control", True)
        assert button._active is True
        panel.set_indicator("screen_control", False)
        assert button._active is False
    finally:
        parent.close()


def test_screen_share_button_renders_offscreen_in_inactive_and_active_states():
    from PyQt6.QtGui import QPixmap
    from jarvis.ui.actionpanel import ActionPanel

    _app()
    parent = QWidget()
    panel = ActionPanel(parent)
    button = panel._buttons["screen_control"]
    button.resize(44, 40)
    try:
        for active in (False, True):
            panel.set_indicator("screen_control", active)
            pixmap = QPixmap(button.size())
            pixmap.fill()
            button.render(pixmap)
            assert pixmap.isNull() is False
    finally:
        parent.close()


def test_focus_mode_indicator_bekerja_di_panel_default():
    """focus_mode tetap ikon default — cakupannya tidak boleh bergantung
    pada opt-in awareness."""
    _app()
    from jarvis.ui.actionpanel import ActionPanel, GlyphButton
    parent = QWidget()               # hold a ref so Qt doesn't GC the buttons
    panel = ActionPanel(parent)
    assert isinstance(panel._buttons["focus_mode"], GlyphButton)
    panel.set_indicator("focus_mode", True)
    assert panel._buttons["focus_mode"]._active is True
    parent.close()


def test_glyph_button_paints_active_lamp_without_raising():
    from PyQt6.QtGui import QPixmap
    with _panel_with_awareness() as panel:
        btn = panel._buttons["awareness"]
        btn.resize(44, 40)
        for active in (False, True):
            panel.set_indicator("awareness", active)
            pm = QPixmap(btn.size())
            pm.fill()
            btn.render(pm)      # raises through if paintEvent throws
