"""Desktop-local approval surface for bounded external proposals."""
from __future__ import annotations

from collections.abc import Callable

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from jarvis.ui import theme

_ACTION_LABELS = {
    "focus_mode_enable": "Aktifkan Focus Mode",
    "focus_mode_disable": "Nonaktifkan Focus Mode",
    "media_play": "Putar media aktif",
    "media_pause": "Jeda media aktif",
    "media_mute": "Bisukan media aktif",
    "media_unmute": "Aktifkan suara media",
    "media_volume_up": "Naikkan volume media",
    "media_volume_down": "Turunkan volume media",
}


class RemoteProposalSheet(QWidget):
    """Shows a safe action label; local controls alone resolve the request."""

    def __init__(self, queue, *, executor: Callable[[str], bool] | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._queue = queue
        self._executor = executor or (lambda _action: False)
        self._request_id = ""
        self._actor_id = ""
        self._session_id = ""
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        layout = QVBoxLayout(self)
        title = QLabel("PERMINTAAN JARAK JAUH — PERSETUJUAN LOKAL")
        title.setFont(theme.header_font(13))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;")
        layout.addWidget(title)
        self._summary = QLabel("")
        self._summary.setFont(theme.mono_font(10))
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        row = QHBoxLayout()
        approve = QPushButton("LANJUT")
        approve.clicked.connect(self._approve)
        cancel = QPushButton("BATAL")
        cancel.clicked.connect(self._cancel)
        for button in (approve, cancel):
            button.setFont(theme.header_font(10))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            row.addWidget(button)
        row.addStretch()
        layout.addLayout(row)
        self.hide()

    def present(self, request_id: str, *, actor_id: str, session_id: str) -> bool:
        request = self._queue.get(request_id, actor_id=actor_id, session_id=session_id)
        if request is None or request.status != "pending_local_approval":
            self._summary.setText("Permintaan tidak tersedia atau kedaluwarsa.")
            return False
        self._request_id, self._actor_id, self._session_id = request.id, str(actor_id), str(session_id)
        self._summary.setText(f"Tindakan diminta:\n{_ACTION_LABELS.get(request.action, 'Tindakan tidak tersedia')}\n\nSetujui hanya jika sesuai permintaan Anda.")
        self.show()
        self.raise_()
        return True

    def summary_text(self) -> str:
        return self._summary.text()

    def _approve(self) -> None:
        if self._request_id:
            self._queue.approve_local(self._request_id, actor_id=self._actor_id,
                                      session_id=self._session_id, executor=self._executor)
        self._clear_hide()

    def _cancel(self) -> None:
        if self._request_id:
            self._queue.cancel_local(self._request_id, actor_id=self._actor_id,
                                     session_id=self._session_id)
        self._clear_hide()

    def _clear_hide(self) -> None:
        self._request_id = self._actor_id = self._session_id = ""
        self.hide()


__all__ = ["RemoteProposalSheet"]
