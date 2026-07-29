"""Read-only formatter for the Sessions management surface."""
from __future__ import annotations


def session_rows(snapshot: dict) -> list[str]:
    return [f"{item.get('id', '')} · {item.get('source', '')} · "
            f"{item.get('status', '')} · {item.get('turn_count', 0)} turns"
            for item in snapshot.get("sessions", [])]


try:
    from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

    class SessionsPanel(QWidget):
        def __init__(self, snapshot: dict | None = None, parent=None):
            super().__init__(parent)
            layout = QVBoxLayout(self)
            for row in session_rows(snapshot or {}):
                layout.addWidget(QLabel(row))
except ImportError:
    SessionsPanel = None
