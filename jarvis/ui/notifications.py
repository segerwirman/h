"""NotificationBlipStack — minimal ambient notifications (redesign §17).

Replaces large notification panels with a stack of small blips: a status dot,
an optional short label, automatic dismissal, and a placement that never
covers ContentStage. Critical errors / destructive-action confirmations keep
using explicit panels (write_log + the confirmation gate) — this widget is
strictly for ambient, non-blocking status.
"""
from __future__ import annotations

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PyQt6.QtGui import QColor, QPainter
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QWidget

from jarvis.core import config
from jarvis.ui import theme

_STATUS_COLOR = {
    "info": lambda: theme.PAL.accent_dim,
    "success": lambda: theme.PAL.success,
    "warning": lambda: theme.PAL.log_colors.get("WARNING", theme.PAL.alert),
    "error": lambda: theme.PAL.alert,
}


class _Blip(QWidget):
    def __init__(self, title: str, body: str, status: str, parent: QWidget):
        super().__init__(parent)
        self._title = title
        self._body = body
        self._dot_px = float(config.get("ui.notifications.dot_px", 8))
        self._color = QColor(_STATUS_COLOR.get(status, _STATUS_COLOR["info"])())
        self.setFixedHeight(28)
        self.setMinimumWidth(60)
        self._eff = QGraphicsOpacityEffect(self)
        self._eff.setOpacity(0.0)
        self.setGraphicsEffect(self._eff)
        self._anim: QPropertyAnimation | None = None

    def sizeHint(self):
        fm = self.fontMetrics()
        label = self._label_text()
        w = int(self._dot_px + 10 + fm.horizontalAdvance(label) + 10) if label else int(self._dot_px + 16)
        from PyQt6.QtCore import QSize
        return QSize(max(w, 40), 28)

    def _label_text(self) -> str:
        if self._title and self._body:
            return f"{self._title}: {self._body}"[:60]
        return (self._title or self._body)[:60]

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cy = self.height() / 2
        d = self._dot_px
        glow = QColor(self._color)
        glow.setAlpha(70)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(4, cy - d, d * 2, d * 2))
        p.setBrush(self._color)
        p.drawEllipse(QRectF(4 + d / 2, cy - d / 2, d, d))
        label = self._label_text()
        if label:
            p.setPen(theme.qcolor(theme.PAL.text, 235))
            p.setFont(theme.mono_font(9))
            p.drawText(QRectF(4 + d * 2 + 8, 0, self.width() - (d * 2 + 16), self.height()),
                      Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft, label)

    def fade_in(self, ms: int) -> None:
        self._animate(0.0, 1.0, ms)

    def fade_out(self, ms: int, on_done) -> None:
        anim = self._animate(self._eff.opacity(), 0.0, ms)
        anim.finished.connect(on_done)

    def _animate(self, start: float, end: float, ms: int) -> QPropertyAnimation:
        anim = QPropertyAnimation(self._eff, b"opacity", self)
        anim.setDuration(max(1, ms))
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._anim = anim
        anim.start()
        return anim


class NotificationBlipStack(QWidget):
    """Owns a small vertical stack of auto-dismissing blips.

    Placement is config-driven (``ui.notifications.placement``) and always
    anchored to a corner away from the center stage, so it never overlaps
    ContentStage or the orb.
    """

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._blips: list[_Blip] = []
        self._muted = False
        self._focus_mode = False

    def set_muted(self, muted: bool) -> None:
        self._muted = muted

    def set_focus_mode(self, active: bool) -> None:
        self._focus_mode = active

    def push(self, title: str, body: str = "", status: str = "info") -> None:
        if self._muted:
            return
        if self._focus_mode and status not in ("error",):
            return  # Focus Mode: only critical/error blips still show
        max_stack = int(config.get("ui.notifications.max_stack", 4))
        while len(self._blips) >= max_stack:
            oldest = self._blips.pop(0)
            oldest.deleteLater()
        blip = _Blip(title, body, status, self)
        blip.resize(blip.sizeHint())
        blip.show()
        self._blips.append(blip)
        self._reflow()
        fade_ms = int(config.get("motion.crossfade_ms", 250))
        blip.fade_in(fade_ms)
        duration = int(config.get("ui.notifications.duration_ms", 3800))
        QTimer.singleShot(duration, lambda: self._dismiss(blip))

    def _dismiss(self, blip: _Blip) -> None:
        if blip not in self._blips:
            return
        fade_ms = int(config.get("motion.crossfade_ms", 250))

        def _remove():
            if blip in self._blips:
                self._blips.remove(blip)
            blip.deleteLater()
            self._reflow()
        blip.fade_out(fade_ms, _remove)

    def _reflow(self) -> None:
        placement = str(config.get("ui.notifications.placement", "top_right"))
        parent = self.parentWidget()
        if parent is None:
            return
        margin = 16
        y = margin if "top" in placement else parent.height() - margin
        step = 1 if "top" in placement else -1
        for blip in self._blips:
            w = blip.width()
            x = (parent.width() - margin - w) if "right" in placement else margin
            blip.move(x, y if step == 1 else y - blip.height())
            blip.raise_()
            y += step * (blip.height() + 6)

    def reposition(self) -> None:
        self._reflow()
