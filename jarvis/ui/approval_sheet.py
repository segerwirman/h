"""WA2-lanjutan — approval sheet UI (lokal).

Sheet persetujuan lokal: menampilkan METADATA proposal (proposal_id,
facade_name, status) + tombol Approve/Reject → signal dengan proposal_id.
TIDAK pernah menerima/menyimpan args/secret — murni metadata. Offscreen
testable; tanpa network/authority baru.
"""
from __future__ import annotations

from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QPushButton, QVBoxLayout,
                             QWidget)


class ApprovalSheet(QWidget):
    """Metadata-only approval sheet; signal approved/rejected(proposal_id)."""

    approved = pyqtSignal(int)
    rejected = pyqtSignal(int)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._proposal_id: int | None = None
        self._facade_name: str | None = None
        self._status: str | None = None

        self._title_label = QLabel("Belum ada proposal", self)
        self._detail_label = QLabel("", self)
        self._approve_button = QPushButton("Approve (lokal)", self)
        self._reject_button = QPushButton("Reject", self)

        layout = QVBoxLayout(self)
        layout.addWidget(self._title_label)
        layout.addWidget(self._detail_label)
        buttons = QHBoxLayout()
        buttons.addWidget(self._approve_button)
        buttons.addWidget(self._reject_button)
        layout.addLayout(buttons)

        self._approve_button.clicked.connect(self._on_approve)
        self._reject_button.clicked.connect(self._on_reject)

    # ── konten (metadata only) ───────────────────────────────────────────────
    def set_proposal(self, metadata: dict) -> None:
        """Isi sheet dari metadata proposal — args/secret TIDAK diterima."""
        self._proposal_id = int(metadata["proposal_id"])
        self._facade_name = str(metadata["facade_name"])
        self._status = str(metadata["status"])
        self._title_label.setText(f"Proposal #{self._proposal_id} — "
                                  f"{self._facade_name}")
        self._detail_label.setText(f"Status: {self._status}")

    def clear(self) -> None:
        self._proposal_id = None
        self._facade_name = None
        self._status = None
        self._title_label.setText("Belum ada proposal")
        self._detail_label.setText("")

    def is_empty(self) -> bool:
        return self._proposal_id is None

    def proposal_id(self) -> int | None:
        return self._proposal_id

    def facade_name(self) -> str | None:
        return self._facade_name

    def raw_payload(self) -> object | None:
        """Selalu None — sheet tidak pernah menyimpan payload/args."""
        return None

    # ── aksi ─────────────────────────────────────────────────────────────────
    def _on_approve(self) -> None:
        if self._proposal_id is not None:
            self.approved.emit(self._proposal_id)

    def _on_reject(self) -> None:
        if self._proposal_id is not None:
            self.rejected.emit(self._proposal_id)


__all__ = ["ApprovalSheet"]
