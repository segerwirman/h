"""INFO / HASIL TUGAS drawer — ringkasan agent terpisah dari Activity Log."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def test_task_result_drawer_menyimpan_jenis_hasil_dan_escape_html():
    _app()
    from jarvis.ui.overlays import TaskResultDrawer

    host = QWidget()
    drawer = TaskResultDrawer(host)
    drawer.add_entry("TUGAS", "Buat <gambar> untuk user")
    drawer.add_entry("PROSES", "image_generate")
    drawer.add_entry("HASIL", "Gambar siap")
    drawer.add_entry("GAGAL", "tidak ada provider")
    text = drawer._text.toPlainText()
    for item in ("[TUGAS]", "[PROSES]", "[HASIL]", "[GAGAL]"):
        assert item in text
    assert "Buat <gambar> untuk user" in text
    # HTML input tidak menjadi markup pada QTextEdit.
    assert "<span" not in text


def test_task_result_drawer_bisa_hide_show_seperti_activity_log():
    _app()
    from jarvis.ui.overlays import TaskResultDrawer

    host = QWidget()
    host.resize(1200, 800)
    host.show()
    drawer = TaskResultDrawer(host)
    assert drawer.shown is False
    drawer.set_shown(True)
    assert drawer.shown is True
    assert drawer.isVisible() is True
    drawer.set_shown(False)
    assert drawer.shown is False


def test_f1_menampilkan_sys_monitor_dan_hasil_task_bersamaan():
    _app()
    from jarvis.ui.window import JarvisUI

    ui = JarvisUI(services={"assistant": None, "vision": None})
    win = ui._win
    assert win.sys_stats.shown is False
    assert win.task_results.shown is False
    win._toggle_task_result_view()
    assert win.sys_stats.shown is True
    assert win.task_results.shown is True
    # F1 kedua menutup keduanya seperti Activity Log toggle.
    win._toggle_task_result_view()
    assert win.sys_stats.shown is False
    assert win.task_results.shown is False
