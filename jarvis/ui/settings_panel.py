"""Extracted UI panel implementation; re-exported by jarvis.ui.panels."""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
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

from jarvis.ui.panel_widgets import _TogglePill, _chip

class SettingsPanel(QWidget):
    """Panel Settings (PARITY §7) — UI untuk config.yaml yang sudah jalan.

    Kiri: daftar seksi. Kanan: form field data-driven dari
    jarvis.core.settings_service. Voice read-only (§7.2). Seksi Model
    menautkan ProviderSettingsSheet lama lewat sinyal ``open_providers``.
    """

    open_providers = pyqtSignal()
    _oauth_done = pyqtSignal(bool, str)

    def __init__(self, parent: QWidget | None = None, service=None):
        super().__init__(parent)
        if service is None:
            from jarvis.core import settings_service as service
        self._service = service
        self._sections: list[dict] = []
        self._sec_buttons: dict[str, QPushButton] = {}
        self._selected: str | None = None
        self._editors: dict[str, tuple[str, object]] = {}   # key → (type, widget)

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.base};")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 12)
        root.setSpacing(8)

        title = QLabel("SETTINGS")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;"
                            "letter-spacing: 4px;")
        root.addWidget(title)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, stretch=1)

        nav_host = QWidget()
        self._nav_lay = QVBoxLayout(nav_host)
        self._nav_lay.setContentsMargins(0, 0, 8, 0)
        self._nav_lay.setSpacing(3)
        self._nav_lay.addStretch()
        split.addWidget(nav_host)

        form_host = QWidget()
        self._form_lay = QVBoxLayout(form_host)
        self._form_lay.setContentsMargins(12, 0, 0, 0)
        self._form_lay.setSpacing(6)
        form_scroll = QScrollArea()
        form_scroll.setWidgetResizable(True)
        form_scroll.setFrameShape(QFrame.Shape.NoFrame)
        form_scroll.setStyleSheet("background: transparent;")
        form_scroll.setWidget(form_host)
        split.addWidget(form_scroll)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 3)

        self._status = QLabel("")
        self._status.setFont(theme.mono_font(8))
        self._status.setWordWrap(True)
        self._status.setStyleSheet(f"color: {theme.PAL.text_dim};"
                                   " background: transparent;")
        root.addWidget(self._status)
        self._oauth_done.connect(self._on_oauth_done)

    def refresh(self) -> None:
        try:
            self._sections = self._service.resolve()
        except Exception as e:                               # noqa: BLE001
            _logger.error("settings.load_failed", error=str(e)[:120])
            self._status.setText("Gagal memuat settings — lihat log.")
            return
        while self._nav_lay.count() > 1:
            item = self._nav_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._sec_buttons.clear()
        for sec in self._sections:
            b = QPushButton(sec["title"])
            b.setFont(theme.mono_font(8))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, s=sec["id"]: self._select(s))
            self._sec_buttons[sec["id"]] = b
            self._nav_lay.insertWidget(self._nav_lay.count() - 1, b)
        if self._sections:
            self._select(self._selected
                         if self._selected in self._sec_buttons
                         else self._sections[0]["id"])

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.refresh()

    # ── form ─────────────────────────────────────────────────────────────────

    def _clear_form(self) -> None:
        self._editors.clear()
        while self._form_lay.count():
            item = self._form_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
            elif item.layout() is not None:
                sub = item.layout()
                while sub.count():
                    si = sub.takeAt(0)
                    if si.widget() is not None:
                        si.widget().deleteLater()

    def _select(self, sec_id: str) -> None:
        self._selected = sec_id
        for sid, btn in self._sec_buttons.items():
            active = sid == sec_id
            btn.setChecked(active)
            color = theme.PAL.accent if active else theme.PAL.text_dim
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                f" color: {color}; text-align: left; padding: 4px 8px; }}")
        sec = next((s for s in self._sections if s["id"] == sec_id), None)
        self._clear_form()
        if sec is None:
            return

        hint = QLabel(sec["hint"])
        hint.setFont(theme.mono_font(8))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        self._form_lay.addWidget(hint)

        from PyQt6.QtWidgets import QComboBox
        for f in sec["fields"]:
            row = QHBoxLayout()
            label = QLabel(f["label"])
            label.setFont(theme.mono_font(8))
            label.setFixedWidth(220)
            label.setStyleSheet(f"color: {theme.PAL.text_dim};"
                                " background: transparent;")
            row.addWidget(label)
            ftype = f["type"]
            if ftype == "readonly":
                val = QLabel(str(f["value"]))
                val.setFont(theme.mono_font(9))
                val.setStyleSheet(f"color: {theme.PAL.text};"
                                  " background: transparent;")
                row.addWidget(val, stretch=1)
            elif ftype == "bool":
                pill = _TogglePill(bool(f["value"]))
                self._editors[f["key"]] = (ftype, pill)
                row.addWidget(pill)
                row.addStretch()
            elif ftype == "choice":
                combo = QComboBox()
                combo.setFont(theme.mono_font(9))
                combo.addItems([str(c) for c in f.get("choices", [])])
                combo.setCurrentText(str(f["value"]))
                combo.setStyleSheet(
                    f"QComboBox {{ background: {theme.PAL.panel};"
                    f" color: {theme.PAL.text}; border: none;"
                    f" border-radius: 4px; padding: 5px 8px; }}")
                self._editors[f["key"]] = (ftype, combo)
                row.addWidget(combo, stretch=1)
            else:                                   # text | int | float
                edit = QLineEdit(str(f["value"]))
                edit.setFont(theme.mono_font(9))
                edit.setStyleSheet(
                    f"QLineEdit {{ background: {theme.PAL.panel};"
                    f" color: {theme.PAL.text}; border: 1px solid"
                    f" {theme.PAL.panel}; border-radius: 4px;"
                    f" padding: 5px 8px; }}")
                self._editors[f["key"]] = (ftype, edit)
                row.addWidget(edit, stretch=1)
            self._form_lay.addLayout(row)

        if sec.get("action") == "oauth":
            self._build_oauth_block()
        elif sec.get("action") == "google_oauth":
            self._build_google_oauth_block()

        btn_row = QHBoxLayout()
        if sec.get("action") == "providers":
            prov = QPushButton("Provider API keys …")
            prov.setFont(theme.mono_font(8))
            prov.setCursor(Qt.CursorShape.PointingHandCursor)
            prov.setStyleSheet(
                f"QPushButton {{ background: {theme.PAL.panel};"
                f" color: {theme.PAL.accent}; border: none;"
                f" border-radius: 4px; padding: 6px 14px; }}")
            prov.clicked.connect(self.open_providers.emit)
            btn_row.addWidget(prov)
        btn_row.addStretch()
        if self._editors:
            save = QPushButton("Save changes")
            save.setFont(theme.mono_font(8))
            save.setCursor(Qt.CursorShape.PointingHandCursor)
            save.setStyleSheet(
                f"QPushButton {{ background: {theme.PAL.panel};"
                f" color: {theme.PAL.accent}; border: none;"
                f" border-radius: 4px; padding: 6px 14px; }}"
                f"QPushButton:hover {{ color: {theme.PAL.orb_core}; }}")
            save.clicked.connect(self._save)
            btn_row.addWidget(save)
        self._form_lay.addLayout(btn_row)
        self._form_lay.addStretch()

    # ── Connect Account (§7.3.4-7.3.5) ───────────────────────────────────────

    def _build_oauth_block(self) -> None:
        from jarvis.core import secrets_store
        storage = QLabel(f"Penyimpanan aman: {secrets_store.backend_label()}")
        storage.setFont(theme.mono_font(8))
        storage.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;")
        self._form_lay.addWidget(storage)

        providers = (
            ("openai_oauth", "OpenAI OAuth (ChatGPT/Codex)",
             "Sign in with ChatGPT"),
            ("anthropic_oauth", "Anthropic OAuth (Claude)",
             "Sign in with Claude"),
        )
        for provider, title, sign_label in providers:
            try:
                module = __import__(f"jarvis.integrations.{provider}",
                                    fromlist=[provider])
                oauth_status = getattr(module, "status", lambda: {})()
                is_connected = bool(oauth_status.get("connected",
                                                     module.connected()))
                needs_reauth = bool(oauth_status.get("needs_reauth", False))
            except Exception as e:                           # noqa: BLE001
                _logger.warning("settings.oauth_unavailable",
                                provider=provider, error=str(e)[:100])
                is_connected = False
                needs_reauth = False

            row = QHBoxLayout()
            name = QLabel(title)
            name.setFont(theme.mono_font(9))
            name.setStyleSheet(
                f"color: {theme.PAL.text}; background: transparent;")
            row.addWidget(name)
            badge_text = ("✓ Connected" if is_connected else
                          "Sign in again" if needs_reauth else "Not connected")
            badge = _chip(badge_text, theme.PAL.accent if is_connected
                          else theme.PAL.text_dim)
            row.addWidget(badge)
            row.addStretch()
            button = QPushButton("Disconnect" if is_connected else
                                 "Sign in again" if needs_reauth else sign_label)
            button.setFont(theme.mono_font(8))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                f"QPushButton {{ background: {theme.PAL.panel};"
                f" color: {theme.PAL.accent}; border: none;"
                f" border-radius: 4px; padding: 6px 14px; }}")
            if is_connected:
                button.clicked.connect(
                    lambda _checked=False, p=provider: self._oauth_logout(p))
            else:
                button.clicked.connect(
                    lambda _checked=False, p=provider: self._oauth_signin(p))
            row.addWidget(button)
            self._form_lay.addLayout(row)

    def _oauth_signin(self, provider: str) -> None:
        if provider == "openai_oauth":
            from jarvis.integrations import openai_oauth_service

            def update(state: dict) -> None:
                if state.get("state") == "connected":
                    self._oauth_done.emit(
                        True, "Terhubung — OpenAI OAuth siap dipilih sebagai "
                        "provider berat.")
                elif state.get("state") == "failed":
                    self._oauth_done.emit(False, str(state.get("error") or
                                                      "login gagal"))

            state = openai_oauth_service.start(update)
            if state.get("state") == "callback_pending":
                self._status.setText("Login OpenAI sudah menunggu callback localhost …")
            else:
                self._status.setText(
                    "Membuka browser eksternal — selesaikan sign-in; Jarvis "
                    "menunggu callback localhost …")
            return

        module = __import__(f"jarvis.integrations.{provider}",
                            fromlist=[provider])

        def run():
            try:
                module.start_login()
                self._oauth_done.emit(
                    True, f"Terhubung — {provider} siap dipilih sebagai "
                          "provider berat.")
            except Exception as e:                           # noqa: BLE001
                self._oauth_done.emit(False, str(e)[:200])

        import threading
        threading.Thread(target=run, daemon=True,
                         name=f"oauth-{provider}").start()
        self._status.setText(
            "Membuka browser eksternal — selesaikan sign-in; Jarvis "
            "menunggu callback localhost …")

    def _oauth_logout(self, provider: str) -> None:
        try:
            module = __import__(f"jarvis.integrations.{provider}",
                                fromlist=[provider])
            module.logout()
            self._status.setText("Akun diputus.")
        except Exception as e:                               # noqa: BLE001
            self._status.setText(f"Gagal memutus akun: {str(e)[:120]}")
        self.refresh()

    # ── Google Cloud OAuth (§10) ───────────────────────────────────────────

    def _build_google_oauth_block(self) -> None:
        from jarvis.integrations import google_auth

        status = google_auth.status()
        connected = bool(status["connected"])
        storage = QLabel(f"Penyimpanan aman: {status['backend']}")
        storage.setFont(theme.mono_font(8))
        storage.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;")
        self._form_lay.addWidget(storage)

        scopes = status["scopes"]
        scope_text = (f"Scope diberikan: {len(scopes)}"
                      if scopes else "Scope diberikan: belum ada")
        scope_label = QLabel(scope_text)
        scope_label.setFont(theme.mono_font(8))
        scope_label.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;")
        self._form_lay.addWidget(scope_label)

        self._google_client = QLineEdit()
        self._google_client.setPlaceholderText(
            "OAuth client ID Desktop app (tidak ditampilkan kembali)")
        self._google_secret = QLineEdit()
        self._google_secret.setEchoMode(QLineEdit.EchoMode.Password)
        self._google_secret.setPlaceholderText(
            "OAuth client secret (disimpan terenkripsi)")
        for title, editor in (("Client ID", self._google_client),
                              ("Client secret", self._google_secret)):
            row = QHBoxLayout()
            label = QLabel(title)
            label.setFont(theme.mono_font(8))
            label.setFixedWidth(220)
            label.setStyleSheet(
                f"color: {theme.PAL.text_dim}; background: transparent;")
            editor.setFont(theme.mono_font(9))
            editor.setStyleSheet(
                f"QLineEdit {{ background: {theme.PAL.panel};"
                f" color: {theme.PAL.text}; border: 1px solid"
                f" {theme.PAL.panel}; border-radius: 4px;"
                f" padding: 5px 8px; }}")
            row.addWidget(label)
            row.addWidget(editor, stretch=1)
            self._form_lay.addLayout(row)

        row = QHBoxLayout()
        badge = _chip("✓ Connected" if connected else "Not connected",
                      theme.PAL.accent if connected else theme.PAL.text_dim)
        row.addWidget(badge)
        row.addStretch()
        save_client = QPushButton("Save OAuth client")
        save_client.clicked.connect(self._google_save_client)
        row.addWidget(save_client)
        connect = QPushButton("Disconnect" if connected else "Connect Google")
        if connected:
            connect.clicked.connect(self._google_logout)
        else:
            connect.clicked.connect(self._google_signin)
        row.addWidget(connect)
        for button in (save_client, connect):
            button.setFont(theme.mono_font(8))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(
                f"QPushButton {{ background: {theme.PAL.panel};"
                f" color: {theme.PAL.accent}; border: none;"
                f" border-radius: 4px; padding: 6px 14px; }}")
        self._form_lay.addLayout(row)

    def _google_save_client(self) -> bool:
        from jarvis.integrations import google_auth

        client = self._google_client.text().strip()
        secret = self._google_secret.text().strip()
        if not client or not secret:
            self._status.setText("Client ID dan client secret wajib diisi.")
            return False
        if not google_auth.save_client(client, secret):
            self._status.setText(
                "OAuth client gagal disimpan ke backend terenkripsi.")
            return False
        self._google_client.clear()
        self._google_secret.clear()
        self._status.setText("OAuth client tersimpan terenkripsi.")
        return True

    def _google_save_api_toggles(self) -> bool:
        errors = []
        for key, (ftype, widget) in self._editors.items():
            if not key.startswith("providers.google.apis."):
                continue
            ok, msg = self._service.set_value(
                key, widget.isChecked(), ftype)
            if not ok:
                errors.append(f"{key}: {msg}")
        if errors:
            self._status.setText(" · ".join(errors)[:300])
            return False
        return True

    def _google_signin(self) -> None:
        from jarvis.integrations import google_auth

        if not self._google_save_api_toggles():
            return
        typed_client = bool(self._google_client.text().strip()
                            or self._google_secret.text().strip())
        if typed_client and not self._google_save_client():
            return
        if not google_auth.client_configured():
            self._status.setText(
                "Simpan OAuth client Desktop app sebelum Connect Google.")
            return

        def run():
            try:
                google_auth.start_login()
                self._oauth_done.emit(
                    True, "Google terhubung. Tool aktif sesuai scope; "
                          "sambungkan ulang sesi voice untuk memperbarui "
                          "schema Gemini Live.")
            except Exception as exc:                         # noqa: BLE001
                self._oauth_done.emit(False, str(exc)[:200])

        import threading
        threading.Thread(target=run, daemon=True,
                         name="oauth-google").start()
        self._status.setText(
            "Membuka browser eksternal; Jarvis menunggu callback "
            "http://127.0.0.1 …")

    def _google_logout(self) -> None:
        try:
            from jarvis.integrations import google_auth
            google_auth.logout()
            self._status.setText("Akun Google diputus; tool dinonaktifkan.")
        except Exception as exc:                             # noqa: BLE001
            self._status.setText(f"Gagal memutus Google: {str(exc)[:120]}")
        self.refresh()

    def _on_oauth_done(self, ok: bool, msg: str) -> None:
        color = theme.PAL.text_dim if ok else theme.PAL.alert
        self._status.setStyleSheet(f"color: {color}; background: transparent;")
        self._status.setText(msg)
        self.refresh()

    def _save(self) -> None:
        from PyQt6.QtWidgets import QComboBox
        results = []
        for key, (ftype, widget) in self._editors.items():
            if ftype == "bool":
                value = widget.isChecked()
            elif ftype == "choice":
                value = widget.currentText()
            else:
                value = widget.text()
            ok, msg = self._service.set_value(key, value, ftype)
            if not ok:
                results.append(f"{key}: {msg}")
        if results:
            self._status.setStyleSheet(
                f"color: {theme.PAL.alert}; background: transparent;")
            self._status.setText(" · ".join(results)[:300])
        else:
            self._status.setStyleSheet(
                f"color: {theme.PAL.text_dim}; background: transparent;")
            self._status.setText("Tersimpan. Sebagian nilai berlaku pada "
                                 "run/sesi berikutnya.")
        self.refresh()
