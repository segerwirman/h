"""Floating overlays (Part 1.2) — SYS MONITOR, ACTIVITY LOG, FILE UPLOAD,
VISION PANEL. All are slide-in panels bound to hotkeys + edge hover; nothing
is permanently on screen. Borderless: separation via spacing and glow.
"""
from __future__ import annotations

import html
import time
from pathlib import Path

from PyQt6.QtCore import (QEasingCurve, QPropertyAnimation, QRect, Qt,
                          QTimer, pyqtSignal)
from PyQt6.QtGui import QColor, QPainter, QPixmap, QTransform
from PyQt6.QtWidgets import (QFileDialog, QLabel, QTextEdit, QVBoxLayout,
                             QWidget)

from jarvis.core import config
from jarvis.core.bus import BUS
from jarvis.ui import theme


class SlidePanel(QWidget):
    """Base: hidden panel that slides in from an edge (ease-out, 200-350 ms)."""

    def __init__(self, parent: QWidget, edge: str, size_px: int):
        super().__init__(parent)
        self.edge = edge                      # "left" | "right" | "top"
        self.size_px = size_px
        self._shown = False
        self._ms = int(config.get("motion.transition_max_ms", 350))
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        self.hide()

    def _rects(self) -> tuple[QRect, QRect]:
        p = self.parentWidget()
        w, h = p.width(), p.height()
        if self.edge == "left":
            shown = QRect(0, 48, self.size_px, h - 48 - 56)
            hidden = shown.translated(-self.size_px - 12, 0)
        elif self.edge == "right":
            shown = QRect(w - self.size_px, 48, self.size_px, h - 48 - 56)
            hidden = shown.translated(self.size_px + 12, 0)
        else:
            shown = QRect(0, 0, w, self.size_px)
            hidden = shown.translated(0, -self.size_px - 12)
        return shown, hidden

    def toggle(self) -> None:
        self.set_shown(not self._shown)

    def set_shown(self, shown: bool) -> None:
        if shown == self._shown:
            return
        self._shown = shown
        tgt_shown, tgt_hidden = self._rects()
        if shown:
            self.setGeometry(tgt_hidden)
            self.show()
            self.raise_()
        anim = QPropertyAnimation(self, b"geometry", self)
        anim.setDuration(self._ms)
        anim.setStartValue(self.geometry())
        anim.setEndValue(tgt_shown if shown else tgt_hidden)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        if not shown:
            anim.finished.connect(self.hide)
        self._anim = anim
        anim.start()

    def reposition(self) -> None:
        if self._shown:
            self.setGeometry(self._rects()[0])

    @property
    def shown(self) -> bool:
        return self._shown


class SysStatsOverlay(SlidePanel):
    """Top-left system metrics — visible only on F1 / edge hover."""

    def __init__(self, parent: QWidget):
        super().__init__(parent, "left", 210)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 18, 16)
        lay.setSpacing(10)
        title = QLabel("SYS MONITOR")
        title.setFont(theme.header_font(11))
        title.setStyleSheet(f"color: {theme.PAL.secondary}; background: transparent;"
                            "letter-spacing: 3px;")
        lay.addWidget(title)
        self._rows: dict[str, QLabel] = {}
        for key in ("CPU", "MEM", "GPU", "NET", "TMP", "UPTIME"):
            lbl = QLabel(f"{key}  —")
            lbl.setFont(theme.mono_font(10))
            lbl.setStyleSheet(f"color: {theme.PAL.text}; background: transparent;")
            lay.addWidget(lbl)
            self._rows[key] = lbl
        lay.addStretch()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._timer.start(int(float(config.get("overlays.sys_stats_poll_s", 2.0)) * 1000))
        self._last_net = None

    def _refresh(self) -> None:
        if not self.shown:
            return
        try:
            import psutil
            cpu = psutil.cpu_percent(interval=None)
            mem = psutil.virtual_memory().percent
            self._rows["CPU"].setText(f"CPU  {cpu:4.0f} %")
            self._rows["MEM"].setText(f"MEM  {mem:4.0f} %")
            net = psutil.net_io_counters()
            now = time.time()
            if self._last_net:
                dt = now - self._last_net[2]
                rate = ((net.bytes_recv - self._last_net[0])
                        + (net.bytes_sent - self._last_net[1])) / max(dt, 0.1)
                self._rows["NET"].setText(f"NET  {rate/1024:6.0f} KB/s")
            self._last_net = (net.bytes_recv, net.bytes_sent, now)
            up = time.time() - psutil.boot_time()
            self._rows["UPTIME"].setText(f"UP   {int(up//3600):02d}:{int(up%3600//60):02d}")
        except Exception:
            pass
        try:
            import pynvml
            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            gpu = pynvml.nvmlDeviceGetUtilizationRates(h).gpu
            tmp = pynvml.nvmlDeviceGetTemperature(h, pynvml.NVML_TEMPERATURE_GPU)
            self._rows["GPU"].setText(f"GPU  {gpu:4.0f} %")
            self._rows["TMP"].setText(f"TMP  {tmp:4.0f} °C")
        except Exception:
            self._rows["GPU"].setText("GPU   n/a")
            self._rows["TMP"].setText("TMP   n/a")


