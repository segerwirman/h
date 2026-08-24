"""ActionPanel (Mark L Change 3) — floating bottom-center icon bar.

Borderless glyph buttons with subtle glow and hover highlight. Dims to
``action_panel.dim_opacity`` while the ContentStage shows content (Change 7),
back to 1.0 at home. All tunables in config.yaml.
"""
from __future__ import annotations

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (QGraphicsOpacityEffect, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QVBoxLayout, QWidget)

from jarvis.core import config, llm, log
from jarvis.ui import theme

_logger = log.get("ui.actionpanel")


class CameraButton(QPushButton):
    """Crisp vector camera control; no emoji or raster asset dependency."""

    def __init__(self, size_px: int, parent=None):
        super().__init__(parent)
        self._icon_px = size_px
        self._active = False
        self.setText("")
        self.setAccessibleName("Camera and vision panel")
        self.setToolTip("Open camera and vision panel")

    @staticmethod
    def camera_path(size: float) -> QPainterPath:
        path = QPainterPath()
        path.addRoundedRect(size * .12, size * .28, size * .76, size * .54,
                            size * .08, size * .08)
        path.addRect(size * .30, size * .18, size * .22, size * .12)
        return path

    def set_active(self, active: bool) -> None:
        if self._active != active:
            self._active = active
            self.update()

    def paintEvent(self, _event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        side = min(self.width(), self.height()) * .68
        p.translate((self.width() - side) / 2, (self.height() - side) / 2)
        color = QColor(theme.PAL.accent if (self.underMouse() or self._active)
                       else theme.PAL.text_dim)
        p.setPen(QPen(color, float(config.get("action_panel.camera_icon.stroke_px", 1.8))))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(self.camera_path(side))
        p.drawEllipse(QRectF(side * .36, side * .42, side * .28, side * .28))
        if self._active:  # a shutter lamp makes active state non-colour-only
            dot = float(config.get("action_panel.camera_icon.active_dot_px", 3))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawEllipse(QRectF(side * .76, side * .12, dot, dot))

class GlyphButton(QPushButton):
    """Text-glyph action button that can show a lit on/off lamp when active.

    Used for toggle icons (screen awareness, Focus Mode): when active the glyph
    turns accent-coloured and a small lamp is drawn in the top-right corner, so
    the on/off state is visible without relying on colour alone."""

    def __init__(self, glyph: str, icon_px: int, parent=None):
        super().__init__(glyph, parent)
        self._icon_px = int(icon_px)
        self._active = False
        self._apply_style()

    def _apply_style(self) -> None:
        col = theme.PAL.accent if self._active else theme.PAL.text_dim
        self.setStyleSheet(
            f"QPushButton {{ background: transparent; border: none;"
            f"  color: {col}; font-size: {self._icon_px}px; }}"
            f"QPushButton:hover {{ color: {theme.PAL.accent}; }}")

    def set_active(self, active: bool) -> None:
        active = bool(active)
        if active != self._active:
            self._active = active
            self._apply_style()
            self.update()

    def paintEvent(self, event) -> None:
        super().paintEvent(event)          # draws the glyph via the stylesheet
        if not self._active:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        d = float(config.get("action_panel.indicator_dot_px", 3.0))
        m = float(config.get("action_panel.indicator_margin_px", 7.0))
        c = QColor(theme.PAL.accent)
        glow = QColor(c); glow.setAlpha(90)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(self.width() - d * 2 - m, m, d * 2, d * 2))
        p.setBrush(c)
        p.drawEllipse(QRectF(self.width() - d * 1.5 - m, m + d * 0.5, d, d))


_ICONS = {           # glyph, tooltip
    "vision":     ("◉", "Vision panel — kamera + YOLO + gestur"),
    "upload":     ("⇪", "Unggah berkas untuk dianalisis"),
    "spotify":    ("♫", "Buka Spotify"),
    "settings":   ("⚙", "Pengaturan — API key"),
    "awareness":  ("◈", "Screen awareness — pause/resume"),
    "focus_mode": ("◐", "Focus Mode — pause comment narration"),
    "palette":    ("▤", "Command palette"),
    "timeline":   ("◷", "Context timeline"),
    # Semua control plane dibuka sebagai sheet lokal, bukan ContentStage.
    "capabilities": ("⬡", "Capabilities — skills, tools, MCP"),
    "messaging":    ("✉", "Messaging Settings — Telegram Control"),
    "gateway_ops":  ("⌁", "Gateway Operations — health dan approval queue"),
    # MK50 §7.3 — panel Home Assistant (CCTV, lampu, cuaca)
    "home":         ("⌂", "Home Assistant — CCTV, lampu, cuaca"),
    "studio":       ("✦", "Content Studio — project dan scene lokal"),
    # N-2 (audit 2026-08-24) — jalan keluar pembatalan untuk user UI:
    # sebelumnya hanya Telegram yang bisa membatalkan task berjalan.
    "cancel":       ("⏹", "Batalkan semua tugas agent yang sedang berjalan"),
}


