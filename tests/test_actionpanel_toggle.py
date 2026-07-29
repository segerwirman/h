"""ActionPanel toggle: vision/home, highlight, ESC, riwayat."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

from PyQt6.QtWidgets import QApplication

_APP = None


def _window():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    from jarvis.ui.window import JarvisUI
    ui = JarvisUI(services={"assistant": None, "vision": None})
    win = ui._win
    win.show()
    _APP.processEvents()
    return win


def test_vision_toggle_menutup_panel_yang_sama_dan_memadamkan_icon():
    win = _window()
    # payload dipalsukan agar begin_loading langsung bisa ACTIVE.
    win.vision_panel._pix = object()
    win.toggle_vision_panel()
    assert win.stage.current == "vision"
    assert win.action_panel._camera_button._active is True

    win.toggle_vision_panel()
    assert win.stage.current is None
    assert win.action_panel._camera_button._active is False


def test_panel_stage_berpindah_dan_highlight_vision_padam():
    win = _window()
    win.vision_panel._pix = object()
    win.toggle_vision_panel()
    assert win.stage.current == "vision"

    # Berpindah panel stage langsung: status callback memindah indikator.
    win.stage.activate("info")
    assert win.stage.current == "info"
    assert win.action_panel._camera_button._active is False


def test_escape_diam_menutup_panel_dan_membersihkan_riwayat():
    win = _window()
    from jarvis.ui.stage_history import StageHistory
    win.stage.activate("info")
    win.stage_history = StageHistory(win.stage)
    win.stage_history.record("vision")
    assert win.stage_history.depth() == 1
    win._legacy_state = "IDLE"
    win._do_interrupt()
    assert win.stage.current is None
    assert win.stage_history.depth() == 0


def test_escape_saat_bicara_interrupt_tanpa_menutup_panel():
    win = _window()
    win.stage.activate("info")
    called = []
    win.on_interrupt = lambda: called.append(True)
    win._legacy_state = "SPEAKING"
    win._do_interrupt()
    assert called == [True]
    assert win.stage.current == "info"


def test_rapid_vision_toggle_akhirnya_empty_tanpa_panel_sisa():
    win = _window()
    win.vision_panel._pix = object()
    for _ in range(4):
        win.toggle_vision_panel()
        win.toggle_vision_panel()
    assert win.stage.current is None
    assert win.action_panel._camera_button._active is False