class ActivityLogDrawer(SlidePanel):
    """Right drawer — structured activity log (F2 / right-edge hover)."""

    _line_sig = pyqtSignal(str, str)          # (level, message)

    def __init__(self, parent: QWidget):
        super().__init__(parent, "right", 360)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 14, 16)
        lay.setSpacing(8)
        title = QLabel("ACTIVITY LOG")
        title.setFont(theme.header_font(11))
        title.setStyleSheet(f"color: {theme.PAL.secondary}; background: transparent;"
                            "letter-spacing: 3px;")
        lay.addWidget(title)
        self._text = QTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setFont(theme.mono_font(9))
        self._text.setStyleSheet(
            f"QTextEdit {{ background: transparent; color: {theme.PAL.text};"
            f" border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {theme.PAL.text_dim};"
            f" border-radius: 3px; }}")
        lay.addWidget(self._text, stretch=1)
        self._max_lines = int(config.get("overlays.log_max_lines", 500))
        self._line_sig.connect(self._append)

    def add_line(self, level: str, message: str) -> None:
        """Thread-safe append."""
        self._line_sig.emit(level, message)

    def _append(self, level: str, message: str) -> None:
        color = theme.PAL.log_colors.get(level, theme.PAL.text)
        ts = time.strftime("%H:%M:%S")
        self._text.append(
            f'<span style="color:{theme.PAL.text_dim}">{ts}</span> '
            f'<span style="color:{color}">{message}</span>')
        doc = self._text.document()
        while doc.blockCount() > self._max_lines:
            cursor = self._text.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()


class TaskResultDrawer(SlidePanel):
    """Right drawer khusus task agent: TUGAS, PROSES, HASIL, dan GAGAL.

    Berbeda dari Activity Log (F2) yang berisi jejak teknis lengkap. Drawer ini
    adalah ringkasan yang layak dibaca user dan dibuka bersama Sys Monitor
    lewat F1, sehingga progres dan hasil tidak lagi menutupi orb secara tetap.
    """

    _entry_sig = pyqtSignal(str, str)          # (kind, text), thread-safe

    _COLORS = {
        "TUGAS": "secondary",
        "PROSES": "text_dim",
        "AGENT": "accent",
        "HASIL": "success",
        "GAGAL": "alert",
    }

    def __init__(self, parent: QWidget):
        super().__init__(parent, "right", int(config.get(
            "overlays.task_result_width", 420)))
        lay = QVBoxLayout(self)
        lay.setContentsMargins(18, 16, 14, 16)
        lay.setSpacing(8)
        title = QLabel("INFO / HASIL TUGAS")
        title.setFont(theme.header_font(11))
        title.setStyleSheet(f"color: {theme.PAL.secondary}; background: transparent;"
                            "letter-spacing: 3px;")
        lay.addWidget(title)
        hint = QLabel("F1 · sembunyikan / tampilkan bersama SYS MONITOR")
        hint.setFont(theme.mono_font(8))
        hint.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;")
        lay.addWidget(hint)
        self._text = QTextEdit(self)
        self._text.setReadOnly(True)
        self._text.setFont(theme.mono_font(9))
        self._text.setStyleSheet(
            f"QTextEdit {{ background: transparent; color: {theme.PAL.text};"
            f" border: none; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 6px; }}"
            f"QScrollBar::handle:vertical {{ background: {theme.PAL.text_dim};"
            f" border-radius: 3px; }}")
        lay.addWidget(self._text, stretch=1)
        self._max_lines = int(config.get("overlays.task_result_max_lines", 160))
        self._entry_sig.connect(self._append)

    def add_entry(self, kind: str, text: str) -> None:
        """Append aman dari worker thread; credential tidak diproses di sini."""
        clean = str(text or "").strip()
        if clean:
            self._entry_sig.emit(str(kind or "INFO").upper(), clean)

    def _append(self, kind: str, text: str) -> None:
        color_name = self._COLORS.get(kind, "text")
        color = getattr(theme.PAL, color_name, theme.PAL.text)
        ts = time.strftime("%H:%M:%S")
        safe_kind = html.escape(kind)
        safe_text = html.escape(text).replace("\n", "<br>")
        self._text.append(
            f'<span style="color:{theme.PAL.text_dim}">{ts}</span> '
            f'<span style="color:{color}">[{safe_kind}]</span> '
            f'<span style="color:{theme.PAL.text}">{safe_text}</span>')
        doc = self._text.document()
        while doc.blockCount() > self._max_lines:
            cursor = self._text.textCursor()
            cursor.movePosition(cursor.MoveOperation.Start)
            cursor.select(cursor.SelectionType.BlockUnderCursor)
            cursor.removeSelectedText()
            cursor.deleteChar()


