"""Toggle ContentStage: klik ikon sama menutup, pindah panel tetap cross-fade."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _stage():
    _app()
    from jarvis.ui.stage import ContentStage, ContentStatus
    stage = ContentStage()
    stage.resize(900, 600)
    stage.show()
    _app().processEvents()
    first, second = QWidget(), QWidget()
    stage.register("vision", first)
    stage.register("home", second)
    return stage, first, second, ContentStatus


def test_toggle_panel_sama_menutup_kembali_ke_empty():
    stage, first, _second, status = _stage()
    assert stage.toggle("vision") is True
    assert stage.current == "vision"
    assert stage.status is status.ACTIVE
    assert first.isVisible()

    assert stage.toggle("vision") is False
    assert stage.current is None
    assert stage.status is status.EMPTY


def test_toggle_panel_lain_mengganti_panel_dan_menjaga_target_aktif():
    stage, first, second, status = _stage()
    stage.toggle("vision")
    assert stage.toggle("home") is True
    assert stage.current == "home"
    assert stage.status is status.ACTIVE
    assert second.isVisible()
    # Outgoing boleh masih visible selama cross-fade, namun target benar.
    assert first is not second


def test_toggle_cepat_tetap_konsisten_pada_state_akhir():
    stage, _first, _second, status = _stage()
    for _ in range(5):
        stage.toggle("vision")
        stage.toggle("vision")
    assert stage.current is None
    assert stage.status is status.EMPTY


def test_hide_all_menghentikan_animasi_lama_sebelum_keluar():
    stage, _first, _second, status = _stage()
    stage.toggle("vision")
    stage.hide_all()
    assert stage.current is None
    assert stage.status is status.EMPTY
    # Hanya fade keluar baru yang boleh hidup; fade masuk lama sudah dihentikan.
    assert len(stage._animations) <= 1


def test_stage_history_clear_menghapus_stack_saat_toggle_close():
    stage, _first, _second, _status = _stage()
    from jarvis.ui.stage_history import StageHistory
    history = StageHistory(stage)
    stage.activate("vision")
    history.record("home")
    stage.activate("home")
    assert history.depth() == 1
    history.clear()
    stage.hide_all()
    assert history.depth() == 0
    assert stage.current is None


def test_actionpanel_indicator_menyalakan_ikon_vision():
    _app()
    from jarvis.ui.actionpanel import ActionPanel
    host = QWidget()
    panel = ActionPanel(host)
    panel.set_indicator("vision", True)
    assert panel._camera_button is not None
    assert panel._camera_button._active is True
    panel.set_indicator("vision", False)
    assert panel._camera_button._active is False
