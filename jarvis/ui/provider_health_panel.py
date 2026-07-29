"""Read-only formatter for Provider Health management surface."""
from __future__ import annotations


def provider_rows(snapshot: dict) -> list[str]:
    return [f"{item.get('name', '')} · "
            f"{'configured' if item.get('configured') else 'not configured'} · "
            f"{item.get('model', '')}"
            for item in snapshot.get("providers", [])]


try:
    from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget

    class ProviderHealthPanel(QWidget):
        def __init__(self, snapshot: dict | None = None, parent=None):
            super().__init__(parent)
            layout = QVBoxLayout(self)
            for row in provider_rows(snapshot or {}):
                layout.addWidget(QLabel(row))
except ImportError:
    ProviderHealthPanel = None
