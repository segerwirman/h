"""ContentStage — vision, interactive information, or Home Assistant.

Hosts exactly one registered child at a time with a short cross-fade. MK50
§7 deliberately keeps browser and messaging surfaces out of this stage.
"""
from __future__ import annotations

from enum import Enum

from PyQt6.QtCore import QEasingCurve, QPropertyAnimation, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPen
from PyQt6.QtWidgets import QGraphicsOpacityEffect, QLabel, QWidget

from jarvis.core import config
from jarvis.ui import theme


class ContentStatus(str, Enum):
    """Readiness of the *visual payload*, independent of pipeline state."""

    EMPTY = "EMPTY"
    LOADING = "LOADING"
    ACTIVE = "ACTIVE"
    ERROR = "ERROR"


class ContentStage(QWidget):
    """A stage with one authoritative, readiness-aware content model.

    A request first enters LOADING.  It only becomes ACTIVE once its mounted
    widget is ready, avoiding the old behaviour where simply starting a page
    load immediately changed the orb layout.
    """

    status_changed = pyqtSignal(str)

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._children: dict[str, QWidget] = {}
        self._current: str | None = None
        self._status = ContentStatus.EMPTY
        self._pending: str | None = None
        self._fade_ms = int(config.get("ui.content_stage.crossfade_ms",
                                       config.get("motion.crossfade_ms", 250)))
        self._empty_frame_visible = bool(config.get(
            "ui.content_stage.empty_frame_visible", True))
        self._loading_label = QLabel(str(config.get(
            "ui.content_stage.loading_indicator", "LOADING")), self)
        self._loading_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._loading_label.setFont(theme.mono_font(int(config.get(
            "ui.content_stage.loading_font_px", 9))))
        self._loading_label.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent; letter-spacing: 3px;")
        self._loading_label.hide()
        self._animations: list[QPropertyAnimation] = []

    # ── child management ─────────────────────────────────────────────────────

    def register(self, name: str, widget: QWidget) -> None:
        widget.setParent(self)
        widget.hide()
        self._children[name] = widget

    def widget(self, name: str) -> QWidget | None:
        return self._children.get(name)

    def begin_loading(self, name: str) -> None:
        """Mount intent without claiming that a visual payload is ready."""
        if name not in self._children:
            return
        self._pending = name
        self._set_status(ContentStatus.LOADING)
        self._loading_label.setText(str(config.get(
            "ui.content_stage.loading_indicator", "LOADING")))
        self._loading_label.setGeometry(self.rect())
        self._loading_label.show()
        self._loading_label.raise_()

    def activate(self, name: str) -> None:
        """Make a mounted, real payload visible and mark the stage ACTIVE."""
        if name == self._current or name not in self._children:
            if name == self._current:
                self._pending = None
                self._loading_label.hide()
                self._set_status(ContentStatus.ACTIVE)
            return
        incoming = self._children[name]
        outgoing = self._children.get(self._current) if self._current else None
        self._current = name
        self._pending = None

        incoming.setGeometry(self.rect())
        incoming.show()
        incoming.raise_()
        self._fade(incoming, 0.0, 1.0)
        if outgoing is not None:
            self._fade(outgoing, 1.0, 0.0, hide_after=outgoing)
        self._loading_label.hide()
        # Panel bisa berubah saat status tetap ACTIVE (vision → info). Tetap
        # emit agar ActionPanel memindahkan highlight ikon aktifnya.
        self._set_status(ContentStatus.ACTIVE, force=True)

    def toggle(self, name: str) -> bool:
        """Toggle satu panel ContentStage.

        Return ``True`` bila ``name`` menjadi panel aktif, ``False`` bila klik
        kedua menutupnya kembali ke EMPTY. Pergantian panel tetap memakai
        cross-fade ``activate()``; penutupan memakai cross-fade ``hide_all()``.
        """
        if name not in self._children:
            return False
        if self._current == name and self._status is ContentStatus.ACTIVE:
            self.hide_all()
            return False
        self.activate(name)
        return True

    def show_child(self, name: str) -> None:
        """Compatibility shorthand for an already-ready payload."""
        self.activate(name)

    def fail_loading(self, message: str = "") -> None:
        """Keep current content mounted while surfacing a minimal failure."""
        self._pending = None
        self._loading_label.setText(message or str(config.get(
            "ui.content_stage.error_indicator", "CONTENT UNAVAILABLE")))
        self._loading_label.setGeometry(self.rect())
        self._loading_label.show()
        self._loading_label.raise_()
        self._set_status(ContentStatus.ERROR)

    def hide_all(self) -> None:
        self._stop_animations()
        if self._current:
            outgoing = self._children.get(self._current)
            if outgoing is not None:
                self._fade(outgoing, 1.0, 0.0, hide_after=outgoing)
        self._current = None
        self._pending = None
        self._loading_label.hide()
        self._set_status(ContentStatus.EMPTY)

    @property
    def current(self) -> str | None:
        return self._current

    @property
    def status(self) -> ContentStatus:
        return self._status

    def is_loading(self, name: str) -> bool:
        return self._status is ContentStatus.LOADING and self._pending == name

    @property
    def registered_names(self) -> frozenset[str]:
        """Read-only registry view for diagnostics and contract tests."""
        return frozenset(self._children)

    def _set_status(self, status: ContentStatus, *, force: bool = False) -> None:
        if status is self._status and not force:
            return
        self._status = status
        self.status_changed.emit(status.value)

    def _fade(self, w: QWidget, start: float, end: float,
              hide_after: QWidget | None = None) -> None:
        # QGraphicsOpacityEffect is unsupported on native-compositing widgets
        # (QWebEngineView) and can crash the GPU path — those switch instantly.
        if getattr(w, "NO_FX", False):
            if hide_after is not None:
                hide_after.hide()
            return
        eff = QGraphicsOpacityEffect(w)
        w.setGraphicsEffect(eff)
        anim = QPropertyAnimation(eff, b"opacity", self)
        anim.setDuration(self._fade_ms)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)

        def _done():
            if hide_after is not None:
                hide_after.hide()
            w.setGraphicsEffect(None)
            if anim in self._animations:
                self._animations.remove(anim)

        anim.finished.connect(_done)
        self._animations.append(anim)
        anim.start()

    def _stop_animations(self) -> None:
        """Rapid toggle tidak boleh menyisakan fade lama yang nantinya
        menimpa state panel terbaru."""
        for anim in tuple(self._animations):
            effect = anim.targetObject()
            anim.stop()
            if isinstance(effect, QGraphicsOpacityEffect):
                widget = effect.parent()
                if isinstance(widget, QWidget):
                    widget.setGraphicsEffect(None)
        self._animations.clear()

    # ── geometry ─────────────────────────────────────────────────────────────

    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._current and self._current in self._children:
            self._children[self._current].setGeometry(self.rect())
        self._loading_label.setGeometry(self.rect())

    def paintEvent(self, event) -> None:
        """Borderless atmospheric frame for the otherwise empty stage."""
        super().paintEvent(event)
        if not self._empty_frame_visible or self._status is ContentStatus.ACTIVE:
            return
        c = QColor(theme.PAL.accent_dim)
        c.setAlpha(int(config.get("ui.content_stage.empty_frame_opacity", 42)))
        inset = int(config.get("ui.content_stage.frame_inset_px", 26))
        span = int(config.get("ui.content_stage.aperture_line_px", 72))
        width = float(config.get("ui.content_stage.frame_line_px", 1.0))
        r = self.rect().adjusted(inset, inset, -inset, -inset)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(c, width))
        # Four detached aperture strokes: deliberately not a rectangular border.
        p.drawLine(r.left(), r.top(), r.left() + span, r.top())
        p.drawLine(r.right() - span, r.top(), r.right(), r.top())
        p.drawLine(r.left(), r.bottom(), r.left() + span, r.bottom())
        p.drawLine(r.right() - span, r.bottom(), r.right(), r.bottom())
