"""ContextTimeline — scrubbable overlay of what J.A.R.V.I.S saw/did
(redesign §12).

Filterable by app/action/time/text; queries run on a background thread
(mirroring the existing `threading.Thread` + signal pattern used
throughout `jarvis/ui/window.py`) so the UI thread never blocks on a
SQLite scan. Selecting an entry only surfaces details — nothing here
executes an action, destructive or otherwise.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QListWidget,
                             QListWidgetItem, QPushButton, QVBoxLayout, QWidget)

from jarvis.core.memory import MemoryManager
from jarvis.ui import theme


class ContextTimeline(QWidget):
    entry_selected = pyqtSignal(dict)
    _results_ready = pyqtSignal(list)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 20, 24, 20)
        lay.setSpacing(10)

        title = QLabel("CONTEXT TIMELINE")
        title.setFont(theme.header_font(13))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent; letter-spacing: 3px;")
        lay.addWidget(title)

        filt_row = QHBoxLayout()
        self._app_filter = QLineEdit()
        self._app_filter.setPlaceholderText("app…")
        self._text_filter = QLineEdit()
        self._text_filter.setPlaceholderText("search…")
        for w in (self._app_filter, self._text_filter):
            w.setFont(theme.mono_font(9))
            w.setStyleSheet(
                f"QLineEdit {{ background: {theme.PAL.base}; color: {theme.PAL.text};"
                f" border: none; padding: 6px; }}")
            w.returnPressed.connect(self.reload)
            filt_row.addWidget(w)
        lay.addLayout(filt_row)

        self._list = QListWidget()
        self._list.setFont(theme.mono_font(9))
        self._list.setStyleSheet(
            f"QListWidget {{ background: transparent; color: {theme.PAL.text}; border: none; }}"
            f"QListWidget::item:selected {{ background: {theme.PAL.accent_dim}; }}")
        self._list.itemActivated.connect(self._on_item_activated)
        lay.addWidget(self._list, stretch=1)

        close = QPushButton("CLOSE")
        close.setFont(theme.header_font(9))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.PAL.text_dim};"
            f" border: none; letter-spacing: 2px; }}"
            f"QPushButton:hover {{ color: {theme.PAL.accent}; }}")
        close.clicked.connect(self.hide)
        lay.addWidget(close)

        self._results_ready.connect(self._populate)
        self._entries: list[dict] = []
        self.hide()

    def open_centered(self, parent_w: int, parent_h: int) -> None:
        w, h = 620, 440
        self.setGeometry((parent_w - w) // 2, (parent_h - h) // 2, w, h)
        self.show()
        self.raise_()
        self.reload()

    def reload(self) -> None:
        """Lazy-loaded: the DB query runs off the UI thread; results land
        back via a Qt signal, never blocking paint/input while scrolling."""
        app = self._app_filter.text().strip() or None
        text = self._text_filter.text().strip() or None
        self._list.clear()
        self._list.addItem("Loading…")

        def _run():
            try:
                rows = MemoryManager.get().get_timeline(app=app, text_contains=text, limit=200)
            except Exception:
                rows = []
            self._results_ready.emit(rows)
        threading.Thread(target=_run, daemon=True, name="timeline-query").start()

    def _populate(self, rows: list[dict]) -> None:
        self._list.clear()
        self._entries = rows
        if not rows:
            self._list.addItem("(no matching activity)")
            return
        import time as _time
        for row in reversed(rows):    # most recent first
            ts = _time.strftime("%H:%M:%S", _time.localtime(row.get("timestamp", 0)))
            app = row.get("app") or "-"
            action = row.get("action_type") or row.get("role", "")
            content = (row.get("content") or "")[:80]
            item = QListWidgetItem(f"{ts}  [{app}]  {action}  {content}")
            item.setData(Qt.ItemDataRole.UserRole, row)
            self._list.addItem(item)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        data = item.data(Qt.ItemDataRole.UserRole)
        if isinstance(data, dict):
            self.entry_selected.emit(data)   # surfaces details only; never executes
