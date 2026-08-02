"""RemoteSetupSheet (Fase 15S) — approval lokal untuk secure remote setup.

Menampilkan hanya metadata setup (provider, requester, hash suffix). Secret
mentah tidak pernah ditampilkan atau dimuat ke widget. Approval memicu import
ke secret store di worker thread (UI tidak freeze); batal/timeout menghapus
staging.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)

from jarvis.core import log
from jarvis.ui import theme

_logger = log.get("ui.remote_setup_sheet")

_PROVIDER_LABELS = {
    "google_oauth_client": "Google OAuth Desktop Client (Gmail + Calendar)",
}


class RemoteSetupSheet(QWidget):
    """Desktop-local approval surface. Remote never approves; this widget does."""

    resolved = pyqtSignal(str, str)  # request_id, fixed status enum

    def __init__(self, queue, parent: QWidget | None = None):
        super().__init__(parent)
        self._queue = queue
        self._request_id: str = ""
        self._import_done = threading.Event()
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 30, 40, 30)
        lay.setSpacing(12)

        title = QLabel("SETUP JARAK JAUH — PERSETUJUAN LOKAL")
        title.setFont(theme.header_font(13))
        title.setStyleSheet(
            f"color: {theme.PAL.accent}; background: transparent; letter-spacing: 3px;")
        lay.addWidget(title)

        self._summary = QLabel("")
        self._summary.setFont(theme.mono_font(10))
        self._summary.setWordWrap(True)
        self._summary.setStyleSheet(
            f"color: {theme.PAL.text}; background: transparent;")
        lay.addWidget(self._summary)

        row = QHBoxLayout()
        approve = QPushButton("LANJUT")
        approve.clicked.connect(self._approve)
        cancel = QPushButton("BATAL")
        cancel.clicked.connect(self._cancel)
        for b in (approve, cancel):
            b.setFont(theme.header_font(10))
            b.setFixedHeight(34)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: {theme.PAL.base};"
                f" color: {theme.PAL.accent}; border: none; letter-spacing: 2px;"
                f" padding: 0 22px; }}"
                f"QPushButton:hover {{ color: {theme.PAL.orb_core}; }}")
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.hide()

    def present(self, request_id: str) -> bool:
        request = self._queue.get(str(request_id))
        if request is None:
            self._request_id = ""
            self._summary.setText("Permintaan setup tidak tersedia atau kedaluwarsa.")
            return False
        self._request_id = request.id
        self._summary.setText(self._compose_summary(request))
        self.show()
        self.raise_()
        return True

    def summary_text(self) -> str:
        return self._summary.text()

    @staticmethod
    def _compose_summary(request) -> str:
        label = _PROVIDER_LABELS.get(request.provider, request.provider)
        return (
            f"Provider: {request.provider}\n"
            f"Layanan: {label}\n"
            "Pemohon remote terverifikasi\n"
            f"Sidik berkas: …{request.hash_suffix}\n\n"
            "Kredensial akan diimpor ke penyimpanan terenkripsi lokal. "
            "Isi rahasia tidak ditampilkan dan tidak dikirim kembali ke remote."
        )

    def _approve(self) -> None:
        if not self._request_id:
            return
        rid = self._request_id
        self._request_id = ""
        # hide immediately; the import itself runs off the UI thread so a slow
        # secret backend never freezes the window.
        self.hide()
        self._import_done.clear()

        def _worker() -> None:
            try:
                status = str(self._queue.approve_local(rid))
            finally:
                self._import_done.set()
            # pyqtSignal emit from a worker is queued back to the UI thread
            self.resolved.emit(rid, status)

        threading.Thread(target=_worker, daemon=True,
                         name="remote-setup-import").start()

    def _cancel(self) -> None:
        if not self._request_id:
            self.hide()
            return
        rid = self._request_id
        self._queue.cancel(rid)
        self._request_id = ""
        self.resolved.emit(rid, "cancelled")
        self.hide()


__all__ = ["RemoteSetupSheet"]
