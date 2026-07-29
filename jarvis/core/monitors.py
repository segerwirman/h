"""MonitorManager — multi-monitor awareness (redesign §14).

Tracks every connected display's geometry and DPI scale factor, and reports
which one is "active" (foreground window center, falling back to cursor
position). Every coordinate transform goes through ``MonitorInfo`` so vision
and click code never assumes a single fixed display or a fixed DPI.

Coordinates are never treated as the primary replay mechanism elsewhere in
the codebase (semantic locators / accessibility selectors come first — see
``jarvis.core.target_resolver``); this module only supplies correct
geometry so that when coordinates ARE the last-resort fallback, they are at
least mapped through the right monitor and scale.

Built on Qt's ``QScreen`` (available once a ``QApplication``/``QGuiApplication``
exists), which already works identically on Windows/macOS/Linux — no
platform-specific branch needed here.
"""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.core import log

_logger = log.get("core.monitors")


@dataclass(frozen=True)
class MonitorInfo:
    name: str
    x: int
    y: int
    width: int
    height: int
    scale: float
    primary: bool

    @property
    def rect(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.width, self.height)

    def contains(self, gx: int, gy: int) -> bool:
        return self.x <= gx < self.x + self.width and self.y <= gy < self.y + self.height

    def to_local(self, gx: int, gy: int) -> tuple[int, int]:
        """Global logical coords → monitor-local pixel coords (DPI-aware)."""
        return (int((gx - self.x) * self.scale), int((gy - self.y) * self.scale))

    def to_global(self, lx: int, ly: int) -> tuple[int, int]:
        """Monitor-local pixel coords → global logical coords."""
        scale = self.scale or 1.0
        return (int(self.x + lx / scale), int(self.y + ly / scale))


class MonitorManager:
    """Reads live ``QScreen`` state on demand — cheap enough to call per
    click/capture rather than poll continuously. Callers who want live
    updates can hook ``QGuiApplication.screenAdded``/``screenRemoved``."""

    def list_monitors(self) -> list[MonitorInfo]:
        try:
            from PyQt6.QtGui import QGuiApplication
        except ImportError:
            return []
        app = QGuiApplication.instance()
        if app is None:
            return []
        primary = app.primaryScreen()
        out = []
        for scr in app.screens():
            geo = scr.geometry()
            out.append(MonitorInfo(
                name=scr.name(), x=geo.x(), y=geo.y(),
                width=geo.width(), height=geo.height(),
                scale=float(scr.devicePixelRatio()),
                primary=(scr is primary),
            ))
        return out

    def monitor_at(self, gx: int, gy: int) -> MonitorInfo | None:
        monitors = self.list_monitors()
        for m in monitors:
            if m.contains(gx, gy):
                return m
        return monitors[0] if monitors else None

    def active_monitor(self, foreground_rect: tuple[int, int, int, int] | None = None
                       ) -> MonitorInfo | None:
        """Prefer the foreground window's center; fall back to cursor position."""
        if foreground_rect is not None:
            fx, fy, fw, fh = foreground_rect
            m = self.monitor_at(fx + fw // 2, fy + fh // 2)
            if m is not None:
                return m
        try:
            from PyQt6.QtGui import QCursor, QGuiApplication
        except ImportError:
            return None
        if QGuiApplication.instance() is None:
            return None
        pos = QCursor.pos()
        return self.monitor_at(pos.x(), pos.y())


_manager: MonitorManager | None = None


def get() -> MonitorManager:
    global _manager
    if _manager is None:
        _manager = MonitorManager()
    return _manager
