"""Volatile local preview and visualization-only cursor for one selected tab."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass

from PyQt6.QtCore import QPointF, QRectF, QTimer, Qt
from PyQt6.QtGui import QColor, QImage, QPainter, QPen
from PyQt6.QtWidgets import QWidget

_CURSOR_STATES = frozenset({"planned", "attempted", "verified", "ambiguous"})
_ASPECT_REL_TOLERANCE = 0.01


@dataclass(frozen=True)
class PreviewGeneration:
    target_generation: int
    document_generation: int
    observation_generation: int
    preview_generation: int


@dataclass(frozen=True)
class PreviewMetadata:
    viewport_css: tuple[float, float]
    screenshot_px: tuple[int, int]
    generation: PreviewGeneration
    captured_at: float
    expires_at: float


@dataclass(frozen=True)
class CursorVisual:
    dom_rect: tuple[float, float, float, float]
    generation: PreviewGeneration
    state: str


@dataclass(frozen=True)
class PreviewProjection:
    visible: bool = False
    cursor: tuple[float, float] | None = None
    target_rect: tuple[float, float, float, float] | None = None


def project_dom_rect(
    *,
    dom_rect,
    viewport_css,
    screenshot_px,
    preview_rect,
) -> PreviewProjection:
    """Project one viewport-relative DOM rectangle into Qt widget coordinates."""
    dom = _finite_rect(dom_rect)
    viewport = _positive_pair(viewport_css)
    screenshot = _positive_pair(screenshot_px)
    preview = _finite_rect(preview_rect)
    if (
        dom is None
        or viewport is None
        or screenshot is None
        or preview is None
        or dom[2] <= 0
        or dom[3] <= 0
        or preview[2] <= 0
        or preview[3] <= 0
    ):
        return PreviewProjection()

    viewport_w, viewport_h = viewport
    screenshot_w, screenshot_h = screenshot
    bitmap_scale_x = screenshot_w / viewport_w
    bitmap_scale_y = screenshot_h / viewport_h
    if not math.isclose(
        bitmap_scale_x,
        bitmap_scale_y,
        rel_tol=_ASPECT_REL_TOLERANCE,
        abs_tol=1e-6,
    ):
        return PreviewProjection()

    dom_x, dom_y, dom_w, dom_h = dom
    clip_left = max(0.0, dom_x)
    clip_top = max(0.0, dom_y)
    clip_right = min(viewport_w, dom_x + dom_w)
    clip_bottom = min(viewport_h, dom_y + dom_h)
    if clip_right <= clip_left or clip_bottom <= clip_top:
        return PreviewProjection()

    fit = _aspect_fit_rect(screenshot, preview)
    if fit is None:
        return PreviewProjection()
    fit_x, fit_y, fit_w, fit_h = fit
    bitmap_left = clip_left * bitmap_scale_x
    bitmap_top = clip_top * bitmap_scale_y
    bitmap_right = clip_right * bitmap_scale_x
    bitmap_bottom = clip_bottom * bitmap_scale_y
    preview_scale = fit_w / screenshot_w
    target_x = fit_x + bitmap_left * preview_scale
    target_y = fit_y + bitmap_top * preview_scale
    target_w = (bitmap_right - bitmap_left) * preview_scale
    target_h = (bitmap_bottom - bitmap_top) * preview_scale
    if target_w <= 0 or target_h <= 0:
        return PreviewProjection()
    return PreviewProjection(
        True,
        (target_x + target_w / 2.0, target_y + target_h / 2.0),
        (target_x, target_y, target_w, target_h),
    )


class TabSharePreview(QWidget):
    """Input-transparent widget that retains only an in-memory image and visual."""

    def __init__(self, *, clock=time.monotonic, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, True)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setMinimumHeight(160)
        self._clock = clock
        self._image = QImage()
        self._metadata: PreviewMetadata | None = None
        self._cursor_visual: CursorVisual | None = None
        self._projection = PreviewProjection()
        self._cursor_state = ""
        self._expiry_timer = QTimer(self)
        self._expiry_timer.setInterval(250)
        self._expiry_timer.timeout.connect(self.expire_if_stale)
        self._expiry_timer.start()

    @property
    def has_preview(self) -> bool:
        return self._metadata is not None and not self._image.isNull()

    @property
    def cursor(self) -> tuple[float, float] | None:
        return self._projection.cursor

    @property
    def target_rect(self) -> tuple[float, float, float, float] | None:
        return self._projection.target_rect

    @property
    def cursor_state(self) -> str:
        return self._cursor_state

    def replace_preview(self, image: QImage, metadata: PreviewMetadata) -> bool:
        self.clear_preview()
        if not isinstance(image, QImage) or image.isNull():
            return False
        if not _metadata_valid(metadata, now=self._now()):
            return False
        expected_w, expected_h = metadata.screenshot_px
        if image.width() != expected_w or image.height() != expected_h:
            return False
        copied = image.copy()
        if copied.isNull():
            return False
        self._image = copied
        self._metadata = metadata
        self.update()
        return True

    def update_cursor(self, visual: CursorVisual) -> bool:
        if self.expire_if_stale() or not self.has_preview:
            return False
        metadata = self._metadata
        if (
            metadata is None
            or not isinstance(visual, CursorVisual)
            or visual.state not in _CURSOR_STATES
            or visual.generation != metadata.generation
        ):
            self.clear_cursor()
            return False
        projection = project_dom_rect(
            dom_rect=visual.dom_rect,
            viewport_css=metadata.viewport_css,
            screenshot_px=metadata.screenshot_px,
            preview_rect=_qrect_tuple(self.contentsRect()),
        )
        if not projection.visible:
            self.clear_cursor()
            return False
        self._cursor_visual = visual
        self._projection = projection
        self._cursor_state = visual.state
        self.update()
        return True

    def clear_cursor(self) -> None:
        self._cursor_visual = None
        self._projection = PreviewProjection()
        self._cursor_state = ""
        self.update()

    def clear_preview(self) -> None:
        self._image = QImage()
        self._metadata = None
        self._cursor_visual = None
        self._projection = PreviewProjection()
        self._cursor_state = ""
        self.update()

    def expire_if_stale(self) -> bool:
        metadata = self._metadata
        if metadata is None:
            return False
        if self._now() < metadata.expires_at:
            return False
        self.clear_preview()
        return True

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        visual = self._cursor_visual
        if visual is not None:
            self.update_cursor(visual)

    def closeEvent(self, event) -> None:
        self.clear_preview()
        event.accept()

    def paintEvent(self, _event) -> None:
        if not self.has_preview:
            return
        metadata = self._metadata
        if metadata is None:
            return
        fit = _aspect_fit_rect(
            metadata.screenshot_px,
            _qrect_tuple(self.contentsRect()),
        )
        if fit is None:
            return
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawImage(QRectF(*fit), self._image)
        if not self._projection.visible:
            return
        color = {
            "planned": QColor(92, 190, 255, 235),
            "attempted": QColor(255, 190, 76, 235),
            "verified": QColor(54, 224, 150, 235),
            "ambiguous": QColor(255, 112, 112, 235),
        }.get(self._cursor_state)
        if color is None:
            return
        target = self._projection.target_rect
        cursor = self._projection.cursor
        if target is not None:
            painter.setPen(QPen(color, 2.0, Qt.PenStyle.SolidLine))
            painter.setBrush(QColor(color.red(), color.green(), color.blue(), 24))
            painter.drawRoundedRect(QRectF(*target), 5.0, 5.0)
        if cursor is not None:
            point = QPointF(*cursor)
            painter.setPen(QPen(color, 2.5))
            painter.setBrush(QColor(8, 16, 20, 220))
            painter.drawEllipse(point, 7.0, 7.0)
            painter.drawLine(QPointF(point.x() - 12.0, point.y()), QPointF(point.x() + 12.0, point.y()))
            painter.drawLine(QPointF(point.x(), point.y() - 12.0), QPointF(point.x(), point.y() + 12.0))

    def _now(self) -> float:
        try:
            value = float(self._clock())
        except Exception:
            return math.inf
        return value if math.isfinite(value) else math.inf


def _metadata_valid(value: object, *, now: float) -> bool:
    if not isinstance(value, PreviewMetadata):
        return False
    if _positive_pair(value.viewport_css) is None or _positive_pair(value.screenshot_px) is None:
        return False
    generation = value.generation
    if not isinstance(generation, PreviewGeneration) or any(
        type(part) is not int or part <= 0
        for part in (
            generation.target_generation,
            generation.document_generation,
            generation.observation_generation,
            generation.preview_generation,
        )
    ):
        return False
    try:
        captured_at = float(value.captured_at)
        expires_at = float(value.expires_at)
    except (TypeError, ValueError):
        return False
    return bool(
        math.isfinite(captured_at)
        and math.isfinite(expires_at)
        and captured_at <= now < expires_at
    )


def _aspect_fit_rect(
    source_size,
    destination_rect,
) -> tuple[float, float, float, float] | None:
    source = _positive_pair(source_size)
    destination = _finite_rect(destination_rect)
    if source is None or destination is None or destination[2] <= 0 or destination[3] <= 0:
        return None
    source_w, source_h = source
    dest_x, dest_y, dest_w, dest_h = destination
    scale = min(dest_w / source_w, dest_h / source_h)
    if not math.isfinite(scale) or scale <= 0:
        return None
    fit_w = source_w * scale
    fit_h = source_h * scale
    return (
        dest_x + (dest_w - fit_w) / 2.0,
        dest_y + (dest_h - fit_h) / 2.0,
        fit_w,
        fit_h,
    )


def _positive_pair(value) -> tuple[float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 2:
        return None
    try:
        pair = float(value[0]), float(value[1])
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(part) and part > 0 for part in pair):
        return None
    return pair


def _finite_rect(value) -> tuple[float, float, float, float] | None:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        return None
    try:
        rect = tuple(float(part) for part in value)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(part) for part in rect):
        return None
    return rect


def _qrect_tuple(rect) -> tuple[float, float, float, float]:
    return float(rect.x()), float(rect.y()), float(rect.width()), float(rect.height())


__all__ = [
    "CursorVisual",
    "PreviewGeneration",
    "PreviewMetadata",
    "PreviewProjection",
    "TabSharePreview",
    "project_dom_rect",
]
