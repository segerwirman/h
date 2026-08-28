"""Click-through visualization for one local Screen Control session."""
from __future__ import annotations

import sys
import threading
import time
from dataclasses import dataclass

from PyQt6.QtCore import QPoint, QRect, QThread, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen
from PyQt6.QtWidgets import QApplication, QWidget

WDA_EXCLUDEFROMCAPTURE = 0x00000011


class WindowsCaptureExclusion:
    """Small injectable boundary around SetWindowDisplayAffinity."""

    def __init__(self, *, setter=None, platform: str | None = None) -> None:
        self._platform = str(platform or sys.platform)
        self._setter = setter

    def exclude(self, handle: int) -> bool:
        if self._platform != "win32":
            return False
        setter = self._setter or _set_window_display_affinity
        try:
            return bool(setter(int(handle), WDA_EXCLUDEFROMCAPTURE))
        except Exception:
            return False


@dataclass(frozen=True)
class OverlayState:
    mode: str = "off"
    status: str = ""
    expires_at: float = 0.0
    cursor: tuple[int, int] | None = None
    target_rect: tuple[int, int, int, int] | None = None


class ScreenCursorOverlay(QWidget):
    """Top-level, input-transparent status and target visualization only."""

    _show_requested = pyqtSignal(str, float, str)
    _visual_requested = pyqtSignal(object, object, str)
    _clear_requested = pyqtSignal()

    def __init__(
        self,
        *,
        coordinates,
        capture_exclusion=None,
        clock=time.monotonic,
    ) -> None:
        flags = (
            Qt.WindowType.Tool
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        super().__init__(None, flags)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._coordinates = coordinates
        self._clock = clock
        self._state = OverlayState()
        self._capture_pause_depth = 0
        self._restore_after_capture = False
        self._pause_lock = threading.RLock()
        self.setGeometry(*self._coordinates.virtual_rect(space="logical"))
        exclusion = capture_exclusion or WindowsCaptureExclusion()
        self.capture_excluded = exclusion.exclude(int(self.winId()))
        self._show_requested.connect(self._show_state_ui)
        self._visual_requested.connect(self._update_visual_ui)
        self._clear_requested.connect(self._clear_ui)
        self.hide()

    @property
    def mode(self) -> str:
        return self._state.mode

    @property
    def status(self) -> str:
        return self._state.status

    @property
    def expires_at(self) -> float:
        return self._state.expires_at

    @property
    def cursor(self) -> tuple[int, int] | None:
        return self._state.cursor

    @property
    def target_rect(self) -> tuple[int, int, int, int] | None:
        return self._state.target_rect

    @property
    def capture_paused(self) -> bool:
        with self._pause_lock:
            return self._capture_pause_depth > 0 and not self.capture_excluded

    def show_state(self, *, mode: str, expires_at: float, status: str) -> None:
        normalized = str(mode or "off").strip().casefold()
        if normalized == "off":
            self.clear()
            return
        expires = max(0.0, float(expires_at or 0.0))
        clean_status = str(status or "")[:64]
        if self._on_ui_thread():
            self._show_state_ui(normalized, expires, clean_status)
        else:
            self._show_requested.emit(normalized, expires, clean_status)

    def _show_state_ui(self, mode: str, expires_at: float, status: str) -> None:
        self._state = OverlayState(
            mode=mode,
            status=status,
            expires_at=expires_at,
            cursor=self._state.cursor,
            target_rect=self._state.target_rect,
        )
        self.show()
        self.raise_()
        self.update()

    def update_visual(
        self,
        *,
        cursor: tuple[int, int] | None,
        target_rect: tuple[int, int, int, int] | None,
        status: str,
    ) -> None:
        clean_cursor = _point_or_none(cursor)
        clean_target = _rect_or_none(target_rect)
        clean_status = str(status or "")[:64]
        if self._on_ui_thread():
            self._update_visual_ui(clean_cursor, clean_target, clean_status)
        else:
            self._visual_requested.emit(clean_cursor, clean_target, clean_status)

    def _update_visual_ui(self, cursor, target_rect, status: str) -> None:
        self._state = OverlayState(
            mode=self._state.mode,
            status=status,
            expires_at=self._state.expires_at,
            cursor=cursor,
            target_rect=target_rect,
        )
        self.update()

    def clear(self) -> None:
        if self._on_ui_thread():
            self._clear_ui()
        else:
            self._clear_requested.emit()

    def _clear_ui(self) -> None:
        self._state = OverlayState()
        with self._pause_lock:
            self._capture_pause_depth = 0
            self._restore_after_capture = False
        self.hide()
        self.update()

    def pause_for_capture(self) -> bool:
        if self.capture_excluded:
            return False
        if not self._on_ui_thread():
            raise RuntimeError("fallback capture pause harus berjalan pada Qt UI thread")
        self._pause_ui()
        return True

    def _pause_ui(self) -> None:
        with self._pause_lock:
            self._capture_pause_depth += 1
            first_pause = self._capture_pause_depth == 1
            if first_pause:
                self._restore_after_capture = self.isVisible()
                restore = self._restore_after_capture
            else:
                restore = False
        if first_pause and restore:
            self.hide()
            _flush_ui()

    def resume_after_capture(self) -> None:
        if self.capture_excluded:
            return
        if not self._on_ui_thread():
            raise RuntimeError("fallback capture resume harus berjalan pada Qt UI thread")
        self._resume_ui()

    def _resume_ui(self) -> None:
        with self._pause_lock:
            if self._capture_pause_depth <= 0:
                return
            self._capture_pause_depth -= 1
            if self._capture_pause_depth != 0:
                return
            restore = self._restore_after_capture and self._state.mode != "off"
            self._restore_after_capture = False
        if restore:
            self.show()
            self.raise_()
            _flush_ui()

    def _on_ui_thread(self) -> bool:
        return QThread.currentThread() is self.thread()

    def paintEvent(self, _event) -> None:
        if self._state.mode == "off":
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        origin = self.geometry().topLeft()
        accent = QColor(54, 224, 206, 230)
        warning = QColor(255, 184, 76, 235)
        color = warning if self._state.mode == "handing_off" else accent

        if self._state.target_rect is not None:
            x, y, width, height = self._state.target_rect
            target = QRect(x - origin.x(), y - origin.y(), width, height)
            painter.setPen(QPen(color, 2.0, Qt.PenStyle.SolidLine))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 24))
            painter.drawRoundedRect(target, 6, 6)

        if self._state.cursor is not None:
            x, y = self._state.cursor
            point = QPoint(x - origin.x(), y - origin.y())
            painter.setPen(QPen(color, 2.5))
            painter.setBrush(QColor(10, 20, 24, 220))
            painter.drawEllipse(point, 8, 8)
            painter.drawLine(point.x() - 14, point.y(), point.x() + 14, point.y())
            painter.drawLine(point.x(), point.y() - 14, point.x(), point.y() + 14)

        remaining = max(0, int(self._state.expires_at - self._clock()))
        label = "SCREEN CONTROL"
        if self._state.mode == "handing_off":
            label = "SCREEN CONTROL · WAITING"
        detail = str(self._state.status or "active").replace("_", " ")
        text = f"{label}  ·  {detail}  ·  {remaining // 60:02d}:{remaining % 60:02d}"
        painter.setFont(QFont("Consolas", 9, QFont.Weight.DemiBold))
        metrics = painter.fontMetrics()
        box = metrics.boundingRect(text).adjusted(-12, -7, 12, 7)
        box.moveTopLeft(QPoint(20, 20))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(8, 16, 20, 220))
        painter.drawRoundedRect(box, 5, 5)
        painter.setPen(color)
        painter.drawText(box, Qt.AlignmentFlag.AlignCenter, text)


def _point_or_none(value) -> tuple[int, int] | None:
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        raise ValueError("cursor overlay harus point x/y")
    return int(value[0]), int(value[1])


def _rect_or_none(value) -> tuple[int, int, int, int] | None:
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ValueError("target overlay harus rectangle x/y/width/height")
    x, y, width, height = (int(part) for part in value)
    if width <= 0 or height <= 0:
        raise ValueError("target overlay harus positif")
    return x, y, width, height


def _flush_ui() -> None:
    app = QApplication.instance()
    if app is not None:
        app.processEvents()


def _set_window_display_affinity(handle: int, affinity: int) -> int:
    import ctypes

    return int(ctypes.windll.user32.SetWindowDisplayAffinity(handle, affinity))


__all__ = [
    "OverlayState",
    "ScreenCursorOverlay",
    "WDA_EXCLUDEFROMCAPTURE",
    "WindowsCaptureExclusion",
]
