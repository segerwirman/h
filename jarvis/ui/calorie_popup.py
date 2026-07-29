"""CalorieOverlay — kartu pop-up hasil analisis kalori DI DALAM frame kamera.

Permintaan user MK50. Widget ini anak dari VisionPanel dan memosisikan diri
sendiri lewat eventFilter pada parent — ``jarvis/ui/overlays.py`` (FROZEN)
tidak diubah sama sekali. Event masuk lewat BUS:

    vision.calories  {state: analyzing|result|error, analysis?, message?}

``analysis`` = jarvis.vision.food_calories.FoodAnalysis.
"""
from __future__ import annotations

import time

from PyQt6.QtCore import QEvent, QObject, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter, QPainterPath
from PyQt6.QtWidgets import QWidget

from jarvis.core import config
from jarvis.core.bus import BUS
from jarvis.ui import theme


class CalorieOverlay(QWidget):
    """Overlay pasif untuk mouse (klik menembus kecuali di kartu — klik kartu
    menutupnya). Auto-hide setelah ``agent.calorie.popup_s`` detik."""

    def __init__(self, vision_panel: QWidget):
        super().__init__(vision_panel)
        self._panel = vision_panel
        self._state = ""            # "" | analyzing | result | error
        self._analysis = None
        self._message = ""
        self._shown_at = 0.0
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.hide()

        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._dismiss)

        self._spin_timer = QTimer(self)
        self._spin_timer.timeout.connect(self.update)

        self._panel.installEventFilter(self)
        BUS.subscribe("vision.calories", self._on_event, ui=True)

    # ── event masuk ───────────────────────────────────────────────────────

    def _on_event(self, d: dict) -> None:
        state = d.get("state", "")
        if state == "analyzing":
            self._state = "analyzing"
            self._message = d.get("message", "Menganalisis makanan…")
            self._analysis = None
            self._spin_timer.start(80)
            self._hide_timer.stop()
        elif state == "result":
            self._state = "result"
            self._analysis = d.get("analysis")
            self._spin_timer.stop()
            self._arm_autohide()
        elif state == "error":
            self._state = "error"
            self._message = d.get("message", "Analisis gagal.")
            self._analysis = None
            self._spin_timer.stop()
            self._arm_autohide()
        else:
            self._dismiss()
            return
        self._shown_at = time.monotonic()
        self._reposition()
        self.show()
        self.raise_()
        self.update()

    def _arm_autohide(self) -> None:
        secs = float(config.get("agent.calorie.popup_s", 18))
        self._hide_timer.start(int(secs * 1000))

    def _dismiss(self) -> None:
        self._hide_timer.stop()
        self._spin_timer.stop()
        self._state = ""
        self.hide()

    # ── posisi: kanan-atas di dalam frame kamera ──────────────────────────

    def eventFilter(self, obj: QObject, ev: QEvent) -> bool:
        if obj is self._panel and ev.type() in (QEvent.Type.Resize,
                                                QEvent.Type.Show):
            self._reposition()
        return False

    def _card_size(self) -> tuple[int, int]:
        w = min(340, max(240, self._panel.width() // 3))
        rows = len(self._analysis.items) if (
            self._state == "result" and self._analysis
            and self._analysis.is_food) else 0
        h = 96 + rows * 20
        if self._state == "result" and self._analysis \
                and self._analysis.is_food:
            h += 34                                     # baris makro total
        return w, min(h, max(120, self._panel.height() - 32))

    def _reposition(self) -> None:
        if self._panel is None:
            return
        w, h = self._card_size()
        margin = 16
        self.setGeometry(self._panel.width() - w - margin, margin, w, h)

    def mousePressEvent(self, _e) -> None:                   # klik = tutup
        self._dismiss()

    # ── lukis kartu ───────────────────────────────────────────────────────

    def paintEvent(self, _e) -> None:
        if not self._state:
            return
        self._reposition()
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        rect = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        path = QPainterPath()
        path.addRoundedRect(rect, 10, 10)
        bg = QColor(theme.PAL.panel)
        bg.setAlpha(226)
        p.fillPath(path, bg)
        p.setPen(theme.qcolor(theme.PAL.accent, 170))
        p.drawPath(path)

        x, y = 14, 24
        p.setPen(QColor(theme.PAL.accent))
        p.setFont(theme.header_font(10))
        p.drawText(x, y, "ANALISIS KALORI")
        y += 8

        if self._state == "analyzing":
            # spinner busur berputar + pesan
            p.setPen(QColor(theme.PAL.text))
            p.setFont(theme.mono_font(9))
            p.drawText(QRectF(x, y, self.width() - 2 * x, 40),
                       Qt.AlignmentFlag.AlignLeft
                       | Qt.AlignmentFlag.AlignVCenter, self._message)
            angle = int((time.monotonic() * 300) % 360)
            arc = QRectF(self.width() - 40, y + 6, 22, 22)
            p.setPen(theme.qcolor(theme.PAL.accent, 220))
            p.drawArc(arc, -angle * 16, 120 * 16)
            return

        if self._state == "error":
            p.setPen(QColor(theme.PAL.alert))
            p.setFont(theme.mono_font(9))
            p.drawText(QRectF(x, y, self.width() - 2 * x,
                              self.height() - y - 10),
                       Qt.TextFlag.TextWordWrap
                       | Qt.AlignmentFlag.AlignLeft, self._message)
            return

        a = self._analysis
        if a is None:
            return
        if not a.is_food:
            p.setPen(QColor(theme.PAL.text))
            p.setFont(theme.mono_font(9))
            p.drawText(QRectF(x, y, self.width() - 2 * x, 40),
                       Qt.TextFlag.TextWordWrap,
                       "Tidak ada makanan terdeteksi di frame.")
            return

        # total besar
        p.setPen(QColor(theme.PAL.orb_core))
        p.setFont(theme.header_font(22))
        p.drawText(x, y + 24, f"{int(a.total_kcal)} kkal")
        p.setPen(QColor(theme.PAL.text_dim))
        p.setFont(theme.mono_font(8))
        p.drawText(x, y + 38, f"P {a.total_protein:g} g   ·   "
                              f"K {a.total_carbs:g} g   ·   "
                              f"L {a.total_fat:g} g   ·   "
                              f"conf {a.confidence:.0%}")
        y += 52

        p.setFont(theme.mono_font(9))
        for item in a.items:
            p.setPen(QColor(theme.PAL.text))
            name = item.name if len(item.name) <= 26 else \
                item.name[:25] + "…"
            p.drawText(x, y + 14, f"• {name}")
            p.setPen(QColor(theme.PAL.secondary))
            kcal = f"{int(item.calories_kcal)} kkal"
            p.drawText(QRectF(0, y, self.width() - 14, 20),
                       Qt.AlignmentFlag.AlignRight
                       | Qt.AlignmentFlag.AlignVCenter, kcal)
            y += 20
            if y > self.height() - 18:
                break
