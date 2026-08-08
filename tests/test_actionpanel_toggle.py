"""ActionPanel toggle: vision/home, highlight, ESC, riwayat."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import QApplication

_APP = None


def _payload() -> QPixmap:
    """Payload vision yang SAH — jangan pakai ``object()``.

    ``VisionPanel.paintEvent`` memanggil ``self._pix.transformed(...)``.
    Saat panel ditutup, ``ContentStage.hide_all()`` memasang
    ``QGraphicsOpacityEffect`` dan menganimasikannya, yang memaksa repaint
    sungguhan ke buffer offscreen. Dengan ``_pix = object()`` paintEvent
    meledak DI DALAM callback paint Qt — di sana exception Python tidak bisa
    dipropagasikan, sehingga proses mati 0xC0000409 dan membawa seluruh
    sesi pytest. QPixmap asli membuat has_payload tetap True tanpa jebakan itu.
    """
    return QPixmap(64, 48)


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
    win.vision_panel._pix = _payload()
    win.toggle_vision_panel()
    assert win.stage.current == "vision"
    assert win.action_panel._camera_button._active is True

    win.toggle_vision_panel()
    assert win.stage.current is None
    assert win.action_panel._camera_button._active is False


def test_panel_stage_berpindah_dan_highlight_vision_padam():
    win = _window()
    win.vision_panel._pix = _payload()
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
    win.vision_panel._pix = _payload()
    for _ in range(4):
        win.toggle_vision_panel()
        win.toggle_vision_panel()
    assert win.stage.current is None
    assert win.action_panel._camera_button._active is False
