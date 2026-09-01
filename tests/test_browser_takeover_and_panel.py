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


def test_screen_share_button_benar_benar_menggambar_empat_lapis_visual():
    """Uji PERILAKU pada piksel hasil render, bukan sekadar 'tidak crash'.

    Latar belakang RED: ukuran mutasi membuktikan test render lama di atas
    lolos walaupun ``paintEvent`` berhenti menggambar tile, aksen cyan, dan
    lampu aktif — karena satu-satunya pemeriksaannya adalah
    ``pixmap.isNull()``. Test ini mengunci keempat lapis visual pada piksel
    nyata supaya mutan itu mati.
    """
    from PyQt6.QtGui import QColor, QImage, QPainter
    from jarvis.ui import theme
    from jarvis.ui.actionpanel import ActionPanel

    _app()
    parent = QWidget()
    panel = ActionPanel(parent)
    button = panel._buttons["screen_control"]
    try:
        accent = QColor(theme.PAL.accent)
        alert = QColor(theme.PAL.alert)
        panel_bg = QColor(theme.PAL.panel)
        accent_rgb = (accent.red(), accent.green(), accent.blue())
        alert_rgb = (alert.red(), alert.green(), alert.blue())
        panel_rgb = (panel_bg.red(), panel_bg.green(), panel_bg.blue())

        def render(active: bool) -> QImage:
            panel.set_indicator("screen_control", active)
            image = QImage(button.size(), QImage.Format.Format_ARGB32)
            image.fill(QColor(0, 0, 0, 0))
            painter = QPainter(image)
            try:
                button.render(painter)
            finally:
                painter.end()
            return image

        def near(sample, target, tol=42) -> bool:
            return all(abs(a - b) <= tol for a, b in zip(sample[:3], target[:3]))

        def scan(image: QImage) -> list[tuple[int, int, int]]:
            return [
                (image.pixelColor(x, y).red(),
                 image.pixelColor(x, y).green(),
                 image.pixelColor(x, y).blue())
                for y in range(image.height())
                for x in range(image.width())
            ]

        inactive = render(False)

        # 1) Tile: warna tile berada di antara panel dan panel yang
        #    diterangkan. Menghitung "piksel buram" tidak berguna di sini —
        #    terukur seluruh kanvas 1760 piksel buram karena widget mengecat
        #    latarnya sendiri. Yang membedakan tile adalah terangnya.
        tile_hits = sum(
            1
            for y in range(inactive.height())
            for x in range(inactive.width())
            if near(inactive.pixelColor(x, y).getRgb()[:3], panel_rgb, tol=30)
            and not near(inactive.pixelColor(x, y).getRgb()[:3], (0, 0, 0), tol=6)
        )
        assert tile_hits > 200, (
            f"hanya {tile_hits} piksel berwarna tile — paintEvent tampaknya "
            f"tidak menggambar tile (harus > 200)"
        )

        # 2) Aksen cyan hadir (garis panah share).
        cyan_hits = [
            (x, y)
            for y in range(inactive.height())
            for x in range(inactive.width())
            if near(inactive.pixelColor(x, y).getRgb()[:3], accent_rgb)
            and not near(inactive.pixelColor(x, y).getRgb()[:3], alert_rgb)
        ]
        assert cyan_hits, (
            f"tidak ada piksel mendekati accent {accent_rgb} — aksen cyan hilang"
        )

        # 3) Aksen alert/pink hadir (titik indikator).
        alert_hits = [
            (x, y)
            for y in range(inactive.height())
            for x in range(inactive.width())
            if near(inactive.pixelColor(x, y).getRgb()[:3], alert_rgb)
        ]
        assert alert_hits, (
            f"tidak ada piksel mendekati alert {alert_rgb} — aksen alert hilang"
        )

        # 4) Lampu aktif berada di bagian bawah ikon. Terukur: menghitung
        #    selisih seluruh kanvas mendeteksi perubahan di mana pun, termasuk
        #    perubahan terang tile yang juga terjadi saat hover/aktif — jadi
        #    mutan "lampu dihapus" lolos. Yang dikunci di sini adalah
        #    kemunculan warna accent DI BAGIAN BAWAH.
        active = render(True)
        band_top = int(active.height() * 0.80)
        inactive_lower = [
            inactive.pixelColor(x, y).getRgb()[:3]
            for y in range(band_top, inactive.height())
            for x in range(inactive.width())
        ]
        active_lower = [
            active.pixelColor(x, y).getRgb()[:3]
            for y in range(band_top, active.height())
            for x in range(active.width())
        ]
        inactive_lamp = sum(
            1 for p in inactive_lower if near(p, accent_rgb) and not near(p, alert_rgb)
        )
        active_lamp = sum(
            1 for p in active_lower if near(p, accent_rgb) and not near(p, alert_rgb)
        )
        assert active_lamp > inactive_lamp + 5, (
            f"pita bawah tidak bertambah accent saat aktif "
            f"({inactive_lamp} -> {active_lamp}) — lampu aktif tidak tergambar"
        )
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
