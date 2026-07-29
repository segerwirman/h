"""Local-only Gateway Operations sheet: health, pairs, and approval queue."""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
                             QPushButton, QVBoxLayout, QWidget)

from jarvis.ops.api import OpsAPI
from jarvis.ui import theme


class GatewayOperationsSheet(QWidget):
    """Desktop-local operational view. It never renders secrets or raw actor IDs."""

    _restart_finished = pyqtSignal(bool)
    _continuation_finished = pyqtSignal(object)

    def __init__(self, parent: QWidget, *, ops: OpsAPI | None = None) -> None:
        super().__init__(parent)
        self._ops = ops or OpsAPI()
        self._role = "local-admin"
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 26, 36, 24)
        root.setSpacing(10)

        title = QLabel("GATEWAY OPERATIONS")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(
            f"color: {theme.PAL.accent}; background: transparent; letter-spacing: 4px;")
        root.addWidget(title)

        hint = QLabel(
            "Desktop lokal saja • metadata aman • approval tidak menyimpan payload/tool arguments")
        hint.setFont(theme.mono_font(8))
        hint.setWordWrap(True)
        hint.setStyleSheet(self._dim_css())
        root.addWidget(hint)

        self._health = QLabel("")
        self._health.setFont(theme.mono_font(9))
        self._health.setWordWrap(True)
        self._health.setStyleSheet(self._dim_css())
        root.addWidget(self._section("GATEWAY HEALTH"))
        root.addWidget(self._health)

        root.addWidget(self._section("PENDING APPROVALS"))
        self._approvals = self._list()
        root.addWidget(self._approvals, stretch=1)
        approval_actions = QHBoxLayout()
        approval_actions.addWidget(self._button("APPROVE", lambda: self._resolve_selected(True)))
        approval_actions.addWidget(self._button("DENY", lambda: self._resolve_selected(False)))
        approval_actions.addStretch()
        root.addLayout(approval_actions)

        root.addWidget(self._section("PAIRED REMOTE ACTORS (HASHED)"))
        self._pairs = self._list()
        root.addWidget(self._pairs, stretch=1)
        pair_actions = QHBoxLayout()
        pair_actions.addWidget(self._button("REVOKE SELECTED", self._revoke_selected))
        pair_actions.addStretch()
        root.addLayout(pair_actions)

        self._status = QLabel("")
        self._status.setFont(theme.mono_font(8))
        self._status.setWordWrap(True)
        self._status.setStyleSheet(self._dim_css())
        root.addWidget(self._status)

        bottom = QHBoxLayout()
        bottom.addWidget(self._button("REFRESH", self._refresh))
        bottom.addWidget(self._button("RESTART TELEGRAM GATEWAY", self._restart_telegram))
        bottom.addStretch()
        bottom.addWidget(self._button("TUTUP", self.hide))
        root.addLayout(bottom)

        self._restart_finished.connect(self._show_restart_result)
        self._continuation_finished.connect(self._show_continuation_result)
        self._refresh()
        self.hide()

    @staticmethod
    def _dim_css() -> str:
        return f"color: {theme.PAL.text_dim}; background: transparent;"

    def _section(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(theme.header_font(9))
        label.setStyleSheet(
            f"color: {theme.PAL.accent}; background: transparent; letter-spacing: 2px;")
        return label

    def _list(self) -> QListWidget:
        widget = QListWidget()
        widget.setFont(theme.mono_font(8))
        widget.setFixedHeight(74)
        widget.setStyleSheet(
            f"QListWidget {{ background: {theme.PAL.base}; color: {theme.PAL.text}; "
            "border: none; padding: 4px; }}")
        return widget

    def _button(self, label: str, callback) -> QPushButton:
        button = QPushButton(label)
        button.setFont(theme.header_font(8))
        button.setFixedHeight(30)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.base}; color: {theme.PAL.accent}; "
            "border: none; letter-spacing: 1px; padding: 0 10px; }"
            f"QPushButton:disabled {{ color: {theme.PAL.text_dim}; }}")
        button.clicked.connect(callback)
        return button

    @staticmethod
    def _add_item(widget: QListWidget, text: str, data: dict) -> None:
        item = QListWidgetItem(text)
        item.setData(Qt.ItemDataRole.UserRole, dict(data))
        widget.addItem(item)

    def _refresh(self, message: str = "") -> None:
        overview = self._ops.gateway_overview(self._role) or {}
        health = dict(overview.get("health") or {})
        telegram = dict(overview.get("telegram") or {})
        rows = [f"{name}: {str(state.get('state', 'unknown'))[:32]}"
                for name, state in sorted(health.items())]
        if telegram:
            rows.append("telegram-control: " + str(telegram.get("state", "unknown"))[:32])
        self._health.setText(" • ".join(rows) or "Tidak ada adapter gateway terdaftar.")

        self._approvals.clear()
        for item in self._ops.pending_approvals(self._role) or []:
            self._add_item(self._approvals,
                           f"{item.get('capability', '-')[:48]} • {item.get('reason', '-')[:48]} "
                           f"• {item.get('id', '-')[:16]}", item)
        self._approvals.setEnabled(self._approvals.count() > 0)

        self._pairs.clear()
        for item in self._ops.gateway_pairs(self._role) or []:
            self._add_item(self._pairs,
                           f"{item.get('platform', '-')[:32]} • {item.get('state', '-')[:16]} "
                           f"• {item.get('actor_hash', '-')[:16]}", item)
        self._pairs.setEnabled(self._pairs.count() > 0)
        self._status.setText(message or "Status diperbarui. Semua actor ditampilkan sebagai hash.")

    def _resolve_selected(self, approved: bool) -> None:
        item = self._approvals.currentItem()
        if item is None:
            self._status.setText("Pilih approval request terlebih dahulu.")
            return
        data = dict(item.data(Qt.ItemDataRole.UserRole) or {})
        result = self._ops.resolve_approval(
            self._role, str(data.get("id", "")), approved=approved, actor_id="desktop-ui")
        if result and approved:
            request_id = str(data.get("id", ""))
            self._refresh("Approval disetujui; melanjutkan tool di worker lokal …")
            threading.Thread(
                target=lambda: self._resume_continuation_async(request_id),
                daemon=True, name="approval-continuation",
            ).start()
            return
        self._refresh("Approval ditolak." if result else "Aksi approval ditolak.")

    def _resume_continuation_async(self, request_id: str) -> None:
        from jarvis.agent import approval_continuations
        result = approval_continuations.resume_sync(request_id)
        try:
            self._continuation_finished.emit(result)
        except (AttributeError, RuntimeError):
            # Sheet may have been closed/destroyed while the worker was running.
            return

    def _show_continuation_result(self, result) -> None:
        self._refresh("Tool yang disetujui selesai dijalankan." if getattr(result, "ok", False)
                      else "Tool yang disetujui tidak dapat dilanjutkan.")

    def _revoke_selected(self) -> None:
        item = self._pairs.currentItem()
        if item is None:
            self._status.setText("Pilih paired actor terlebih dahulu.")
            return
        data = dict(item.data(Qt.ItemDataRole.UserRole) or {})
        ok = self._ops.revoke_gateway_pair(
            self._role, str(data.get("platform", "")), str(data.get("actor_hash", "")),
            actor_id="desktop-ui")
        self._refresh("Pair remote dicabut." if ok else "Pair tidak dapat dicabut.")

    def _restart_telegram(self) -> None:
        self._status.setText("Me-restart gateway Telegram …")
        threading.Thread(
            target=lambda: self._restart_finished.emit(
                self._ops.restart_gateway(
                    self._role, "telegram", actor_id="desktop-ui")),
            daemon=True, name="gateway-operations-restart",
        ).start()

    def _show_restart_result(self, ok: bool) -> None:
        self._refresh("Gateway Telegram diterapkan ulang." if ok else
                      "Restart Telegram gagal; lihat Messaging Settings.")

    def open_centered(self, parent_w: int, parent_h: int) -> None:
        width, height = 900, min(660, max(560, parent_h - 48))
        self._refresh()
        self.setGeometry((parent_w - width) // 2, (parent_h - height) // 2, width, height)
        self.show()
        self.raise_()
