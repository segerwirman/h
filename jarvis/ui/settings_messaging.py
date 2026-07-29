"""Settings sheet untuk Telegram Control native (MK50 §11.7).

Kontrol disusun seluruhnya dengan Qt layouts dan palet yang sudah ada.  Nilai
secret tidak pernah dibaca kembali ke field; UI hanya menampilkan badge aman.
"""
from __future__ import annotations

import re
import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QCheckBox, QFormLayout, QHBoxLayout, QLabel,
                             QLineEdit, QPushButton, QVBoxLayout, QWidget)

from jarvis.integrations import telegram_control
from jarvis.ui import theme


class MessagingSettingsSheet(QWidget):
    saved = pyqtSignal()
    _test_finished = pyqtSignal(object)
    _runtime_finished = pyqtSignal(bool)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 26, 36, 24)
        root.setSpacing(12)

        title = QLabel("SETTINGS — MESSAGING")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(
            f"color: {theme.PAL.accent}; background: transparent; "
            "letter-spacing: 4px;")
        root.addWidget(title)

        subtitle = QLabel(
            "Telegram Control native • token dan allowlist disimpan terenkripsi")
        subtitle.setFont(theme.mono_font(8))
        subtitle.setStyleSheet(self._dim_css())
        subtitle.setWordWrap(True)
        root.addWidget(subtitle)

        form = QFormLayout()
        form.setHorizontalSpacing(18)
        form.setVerticalSpacing(10)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)

        self._token = self._field(password=True)
        self._token.setPlaceholderText("Masukkan token baru; kosong = pertahankan")
        token_row = QHBoxLayout()
        token_row.addWidget(self._token, stretch=1)
        self._token_badge = QLabel("NOT SAVED")
        self._token_badge.setFont(theme.mono_font(8))
        token_row.addWidget(self._token_badge)
        form.addRow(self._label("Bot token"), token_row)

        self._allowed = self._field()
        self._allowed.setPlaceholderText("123456789, 987654321")
        allowed_row = QHBoxLayout()
        allowed_row.addWidget(self._allowed, stretch=1)
        self._allowed_badge = QLabel("0 SAVED")
        self._allowed_badge.setFont(theme.mono_font(8))
        allowed_row.addWidget(self._allowed_badge)
        form.addRow(self._label("Allowed User IDs"), allowed_row)

        self._master = QCheckBox("Aktifkan Telegram Control")
        self._master.setFont(theme.mono_font(9))
        self._master.setStyleSheet(
            f"color: {theme.PAL.text}; background: transparent;")
        self._master.toggled.connect(self._toggle)
        form.addRow(self._label("Master toggle"), self._master)
        root.addLayout(form)

        state_row = QHBoxLayout()
        self._dot = QLabel("●")
        self._dot.setFont(theme.mono_font(12))
        state_row.addWidget(self._dot)
        self._status = QLabel("")
        self._status.setFont(theme.mono_font(9))
        self._status.setStyleSheet(self._dim_css())
        self._status.setWordWrap(True)
        state_row.addWidget(self._status, stretch=1)
        root.addLayout(state_row)

        self._storage = QLabel("")
        self._storage.setFont(theme.mono_font(8))
        self._storage.setStyleSheet(self._dim_css())
        root.addWidget(self._storage)

        self._light_status = QLabel("")
        self._light_status.setFont(theme.mono_font(8))
        self._light_status.setWordWrap(True)
        root.addWidget(self._light_status)

        buttons = QHBoxLayout()
        self._save_button = self._button("SIMPAN", self._save)
        self._test_button = self._button("TEST CONNECTION", self._test)
        self._restart_button = self._button(
            "RESTART TELEGRAM GATEWAY", self._restart_gateway)
        self._clear_button = self._button("HAPUS KREDENSIAL", self._clear)
        buttons.addWidget(self._save_button)
        buttons.addWidget(self._test_button)
        buttons.addWidget(self._restart_button)
        buttons.addWidget(self._clear_button)
        buttons.addStretch()
        buttons.addWidget(self._button("TUTUP", self.hide))
        root.addLayout(buttons)

        self._test_finished.connect(self._show_test_result)
        self._runtime_finished.connect(self._show_runtime_result)
        self._token.textChanged.connect(self._validate_inputs)
        self._allowed.textChanged.connect(self._validate_inputs)
        self._refresh()
        self.hide()

    @staticmethod
    def _dim_css() -> str:
        return f"color: {theme.PAL.text_dim}; background: transparent;"

    def _label(self, text: str) -> QLabel:
        label = QLabel(text)
        label.setFont(theme.mono_font(8))
        label.setStyleSheet(self._dim_css())
        return label

    def _field(self, password: bool = False) -> QLineEdit:
        field = QLineEdit()
        if password:
            field.setEchoMode(QLineEdit.EchoMode.Password)
        field.setFont(theme.mono_font(9))
        field.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.text}; border: none; padding: 8px; }}")
        return field

    def _button(self, label: str, callback) -> QPushButton:
        button = QPushButton(label)
        button.setFont(theme.header_font(9))
        button.setFixedHeight(32)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.accent}; border: none; letter-spacing: 1px; "
            "padding: 0 12px; }"
            f"QPushButton:disabled {{ color: {theme.PAL.text_dim}; }}")
        button.clicked.connect(callback)
        return button

    def _valid_new_ids(self) -> bool:
        raw = self._allowed.text().strip()
        if not raw:
            return False
        parts = [p for p in re.split(r"[,;\s]+", raw) if p]
        return bool(parts) and all(p.isdecimal() and int(p) > 0 for p in parts)

    def _validate_inputs(self) -> None:
        # Toggle aktif hanya terhadap kredensial yang benar-benar sudah
        # tersimpan; input draft belum boleh mengubah perilaku runtime.
        self._master.setEnabled(telegram_control.credentials_ready())
        self._save_button.setEnabled(bool(
            self._token.text().strip() or self._allowed.text().strip()))

    def _refresh(self, message: str = "") -> None:
        state = telegram_control.status()
        self._token_badge.setText(
            "••••••••  SAVED" if state["token_saved"] else "NOT SAVED")
        self._allowed_badge.setText(f"{state['allowed_count']} SAVED")
        self._master.blockSignals(True)
        self._master.setChecked(bool(state["master_enabled"]))
        self._master.setEnabled(bool(state["configured"]))
        self._master.blockSignals(False)
        dot_color = (theme.PAL.success if state["running"] else
                     theme.PAL.accent_dim if state["configured"] else
                     theme.PAL.alert)
        self._dot.setStyleSheet(
            f"color: {dot_color}; background: transparent;")
        self._status.setText(message or str(state["state"]))
        self._storage.setText(f"Penyimpanan aman: {state['backend']}")
        self._refresh_light_status()
        self._test_button.setEnabled(bool(state["configured"]))
        self._restart_button.setEnabled(bool(state["configured"]))
        self._clear_button.setEnabled(bool(
            state["token_saved"] or state["allowed_count"]))
        self._validate_inputs()

    def _refresh_light_status(self) -> None:
        """Tampilkan readiness jalur T1 tanpa metadata credential."""
        try:
            from jarvis.agent import model_routing
            lane = model_routing.role_statuses().get("light", {})
        except Exception:                                    # noqa: BLE001
            lane = {}
        provider = str(lane.get("provider") or "-")
        model = str(lane.get("model") or "default")
        if lane.get("configured"):
            text = f"LIGHT LANE: {provider} ({model})"
            color = theme.PAL.success
        else:
            reason = str(lane.get("reason") or "belum dikonfigurasi")
            text = (f"LIGHT LANE BELUM SIAP: {provider} — {reason}. "
                    "Buka Settings untuk memilih/melengkapi provider ringan.")
            color = theme.PAL.alert
        self._light_status.setText(text)
        self._light_status.setStyleSheet(
            f"color: {color}; background: transparent;")

    def _save(self) -> None:
        result = telegram_control.save_credentials(
            self._token.text(), self._allowed.text())
        if result.ok:
            self._token.clear()
            self._allowed.clear()
            self.saved.emit()
            if telegram_control.master_enabled():
                self._apply_runtime_async()
        self._refresh(result.message)

    def _toggle(self, checked: bool) -> None:
        result = telegram_control.set_enabled(checked)
        if not result.ok:
            self._refresh(result.message)
            return
        self.saved.emit()
        self._status.setText("Menerapkan perubahan runtime …")
        self._apply_runtime_async()

    def _apply_runtime_async(self) -> None:
        threading.Thread(
            target=lambda: self._runtime_finished.emit(
                telegram_control.apply_runtime()),
            daemon=True, name="telegram-runtime-apply").start()

    def _restart_gateway(self) -> None:
        state = telegram_control.status()
        if not state["configured"]:
            self._refresh("Gateway Telegram belum dikonfigurasi.")
            return
        self._status.setText("Me-restart gateway Telegram …")
        self._apply_runtime_async()

    def _show_runtime_result(self, ok: bool) -> None:
        self._refresh("Perubahan diterapkan." if ok else
                      "Perubahan tersimpan, tetapi service gagal diterapkan.")

    def _test(self) -> None:
        if self._token.text().strip() or self._allowed.text().strip():
            result = telegram_control.save_credentials(
                self._token.text(), self._allowed.text())
            if not result.ok:
                self._refresh(result.message)
                return
            self._token.clear()
            self._allowed.clear()
        self._test_button.setEnabled(False)
        self._status.setText("Menguji Telegram Bot API …")
        threading.Thread(
            target=lambda: self._test_finished.emit(
                telegram_control.test_connection_sync()),
            daemon=True, name="telegram-connection-test").start()

    def _show_test_result(self, result) -> None:
        self._refresh(result.message)

    def _clear(self) -> None:
        result = telegram_control.clear_credentials()
        if result.ok:
            self.saved.emit()
        self._refresh(result.message)

    def open_centered(self, parent_w: int, parent_h: int) -> None:
        width, height = 700, 390
        self._refresh()
        self.setGeometry((parent_w - width) // 2,
                         (parent_h - height) // 2, width, height)
        self.show()
        self.raise_()