class ActionPanel(QWidget):
    vision_clicked = pyqtSignal()
    upload_clicked = pyqtSignal()
    spotify_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    awareness_clicked = pyqtSignal()
    focus_mode_clicked = pyqtSignal()
    palette_clicked = pyqtSignal()
    timeline_clicked = pyqtSignal()
    capabilities_clicked = pyqtSignal()
    messaging_clicked = pyqtSignal()
    gateway_ops_clicked = pyqtSignal()
    home_clicked = pyqtSignal()          # MK50 §7.3 — Home Assistant
    studio_clicked = pyqtSignal()        # Studio C — local Content Studio
    cancel_clicked = pyqtSignal()        # N-2 — batalkan semua task berjalan

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        c = config.section("action_panel")
        self._dim = float(c.get("dim_opacity", 0.75))
        icon_px = int(c.get("icon_px", 22))
        self.panel_h = int(c.get("height", 56))
        icons = list(c.get("icons", list(_ICONS)))

        lay = QHBoxLayout(self)
        lay.setContentsMargins(18, 6, 18, 6)
        lay.setSpacing(int(c.get("spacing", 26)))

        sig = {"vision": self.vision_clicked, "upload": self.upload_clicked,
               "spotify": self.spotify_clicked, "settings": self.settings_clicked,
               "awareness": self.awareness_clicked, "focus_mode": self.focus_mode_clicked,
               "palette": self.palette_clicked, "timeline": self.timeline_clicked,
               "capabilities": self.capabilities_clicked,
               "messaging": self.messaging_clicked,
               "gateway_ops": self.gateway_ops_clicked,
               "home": self.home_clicked, "studio": self.studio_clicked,
               "cancel": self.cancel_clicked}
        self._camera_button: CameraButton | None = None
        self._buttons: dict[str, QPushButton] = {}
        for name in icons:
            glyph, tip = _ICONS.get(name, ("?", name))
            if name == "vision":
                btn: QPushButton = CameraButton(icon_px, self)
                self._camera_button = btn
            elif name == "cancel":
                # Tombol batal memakai warna merah agar jelas dari ikon lain.
                btn = GlyphButton(glyph, icon_px, self)
                col = theme.PAL.alert
                btn.setStyleSheet(
                    f"QPushButton {{ background: transparent; border: none;"
                    f"  color: {col}; font-size: {icon_px}px; }}"
                    f"QPushButton:hover {{ color: {col}; }}")
            else:
                # GlyphButton so any toggle icon can show a lit on/off lamp
                btn = GlyphButton(glyph, icon_px, self)
            self._buttons[name] = btn
            btn.setToolTip(tip)
            btn.setAccessibleName(tip)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFixedSize(icon_px + 22, icon_px + 18)
            if name in sig:
                btn.clicked.connect(sig[name].emit)
            lay.addWidget(btn)

        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(1.0)
        self.setGraphicsEffect(self._eff)

    def set_dimmed(self, dimmed: bool) -> None:
        self._eff.setOpacity(self._dim if dimmed else 1.0)

    def set_camera_active(self, active: bool) -> None:
        if self._camera_button is not None:
            self._camera_button.set_active(active)

    def set_indicator(self, name: str, active: bool) -> None:
        """Light/extinguish the on-off lamp on a toggle icon (awareness,
        focus_mode, …). Works for both the camera and glyph buttons."""
        btn = self._buttons.get(name)
        if isinstance(btn, (GlyphButton, CameraButton)):
            btn.set_active(active)

    def set_button_state(self, name: str, tooltip: str) -> None:
        """Non-color-only status update (tooltip text) for toggle icons
        that don't have a dedicated vector active-state like the camera."""
        btn = self._buttons.get(name)
        if btn is not None:
            btn.setToolTip(tooltip)

    def reposition(self, parent_w: int, parent_h: int, above_px: int) -> None:
        w = self.sizeHint().width()
        self.setGeometry((parent_w - w) // 2, parent_h - above_px - self.panel_h,
                         w, self.panel_h)
        self.raise_()


class SettingsSheet(QWidget):
    """Modal legacy: API key tetap masuk backend terenkripsi."""

    saved = pyqtSignal()

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(12)

        title = QLabel("SETTINGS")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;"
                            "letter-spacing: 4px;")
        lay.addWidget(title)

        self._hint = QLabel("Gemini API key (tersimpan aman)")
        self._hint.setFont(theme.mono_font(9))
        self._hint.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;")
        lay.addWidget(self._hint)

        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setFont(theme.mono_font(11))
        self._key.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.base}; color: {theme.PAL.text};"
            f" border: none; padding: 10px; }}")
        self._key.setText(llm.api_key() or "")
        self._key.returnPressed.connect(self._save)
        lay.addWidget(self._key)

        row = QHBoxLayout()
        for label, fn in (("SIMPAN", self._save), ("TUTUP", self.hide)):
            b = QPushButton(label)
            b.setFont(theme.header_font(10))
            b.setFixedHeight(34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: {theme.PAL.base};"
                f" color: {theme.PAL.accent}; border: none; letter-spacing: 2px;"
                f" padding: 0 22px; }}"
                f"QPushButton:hover {{ color: {theme.PAL.orb_core}; }}")
            b.clicked.connect(fn)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.hide()

    def _save(self) -> None:
        key = self._key.text().strip()
        if not key:
            return
        from jarvis.core import secrets_store
        if not secrets_store.set("jarvis/llm/gemini", key):
            _logger.error("settings.api_key_save_failed")
            self._hint.setText(
                "Gagal: backend penyimpanan terenkripsi tidak tersedia.")
            self._hint.setStyleSheet(
                f"color: {theme.PAL.alert}; background: transparent;")
            return
        llm.reset_client()          # text client rebuilds on next call
        _logger.info("settings.api_key_saved")
        self.saved.emit()
        self.hide()

    def open_centered(self, parent_w: int, parent_h: int) -> None:
        w, h = 480, 210
        self._key.setText(llm.api_key() or "")
        self.setGeometry((parent_w - w) // 2, (parent_h - h) // 2, w, h)
        self.show()
        self.raise_()
        self._key.setFocus()
