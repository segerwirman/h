"""Extracted UI panel implementation; re-exported by jarvis.ui.panels."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from jarvis.core import log
from jarvis.ui import theme

_logger = log.get("ui.panels")

from jarvis.ui.panel_widgets import _PlatformRow, _TogglePill, _chip

class MessagingPanel(QWidget):
    """Panel Messaging (PARITY §6) — editor config Hermes via bridge.

    Kiri: platform + status dot. Kanan: field REQUIRED, ADVANCED (N)
    collapsible, allowlist enforcement, master toggle + Save + Restart.
    Operasi tulis via worker thread (subprocess bridge bisa detik-an).
    """

    _op_done = pyqtSignal(bool, str)

    def __init__(self, parent: QWidget | None = None, service=None):
        super().__init__(parent)
        if service is None:
            from jarvis.integrations.hermes import messaging_service as service
        self._service = service
        self._platforms: dict[str, dict] = {}
        self._rows: dict[str, _PlatformRow] = {}
        self._selected: str | None = None
        self._edits: dict[str, QLineEdit] = {}
        self._advanced_open = False
        self._enable_confirm_pending = False

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.base};")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 12)
        root.setSpacing(8)

        title = QLabel("MESSAGING")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;"
                            "letter-spacing: 4px;")
        root.addWidget(title)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, stretch=1)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.setSpacing(4)
        self._list_host = QWidget()
        self._list_lay = QVBoxLayout(self._list_host)
        self._list_lay.setContentsMargins(0, 0, 0, 0)
        self._list_lay.setSpacing(4)
        self._list_lay.addStretch()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setStyleSheet("background: transparent;")
        scroll.setWidget(self._list_host)
        ll.addWidget(scroll, stretch=1)
        split.addWidget(left)

        right = QWidget()
        self._detail_lay = QVBoxLayout(right)
        self._detail_lay.setContentsMargins(12, 0, 0, 0)
        self._detail_lay.setSpacing(6)
        detail_scroll = QScrollArea()
        detail_scroll.setWidgetResizable(True)
        detail_scroll.setFrameShape(QFrame.Shape.NoFrame)
        detail_scroll.setStyleSheet("background: transparent;")
        detail_scroll.setWidget(right)
        split.addWidget(detail_scroll)
        split.setStretchFactor(0, 2)
        split.setStretchFactor(1, 3)

        self._status = QLabel("")
        self._status.setFont(theme.mono_font(8))
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {theme.PAL.text_dim};"
                                   " background: transparent;")
        root.addWidget(self._status)

        self._op_done.connect(self._on_op_done)

    # ── data ─────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        try:
            platforms = self._service.list_platforms()
        except Exception as e:                               # noqa: BLE001
            _logger.error("messaging.load_failed", error=str(e)[:120])
            self._status.setText("Gagal membaca instalasi Hermes — lihat log.")
            return
        self._platforms = {p["id"]: p for p in platforms}
        self._rows.clear()
        while self._list_lay.count() > 1:
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        for plat in platforms:
            row = _PlatformRow(plat)
            row.selected.connect(self._select)
            self._rows[plat["id"]] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        if platforms:
            self._select(self._selected if self._selected in self._platforms
                         else platforms[0]["id"])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    # ── detail ───────────────────────────────────────────────────────────────

    def _clear_detail(self) -> None:
        self._edits.clear()
        while self._detail_lay.count():
            item = self._detail_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _field_row(self, field: dict) -> QWidget:
        host = QWidget()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        label = QLabel(field["key"] + (" *" if field["required"] else ""))
        label.setFont(theme.mono_font(8))
        label.setFixedWidth(210)
        label.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        lay.addWidget(label)

        edit = QLineEdit()
        edit.setFont(theme.mono_font(9))
        if field["secret"]:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.setPlaceholderText(field["redacted"] if field["is_set"]
                                else "belum diisi")
        edit.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.panel}; color: {theme.PAL.text};"
            f" border: 1px solid {theme.PAL.panel}; border-radius: 4px;"
            f" padding: 5px 8px; }}")
        self._edits[field["key"]] = edit
        lay.addWidget(edit, stretch=1)

        if field["is_set"]:
            saved = _chip("Saved", theme.PAL.accent)
            lay.addWidget(saved)
            trash = QPushButton("🗑")
            trash.setFixedSize(24, 24)
            trash.setCursor(Qt.CursorShape.PointingHandCursor)
            trash.setToolTip(f"Hapus {field['key']} dari .env Hermes")
            trash.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                f" color: {theme.PAL.text_dim}; }}"
                f"QPushButton:hover {{ color: {theme.PAL.alert}; }}")
            trash.clicked.connect(
                lambda _, k=field["key"]: self._submit(
                    lambda: self._service.clear_env(k)))
            lay.addWidget(trash)
        return host

    def _select(self, pid: str) -> None:
        self._selected = pid
        self._enable_confirm_pending = False
        for row_id, row in self._rows.items():
            row.set_highlight(row_id == pid)
        plat = self._platforms.get(pid)
        self._clear_detail()
        if plat is None:
            return

        name = QLabel(plat["name"])
        name.setFont(theme.header_font(12))
        name.setStyleSheet(f"color: {theme.PAL.text}; background: transparent;"
                           "letter-spacing: 2px;")
        self._detail_lay.addWidget(name)

        desc = QLabel(plat["description"])
        desc.setFont(theme.mono_font(8))
        desc.setWordWrap(True)
        desc.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        self._detail_lay.addWidget(desc)

        if plat["allow_all"]:
            warn = QLabel("⚠ GATEWAY_ALLOW_ALL_USERS aktif (dev only) — "
                          "SEMUA orang bisa memerintah Jarvis lewat platform "
                          "ini. Matikan kecuali benar-benar sengaja.")
            warn.setFont(theme.mono_font(8))
            warn.setWordWrap(True)
            warn.setStyleSheet(f"color: {theme.PAL.alert}; background: transparent;")
            self._detail_lay.addWidget(warn)

        required = [f for f in plat["fields"] if f["required"]]
        advanced = [f for f in plat["fields"] if not f["required"]]
        if required:
            sec = QLabel("REQUIRED")
            sec.setFont(theme.mono_font(7))
            sec.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
            self._detail_lay.addWidget(sec)
            for f in required:
                self._detail_lay.addWidget(self._field_row(f))

        if advanced:
            adv_btn = QPushButton(
                ("▾ " if self._advanced_open else "▸ ")
                + f"ADVANCED ({len(advanced)})")
            adv_btn.setFont(theme.mono_font(7))
            adv_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            adv_btn.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                f" color: {theme.PAL.text_dim}; text-align: left; }}"
                f"QPushButton:hover {{ color: {theme.PAL.accent}; }}")
            adv_btn.clicked.connect(self._toggle_advanced)
            self._detail_lay.addWidget(adv_btn)
            self._adv_host = QWidget()
            adv_lay = QVBoxLayout(self._adv_host)
            adv_lay.setContentsMargins(0, 0, 0, 0)
            adv_lay.setSpacing(6)
            for f in advanced:
                adv_lay.addWidget(self._field_row(f))
            self._adv_host.setVisible(self._advanced_open)
            self._detail_lay.addWidget(self._adv_host)

        if not plat["allowlist_ok"]:
            guard = QLabel("Master toggle terkunci: isi field allowlist "
                           "(…_ALLOWED_USERS) dulu. Bot tanpa allowlist = "
                           "komputer terbuka ke internet.")
            guard.setFont(theme.mono_font(8))
            guard.setWordWrap(True)
            guard.setStyleSheet(f"color: {theme.PAL.alert}; background: transparent;")
            self._detail_lay.addWidget(guard)

        row = QHBoxLayout()
        self._enable_pill = _TogglePill(plat["enabled"])
        # §6.4 — terkunci selama allowlist kosong, KECUALI allow_all
        # (itu pun butuh konfirmasi kedua di _on_enable_toggle)
        can_toggle = plat["allowlist_ok"] or plat["allow_all"] \
            or plat["enabled"]                    # disable selalu boleh
        self._enable_pill.setEnabled(can_toggle)
        self._enable_pill.clicked.connect(self._on_enable_toggle)
        row.addWidget(self._enable_pill)
        lbl = QLabel("Enabled")
        lbl.setFont(theme.mono_font(8))
        lbl.setStyleSheet(f"color: {theme.PAL.text}; background: transparent;")
        row.addWidget(lbl)
        row.addStretch()

        save = QPushButton("Save changes")
        restart = QPushButton("Restart gateway")
        for b in (save, restart):
            b.setFont(theme.mono_font(8))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.setStyleSheet(
                f"QPushButton {{ background: {theme.PAL.panel};"
                f" color: {theme.PAL.accent}; border: none; border-radius: 4px;"
                f" padding: 6px 14px; }}"
                f"QPushButton:hover {{ color: {theme.PAL.orb_core}; }}")
        save.clicked.connect(self._save_changes)
        restart.clicked.connect(
            lambda: self._submit(self._service.restart_gateway))
        row.addWidget(save)
        row.addWidget(restart)
        self._detail_lay.addLayout(row)
        self._detail_lay.addStretch()

    def _toggle_advanced(self) -> None:
        self._advanced_open = not self._advanced_open
        if self._selected:
            self._select(self._selected)

    # ── operasi tulis (worker thread) ────────────────────────────────────────

    def _submit(self, fn) -> None:
        self._status.setText("Menjalankan …")

        def run():
            try:
                ok, msg = fn()
            except Exception as e:                           # noqa: BLE001
                ok, msg = False, str(e)[:160]
            self._op_done.emit(ok, msg)

        import threading
        threading.Thread(target=run, daemon=True,
                         name="messaging-op").start()

    def _on_op_done(self, ok: bool, msg: str) -> None:
        color = theme.PAL.text_dim if ok else theme.PAL.alert
        self._status.setStyleSheet(f"color: {color}; background: transparent;")
        self._status.setText(msg)
        self.refresh()

    def _save_changes(self) -> None:
        pid = self._selected  # noqa: F841 — parity source retains legacy seam
        changes = [(k, e.text().strip())
                   for k, e in self._edits.items() if e.text().strip()]
        if not changes:
            self._status.setText("Tidak ada perubahan.")
            return

        def do():
            for key, value in changes:
                ok, msg = self._service.set_env(key, value)
                if not ok:
                    return False, f"{key}: {msg}"
            return True, (f"{len(changes)} field tersimpan — restart "
                          "gateway untuk menerapkan")

        self._submit(do)

    def _on_enable_toggle(self, checked: bool) -> None:
        pid = self._selected
        plat = self._platforms.get(pid) or {}
        if checked and plat.get("allow_all") and not plat.get("allowlist_ok"):
            # konfirmasi kedua eksplisit (§6.4) — klik pertama memperingatkan
            if not self._enable_confirm_pending:
                self._enable_confirm_pending = True
                self._enable_pill.setChecked(False)
                self._status.setStyleSheet(
                    f"color: {theme.PAL.alert}; background: transparent;")
                self._status.setText(
                    "⚠ Allow-all TANPA allowlist (dev only). Klik toggle "
                    "sekali lagi untuk konfirmasi.")
                return
        confirmed = self._enable_confirm_pending
        self._enable_confirm_pending = False
        self._submit(lambda: self._service.set_enabled(
            pid, checked, allow_all_confirmed=confirmed))
