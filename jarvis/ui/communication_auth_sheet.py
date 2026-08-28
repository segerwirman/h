"""Desktop-local authorization sheet for bounded communication overrides."""
from __future__ import annotations

from dataclasses import dataclass

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QLineEdit, QPushButton,
                             QVBoxLayout, QWidget)

from jarvis.ui import theme


@dataclass(frozen=True)
class AuthorizationScope:
    task_id: str
    trace_id: str
    capability_ids: frozenset[str]
    ttl_s: float
    uses: int = 1


class CommunicationAuthorizationSheet(QWidget):
    """Secret-safe local entry surface; emits status and opaque grant ID only."""

    resolved = pyqtSignal(bool, str)

    def __init__(self, parent: QWidget | None = None, *, authorizer=None) -> None:
        super().__init__(parent)
        self._authorizer = authorizer
        self._scope: AuthorizationScope | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 30, 40, 30)
        layout.setSpacing(12)

        title = QLabel("OTORISASI KOMUNIKASI")
        title.setFont(theme.header_font(13))
        title.setStyleSheet(
            f"color: {theme.PAL.accent}; background: transparent; "
            "letter-spacing: 3px;"
        )
        layout.addWidget(title)

        description = QLabel(
            "Masukkan sandi lokal untuk memberi izin eksekusi sementara pada "
            "tugas dan kemampuan yang ditampilkan oleh permintaan aktif."
        )
        description.setFont(theme.mono_font(9))
        description.setWordWrap(True)
        description.setStyleSheet(
            f"color: {theme.PAL.text}; background: transparent;"
        )
        layout.addWidget(description)

        self._entry = QLineEdit()
        self._entry.setEchoMode(QLineEdit.EchoMode.Password)
        self._entry.setPlaceholderText("Sandi lokal")
        self._entry.setFont(theme.mono_font(10))
        self._entry.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.text}; border: none; padding: 10px; }}"
        )
        self._entry.returnPressed.connect(self._submit)
        layout.addWidget(self._entry)

        self._status = QLabel("")
        self._status.setFont(theme.mono_font(8))
        self._status.setWordWrap(True)
        self._status.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;"
        )
        layout.addWidget(self._status)

        row = QHBoxLayout()
        self._authorize_button = self._button("OTORISASI", self._submit)
        self._cancel_button = self._button("BATAL", self._cancel)
        row.addWidget(self._authorize_button)
        row.addWidget(self._cancel_button)
        row.addStretch()
        layout.addLayout(row)
        self.hide()

    def present(self, scope: AuthorizationScope, parent_w: int, parent_h: int) -> bool:
        self._entry.setText("")
        self._status.clear()
        if not self._valid_scope(scope):
            self._scope = None
            return False
        self._scope = scope
        width, height = 540, 260
        self.setGeometry(
            (parent_w - width) // 2,
            (parent_h - height) // 2,
            width,
            height,
        )
        self.show()
        self.raise_()
        self._entry.setFocus()
        return True

    def _submit(self) -> None:
        scope = self._scope
        if scope is None:
            self._entry.setText("")
            return
        value = self._entry.text()
        self._entry.setText("")
        result = self._authorization().authorize(
            value,
            task_id=scope.task_id,
            trace_id=scope.trace_id,
            capability_ids=scope.capability_ids,
            ttl_s=scope.ttl_s,
            uses=scope.uses,
        )
        del value
        if result.ok:
            self._scope = None
            self.hide()
            self.resolved.emit(True, result.grant_id)
            return
        self._status.setText(self._status_text(result.status))
        self.resolved.emit(False, "")

    def _cancel(self) -> None:
        self._entry.setText("")
        self._scope = None
        self.hide()
        self.resolved.emit(False, "")

    def closeEvent(self, event) -> None:
        self._entry.setText("")
        self._scope = None
        super().closeEvent(event)

    def _authorization(self):
        if self._authorizer is not None:
            return self._authorizer
        from jarvis.agent.communication_authorization import AUTHORIZER
        return AUTHORIZER

    @staticmethod
    def _valid_scope(scope: object) -> bool:
        return (
            isinstance(scope, AuthorizationScope)
            and bool(scope.task_id)
            and bool(scope.trace_id)
            and bool(scope.capability_ids)
        )

    @staticmethod
    def _status_text(status: str) -> str:
        return {
            "denied": "Sandi tidak cocok.",
            "locked": "Terlalu banyak percobaan. Tunggu sebelum mencoba lagi.",
            "not_configured": "Sandi komunikasi belum dikonfigurasi.",
            "invalid_scope": "Permintaan otorisasi tidak valid atau sudah selesai.",
            "grant_unavailable": "Izin sementara tidak dapat diterbitkan.",
            "task_unavailable": "Tugas aktif sudah tidak tersedia.",
        }.get(str(status), "Otorisasi gagal.")

    @staticmethod
    def _button(label: str, callback) -> QPushButton:
        button = QPushButton(label)
        button.setFont(theme.header_font(10))
        button.setFixedHeight(34)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.accent}; border: none; letter-spacing: 2px; "
            "padding: 0 22px; }}"
            f"QPushButton:hover {{ color: {theme.PAL.orb_core}; }}"
        )
        button.clicked.connect(callback)
        return button


__all__ = ["AuthorizationScope", "CommunicationAuthorizationSheet"]