class FileDropOverlay(SlidePanel):
    """Top sheet for file upload (F3 / drag anywhere)."""

    file_selected = pyqtSignal(str)

    def __init__(self, parent: QWidget):
        super().__init__(parent, "top", 130)
        self.setAcceptDrops(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 18, 24, 18)
        self._label = QLabel("›  Lepaskan berkas di sini, atau klik untuk memilih")
        self._label.setFont(theme.header_font(13))
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._label.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;")
        lay.addWidget(self._label)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.current_file: str | None = None

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._label.setStyleSheet(
                f"color: {theme.PAL.accent}; background: transparent;")

    def dragLeaveEvent(self, e):
        self._label.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;")

    def dropEvent(self, e):
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)

    def mousePressEvent(self, e):
        path, _ = QFileDialog.getOpenFileName(
            self, "Pilih berkas untuk JARVIS", str(Path.home()))
        if path:
            self._set_file(path)

    def _set_file(self, path: str) -> None:
        self.current_file = path
        p = Path(path)
        self._label.setText(f"◈  {p.name}  ·  {p.stat().st_size // 1024} KB")
        self._label.setStyleSheet(
            f"color: {theme.PAL.success}; background: transparent;")
        self.file_selected.emit(path)
        self.set_shown(False)


class VisionPanel(QWidget):
    """ContentStage child (Part 4.4): annotated camera feed + live status.
    Frames arrive pre-annotated (boxes, skeleton, gesture, armed flag) from
    the vision process as JPEG bytes on the bus."""

    frame_available = pyqtSignal()

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setStyleSheet(f"background: {theme.PAL.base};")
        self._pix: QPixmap | None = None
        self._status = "vision offline"
        self._status_color = theme.PAL.text_dim
        BUS.subscribe("vision.frame", self._on_frame, ui=True)
        BUS.subscribe("vision.status", self._on_status, ui=True)

    def _on_frame(self, d: dict) -> None:
        px = QPixmap()
        if px.loadFromData(d["jpeg"]):
            self._pix = px
            self.frame_available.emit()
            if self.isVisible():
                self.update()

    def _on_status(self, d: dict) -> None:
        armed = d.get("armed", False)
        alive = d.get("alive", False)
        detail = d.get("detail", "")
        if not alive:
            self._status, self._status_color = f"OFFLINE — {detail}", theme.PAL.alert
        elif armed:
            self._status, self._status_color = "ARMED — kontrol gestur aktif", theme.PAL.alert
        else:
            self._status, self._status_color = f"disarmed · {detail}", theme.PAL.text_dim
        self.update()

    @property
    def has_payload(self) -> bool:
        return self._pix is not None

    def paintEvent(self, _e) -> None:
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(theme.PAL.base))
        if self._pix is not None:
            pix = self._pix
            # Selfie view: mirror the preview horizontally (display-only; the
            # frame JARVIS analyses stays un-mirrored via the worker).
            if bool(config.get("vision.preview_selfie", True)):
                pix = pix.transformed(QTransform().scale(-1, 1))
            scaled = pix.scaled(self.size(),
                                Qt.AspectRatioMode.KeepAspectRatio,
                                Qt.TransformationMode.SmoothTransformation)
            x = (self.width() - scaled.width()) // 2
            y = (self.height() - scaled.height()) // 2
            p.drawPixmap(x, y, scaled)
        p.setPen(QColor(self._status_color))
        p.setFont(theme.mono_font(10))
        p.drawText(self.rect().adjusted(12, 8, -12, -8),
                   Qt.AlignmentFlag.AlignBottom | Qt.AlignmentFlag.AlignLeft,
                   self._status)
