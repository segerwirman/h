"""ProviderSettingsSheet — metadata provider + secret terenkripsi.

Permintaan user MK50: menu provider API key — Gemini, OpenAI, Anthropic,
Local (OpenAI-compatible: LM Studio/Ollama/llama.cpp/vLLM), Custom — yang
menopang agent native. Bahasa visual identik dengan SettingsSheet lama
(palet + font dari jarvis.ui.theme); file lama TIDAK diubah.

Kunci disimpan hanya via ``jarvis.core.secrets_store``; providers.json tidak
pernah menerima nilai credential.
"""
from __future__ import annotations

import threading

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QVBoxLayout, QWidget)

from jarvis.core import llm, log, secrets_store, settings_service
from jarvis.ui import theme

_logger = log.get("ui.settings_providers")

_ORDER = ["gemini", "openai", "openai_oauth", "anthropic",
          "anthropic_oauth", "openrouter", "local", "custom"]


class ProviderSettingsSheet(QWidget):
    """Sheet modal terpusat: pilih provider → isi kredensial → SIMPAN/TEST."""

    saved = pyqtSignal()
    _oauth_updated = pyqtSignal(object)
    _model_catalog_updated = pyqtSignal(object)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        self._test_sig_bound = False

        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 26, 40, 24)
        lay.setSpacing(10)

        title = QLabel("SETTINGS — LLM PROVIDER")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(f"color: {theme.PAL.accent}; "
                            "background: transparent; letter-spacing: 4px;")
        lay.addWidget(title)

        # Ringkasan stack aktif sekali-lihat: provider mana dipakai untuk
        # Voice / LLM / Image + aturan auto-switch OpenAI(Codex auth) ↔ Gemini.
        self._stack_lbl = QLabel("")
        self._stack_lbl.setFont(theme.mono_font(9))
        self._stack_lbl.setWordWrap(True)
        self._stack_lbl.setStyleSheet(
            f"color: {theme.PAL.accent}; background: {theme.PAL.base};"
            " padding: 8px 10px; border: none;")
        lay.addWidget(self._stack_lbl)

        row = QHBoxLayout()
        lbl = QLabel("Provider")
        lbl.setFont(theme.mono_font(9))
        lbl.setStyleSheet(self._dim_css())
        row.addWidget(lbl)
        self._combo = QComboBox()
        self._combo.setFont(theme.mono_font(10))
        self._combo.setStyleSheet(
            f"QComboBox {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.text}; border: none; padding: 8px; }}"
            f"QComboBox QAbstractItemView {{ background: {theme.PAL.base};"
            f" color: {theme.PAL.text}; selection-background-color: "
            f"{theme.PAL.panel}; }}")
        row.addWidget(self._combo, stretch=1)

        self._active_btn = QPushButton("JADIKAN AKTIF")
        self._style_button(self._active_btn)
        self._active_btn.clicked.connect(self._set_active)
        row.addWidget(self._active_btn)
        self._delete_btn = QPushButton("HAPUS")
        self._style_button(self._delete_btn)
        self._delete_btn.clicked.connect(self._delete_provider)
        row.addWidget(self._delete_btn)
        lay.addLayout(row)

        self._active_lbl = QLabel("")
        self._active_lbl.setFont(theme.mono_font(8))
        self._active_lbl.setStyleSheet(self._dim_css())
        lay.addWidget(self._active_lbl)

        self._roles_lbl = QLabel("")
        self._roles_lbl.setFont(theme.mono_font(8))
        self._roles_lbl.setStyleSheet(self._dim_css())
        self._roles_lbl.setWordWrap(True)
        lay.addWidget(self._roles_lbl)

        self._advanced_toggle = QPushButton("TAMPILKAN ROUTING LANJUTAN")
        self._style_button(self._advanced_toggle)
        self._advanced_toggle.clicked.connect(self._toggle_advanced_routing)
        lay.addWidget(self._advanced_toggle)
        self._advanced_visible = False

        lane_title = QLabel("ROUTING — JALUR RINGAN (TELEGRAM T1)")
        lane_title.setFont(theme.mono_font(8))
        lane_title.setStyleSheet(self._dim_css())
        lay.addWidget(lane_title)
        lane_row = QHBoxLayout()
        self._light_provider = QComboBox()
        self._light_provider.setFont(theme.mono_font(9))
        self._light_provider.setStyleSheet(
            f"QComboBox {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.text}; border: none; padding: 6px; }}")
        lane_row.addWidget(self._light_provider, stretch=1)
        self._save_lane = QPushButton("SIMPAN JALUR")
        self._style_button(self._save_lane)
        self._save_lane.clicked.connect(self._save_light_lane)
        lane_row.addWidget(self._save_lane)
        lay.addLayout(lane_row)
        self._light_model = self._field(
            lay, "Model ringan (kosong = model default provider)")
        self._lane_status = QLabel("")
        self._lane_status.setFont(theme.mono_font(8))
        self._lane_status.setWordWrap(True)
        self._lane_status.setStyleSheet(self._dim_css())
        lay.addWidget(self._lane_status)

        heavy_title = QLabel("ROUTING — NATIVE AGENT (TUGAS T2/T3)")
        heavy_title.setFont(theme.mono_font(8))
        heavy_title.setStyleSheet(self._dim_css())
        lay.addWidget(heavy_title)
        heavy_row = QHBoxLayout()
        self._heavy_provider = QComboBox()
        self._heavy_provider.setFont(theme.mono_font(9))
        self._heavy_provider.setStyleSheet(
            f"QComboBox {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.text}; border: none; padding: 6px; }}")
        heavy_row.addWidget(self._heavy_provider, stretch=1)
        self._save_heavy = QPushButton("SIMPAN JALUR AGENT")
        self._style_button(self._save_heavy)
        self._save_heavy.clicked.connect(self._save_heavy_lane)
        heavy_row.addWidget(self._save_heavy)
        lay.addLayout(heavy_row)
        self._heavy_model = self._field(
            lay, "Model agent (kosong = model provider yang dipilih)")
        self._heavy_status = QLabel("")
        self._heavy_status.setFont(theme.mono_font(8))
        self._heavy_status.setWordWrap(True)
        self._heavy_status.setStyleSheet(self._dim_css())
        lay.addWidget(self._heavy_status)

        # Settings S1 keeps daily setup focused. Expert routing controls remain
        # constructed for compatibility but are hidden until S2 disclosure.
        self._advanced_widgets = (
            lane_title, self._light_provider, self._save_lane, self._light_model,
            self._lane_status, heavy_title, self._heavy_provider, self._save_heavy,
            self._heavy_model, self._heavy_status, self._roles_lbl,
        )
        for widget in self._advanced_widgets:
            widget.hide()

        self._storage_lbl = QLabel("")
        self._storage_lbl.setFont(theme.mono_font(8))
        self._storage_lbl.setStyleSheet(self._dim_css())
        lay.addWidget(self._storage_lbl)

        self._base_url = self._field(lay, "Base URL (otomatis per provider; bisa diubah untuk lokal)")
        self._api_key = self._field(lay, "API Key (disimpan hanya di keyring/secret store)", password=True)
        # Tetap sebagai backing state kompatibel; input manual hanya muncul
        # jika endpoint mengirim format katalog yang tidak dikenali.
        self._model = self._field(lay, "Model manual (fallback endpoint tidak standar)")
        self._model.hide()
        self._model_label = lay.itemAt(lay.count() - 2).widget()
        self._model_label.hide()
        detected_label = QLabel("Model")
        detected_label.setFont(theme.mono_font(8))
        detected_label.setStyleSheet(self._dim_css())
        lay.addWidget(detected_label)
        self._detected_models = QComboBox()
        self._detected_models.setFont(theme.mono_font(9))
        self._detected_models.setStyleSheet(
            f"QComboBox {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.text}; border: none; padding: 6px; }}")
        self._detected_models.setEnabled(False)
        self._detected_models.addItem("Pilih model setelah Tes Koneksi")
        self._detected_models.currentTextChanged.connect(self._choose_detected_model)
        lay.addWidget(self._detected_models)
        self._vision_model = self._field(
            lay, "Vision model (kosong = sama dengan model)")
        self._vision_hint = QLabel("")
        self._vision_hint.setFont(theme.mono_font(8))
        self._vision_hint.setStyleSheet(self._dim_css())
        self._vision_hint.setWordWrap(True)
        lay.addWidget(self._vision_hint)

        self._oauth_button = QPushButton("HUBUNGKAN OAUTH")
        self._style_button(self._oauth_button)
        self._oauth_button.clicked.connect(self._oauth_action)
        lay.addWidget(self._oauth_button)
        self._oauth_button.hide()
        self._detect_models_button = QPushButton("TES KONEKSI")
        self._style_button(self._detect_models_button)
        self._detect_models_button.clicked.connect(self._detect_models)
        lay.addWidget(self._detect_models_button)
        self._detect_models_button.hide()
        self._probe_model_button = QPushButton("TEST NATIVE AGENT MODEL")
        self._style_button(self._probe_model_button)
        self._probe_model_button.clicked.connect(
            self._probe_selected_agent_model)
        lay.addWidget(self._probe_model_button)
        self._probe_model_button.hide()
        self._oauth_provider = ""

        self._status = QLabel("")
        self._status.setFont(theme.mono_font(9))
        self._status.setStyleSheet(self._dim_css())
        self._status.setWordWrap(True)
        lay.addWidget(self._status)

        btn_row = QHBoxLayout()
        for label, fn in (("SIMPAN", self._save), ("TEST", self._test),
                          ("TUTUP", self.hide)):
            b = QPushButton(label)
            self._style_button(b)
            b.clicked.connect(fn)
            btn_row.addWidget(b)
        btn_row.addStretch()
        lay.addLayout(btn_row)

        self._combo.currentTextChanged.connect(self._load_fields)
        self._oauth_updated.connect(self._apply_oauth_update)
        self._model_catalog_updated.connect(self._apply_model_catalog)
        self._reload_light_lane()
        self._reload_heavy_lane()
        self._reload_names()
        self.hide()

    # ── helpers UI ────────────────────────────────────────────────────────

    @staticmethod
    def _dim_css() -> str:
        return (f"color: {theme.PAL.text_dim}; background: transparent;")

    def _set_connection_status(self, text: str, state: str = "idle") -> None:
        """Status discovery selalu terlihat, memakai token tema aktif."""
        color = {"testing": theme.PAL.accent_dim, "ok": theme.PAL.success,
                 "error": theme.PAL.alert}.get(state, theme.PAL.text_dim)
        self._status.setStyleSheet(f"color: {color}; background: transparent;")
        self._status.setText(text)

    def _toggle_advanced_routing(self) -> None:
        """Reveal existing local routing controls only after explicit local interaction."""
        self._advanced_visible = not self._advanced_visible
        for widget in self._advanced_widgets:
            widget.setVisible(self._advanced_visible)
        self._advanced_toggle.setText(
            "SEMBUNYIKAN ROUTING LANJUTAN" if self._advanced_visible
            else "TAMPILKAN ROUTING LANJUTAN")

    def _style_button(self, b: QPushButton) -> None:
        b.setFont(theme.header_font(10))
        b.setFixedHeight(32)
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.accent}; border: none; letter-spacing: 2px;"
            f" padding: 0 18px; }}"
            f"QPushButton:hover {{ color: {theme.PAL.orb_core}; }}")

    def _field(self, lay: QVBoxLayout, hint: str,
               password: bool = False) -> QLineEdit:
        lbl = QLabel(hint)
        lbl.setFont(theme.mono_font(8))
        lbl.setStyleSheet(self._dim_css())
        lay.addWidget(lbl)
        edit = QLineEdit()
        if password:
            edit.setEchoMode(QLineEdit.EchoMode.Password)
        edit.setFont(theme.mono_font(10))
        edit.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.base}; color: "
            f"{theme.PAL.text}; border: none; padding: 8px; }}")
        lay.addWidget(edit)
        return edit

    # ── data ──────────────────────────────────────────────────────────────

    def _reload_names(self) -> None:
        from jarvis.agent import providers
        current = self._combo.currentText()
        self._combo.blockSignals(True)
        self._combo.clear()
        names = [n for n in _ORDER if n in providers.list_names()]
        names += [n for n in providers.list_names() if n not in names]
        self._combo.addItems(names)
        if current in names:
            self._combo.setCurrentText(current)
        else:
            self._combo.setCurrentText(providers.active_name())
        self._combo.blockSignals(False)
        self._load_fields(self._combo.currentText())

    def _reload_light_lane(self) -> None:
        """Muat konfigurasi lane ringan tanpa pernah mengakses credential."""
        from jarvis.agent import providers
        from jarvis.core import config
        selected = str(config.get("routing.light.provider", "gemini") or "gemini")
        names = providers.chat_provider_names()
        if selected not in names:
            names.insert(0, selected)
        self._light_provider.blockSignals(True)
        self._light_provider.clear()
        self._light_provider.addItems(list(dict.fromkeys(names)))
        self._light_provider.setCurrentText(selected)
        self._light_provider.blockSignals(False)
        self._light_model.setText(
            str(config.get("routing.light.model", "") or ""))
        self._refresh_lane_status()

    def _refresh_lane_status(self) -> None:
        try:
            from jarvis.agent import model_routing
            lane = model_routing.role_statuses().get("light", {})
        except Exception:                                    # noqa: BLE001
            lane = {}
        if lane.get("configured"):
            provider = str(lane.get("provider") or "-")
            model = str(lane.get("model") or "default")
            self._lane_status.setText(
                f"Telegram light lane siap: {provider} ({model})")
        else:
            self._lane_status.setText(
                "Telegram light lane belum siap — pilih provider lalu "
                "lengkapi konfigurasinya di sheet ini.")

    def _save_light_lane(self) -> None:
        provider = self._light_provider.currentText().strip()
        model = self._light_model.text().strip()
        ok_provider, message = settings_service.set_value(
            "routing.light.provider", provider, "choice")
        if not ok_provider:
            self._lane_status.setText(f"Gagal menyimpan jalur ringan: {message}")
            return
        ok_model, message = settings_service.set_value(
            "routing.light.model", model, "text")
        if not ok_model:
            self._lane_status.setText(f"Gagal menyimpan model ringan: {message}")
            return
        self._refresh_lane_status()
        self.saved.emit()

    def _reload_heavy_lane(self) -> None:
        """Muat provider yang benar-benar dipakai native agent."""

        from jarvis.agent import providers
        from jarvis.core import config

        selected = str(config.get(
            "routing.heavy.provider", "") or "").strip()
        names = providers.chat_provider_names()
        if selected and selected not in names:
            names.insert(0, selected)
        self._heavy_provider.blockSignals(True)
        self._heavy_provider.clear()
        self._heavy_provider.addItems(list(dict.fromkeys(names)))
        if selected:
            self._heavy_provider.setCurrentText(selected)
        self._heavy_provider.blockSignals(False)
        self._heavy_model.setText(
            str(config.get("routing.heavy.model", "") or ""))
        self._refresh_heavy_status()

    def _refresh_heavy_status(self) -> None:
        try:
            from jarvis.agent import model_routing

            lane = model_routing.role_statuses().get("heavy", {})
        except Exception:                                   # noqa: BLE001
            lane = {}
        if lane.get("configured"):
            provider = str(lane.get("provider") or "-")
            model = str(lane.get("model") or "default")
            self._heavy_status.setText(
                f"Native agent siap: {provider} ({model})")
        else:
            self._heavy_status.setText(
                "Native agent belum siap — simpan credential/model provider, "
                "lalu pilih provider kerja di sini.")

    def _save_heavy_lane(self) -> None:
        provider = self._heavy_provider.currentText().strip()
        model = self._heavy_model.text().strip()
        if not provider:
            self._heavy_status.setText("Pilih provider native agent.")
            return
        ok_provider, message = settings_service.set_value(
            "routing.heavy.provider", provider, "choice")
        if not ok_provider:
            self._heavy_status.setText(
                f"Provider belum siap: {message}")
            return
        ok_model, message = settings_service.set_value(
            "routing.heavy.model", model, "text")
        if not ok_model:
            self._heavy_status.setText(
                f"Gagal menyimpan model agent: {message}")
            return
        from jarvis.agent import llm_client

        llm_client.reset()
        self._refresh_heavy_status()
        self._roles_lbl.setText(settings_service.provider_role_summary())
        self.saved.emit()

    def _load_fields(self, name: str) -> None:
        if not name:
            return
        from jarvis.agent import providers
        p = providers.get_provider(name)
        self._base_url.setText(p.base_url)
        self._api_key.setText(p.api_key)
        self._model.setText(p.model)
        self._vision_model.setText(p.vision_model)
        self._set_detected_models(())
        self._show_manual_fallback(False)
        is_oauth = p.auth == "oauth"
        self._base_url.setEnabled(not is_oauth)
        self._api_key.setEnabled(not is_oauth)
        self._storage_lbl.setText(
            f"Penyimpanan aman: {secrets_store.backend_label()}")
        active = providers.active_name()
        self._active_lbl.setText(
            f"provider aktif agent: {active}"
            + ("   ← sedang dipilih" if active == name else ""))
        self._roles_lbl.setText(settings_service.provider_role_summary())
        try:
            self._stack_lbl.setText(settings_service.active_stack_summary())
        except Exception:                                    # noqa: BLE001
            self._stack_lbl.setText("")
        if is_oauth:
            try:
                if name == "openai_oauth":
                    from jarvis.integrations import openai_oauth as oauth_module
                elif name == "anthropic_oauth":
                    from jarvis.integrations import anthropic_oauth as oauth_module
                else:
                    oauth_module = None
                oauth_status = oauth_module.status() if oauth_module else {
                    "connected": p.configured(), "needs_reauth": False,
                    "token_refresh_due": False, "last_error_code": ""}
            except Exception:                               # noqa: BLE001
                oauth_status = {"connected": False, "needs_reauth": False,
                                "token_refresh_due": False,
                                "last_error_code": "unknown"}
            if oauth_status["needs_reauth"]:
                detail = "OAuth perlu sign in ulang"
            elif oauth_status["connected"]:
                detail = "OAuth terhubung"
                if oauth_status["token_refresh_due"]:
                    detail += "; refresh akan dilakukan saat diperlukan"
            else:
                detail = "OAuth belum terhubung"
            if oauth_status["last_error_code"]:
                detail += f"; status: {oauth_status['last_error_code']}"
            self._status.setText(f"jenis: {p.kind} — {detail}")
        else:
            self._status.setText(f"jenis: {p.kind} — "
                                 + ("siap" if p.configured()
                                    else "belum lengkap"))
        self._oauth_button.setVisible(name in {"openai_oauth", "anthropic_oauth"})
        # API-key/local provider dapat diuji dari nilai field yang baru diketik;
        # OAuth wajib sudah tersambung agar token aman tersedia.
        self._detect_models_button.setVisible(
            not is_oauth or bool(oauth_status.get("connected")))
        # Auto-deteksi model saat provider dipilih bila katalog siap, dan
        # tentukan dukungan vision otomatis untuk model aktif.
        self._update_vision_support(p.model)
        if name in {"openai_oauth", "anthropic_oauth"}:
            connected = bool(oauth_status.get("connected"))
            provider_label = name.replace("_", " ").upper()
            self._oauth_button.setText(
                f"PUTUSKAN {provider_label}" if connected
                else f"HUBUNGKAN {provider_label}")

    # ── aksi ──────────────────────────────────────────────────────────────

    def _save(self) -> None:
        from jarvis.agent import providers
        name = self._combo.currentText()
        if not name:
            return
        key = self._api_key.text().strip()
        provider = providers.get_provider(name)
        options = {
            "model": self._model.text().strip(),
            "vision_model": self._vision_model.text().strip(),
        }
        if provider.auth != "oauth":
            options["base_url"] = self._base_url.text().strip()
            options["api_key"] = key
        ok = providers.save_provider(name, **options)
        if not ok:
            self._status.setText(
                "Gagal menyimpan — backend terenkripsi tidak tersedia.")
            return
        if name == "gemini":
            llm.reset_client()
        _logger.info("settings.provider_saved", provider=name)
        self._status.setText(f"{name} tersimpan.")
        self._load_fields(name)
        self._reload_heavy_lane()
        if self._catalog_ready(providers.get_provider(name), {}):
            self._detect_models()
        self.saved.emit()

    def _set_active(self) -> None:
        from jarvis.agent import providers
        name = self._combo.currentText()
        provider = providers.get_provider(name)
        if not provider.configured():
            self._set_connection_status(
                "Provider belum lengkap — SIMPAN dan TES KONEKSI dahulu.",
                "error",
            )
            return
        ok_route, message = settings_service.set_value(
            "routing.heavy.provider", name, "choice")
        if not ok_route:
            self._set_connection_status(
                f"Gagal mengaktifkan jalur agent: {message}", "error")
            return
        settings_service.set_value("routing.heavy.model", "", "text")
        if not providers.set_active(name):
            self._set_connection_status(
                "Provider tersimpan tetapi gagal dijadikan aktif.", "error")
            return
        self._set_connection_status(
            f"{name} kini provider aktif DAN provider native agent.", "ok")
        self._reload_heavy_lane()
        self._load_fields(name)
        self.saved.emit()

    def _delete_provider(self) -> None:
        from jarvis.agent import providers
        name = self._combo.currentText()
        if not name:
            return
        if not providers.delete_provider(name):
            self._status.setText("Gagal menghapus provider atau credential aman.")
            return
        self._status.setText(f"{name} dihapus dari penyimpanan.")
        self._reload_names()
        self.saved.emit()

    def _oauth_action(self) -> None:
        """Login OAuth non-blocking; UI hanya menerima status aman."""
        name = self._combo.currentText()
        if name == "openai_oauth":
            from jarvis.integrations import openai_oauth as oauth_module
        elif name == "anthropic_oauth":
            from jarvis.integrations import anthropic_oauth as oauth_module
        else:
            return
        status = oauth_module.status()
        if status.get("connected"):
            oauth_module.logout()
            from jarvis.agent import providers
            providers.reset_clients()
            self._status.setText(f"{name} diputuskan.")
            self._load_fields(name)
            self.saved.emit()
            return
        self._oauth_provider = name
        if name == "openai_oauth":
            from jarvis.integrations import openai_oauth_service
            state = openai_oauth_service.start(self._oauth_updated.emit)
            self._status.setText(
                "Login OpenAI menunggu callback localhost …"
                if state.get("state") == "callback_pending"
                else "Membuka browser eksternal — selesaikan sign-in OpenAI …")
            return

        def worker() -> None:
            try:
                oauth_module.start_login()
                self._oauth_updated.emit({"provider": name, "state": "connected"})
            except Exception:                               # noqa: BLE001
                self._oauth_updated.emit({"provider": name, "state": "failed",
                                          "error": "login gagal"})

        threading.Thread(target=worker, daemon=True,
                         name=f"{name}-login").start()
        self._status.setText("Membuka browser eksternal — menunggu callback localhost …")

    def _apply_oauth_update(self, state: dict) -> None:
        name = str(state.get("provider") or self._oauth_provider or "openai_oauth")
        if state.get("state") == "connected":
            self._status.setText(
                f"{name} terhubung — pilih model lalu jadikan provider aktif.")
            self.saved.emit()
            # Deteksi katalog terjadi otomatis di _load_fields saat provider
            # OAuth yang sudah terhubung dimuat ulang di bawah.
        elif state.get("state") == "models_synced":
            self._status.setText("Model OpenAI OAuth disinkronkan dari katalog akun.")
            self.saved.emit()
        elif state.get("state") == "failed":
            self._status.setText(str(state.get("error") or "login gagal"))
        self._load_fields(name)
        if state.get("state") == "connected":
            self._detect_models()

    @staticmethod
    def _catalog_ready(provider, oauth_status: dict) -> bool:
        if provider.auth == "oauth":
            return bool(oauth_status.get("connected"))
        if provider.kind == "openai_compat":
            return bool(provider.base_url and
                        (provider.api_key or provider.auth == "none"))
        return bool(provider.api_key)

    def _set_detected_models(self, models) -> None:
        """Dropdown tunggal. Disabled hingga discovery berhasil."""
        current = self._model.text().strip()
        items = tuple(models)
        self._detected_models.blockSignals(True)
        self._detected_models.clear()
        if not items:
            self._detected_models.addItem("Pilih model setelah Tes Koneksi")
            self._detected_models.setEnabled(False)
            self._probe_model_button.hide()
        else:
            for item in items:
                label = item.display_label() if hasattr(item, "display_label") else str(item)
                ident = item.id if hasattr(item, "id") else str(item)
                self._detected_models.addItem(label, ident)
            self._detected_models.setEnabled(True)
            tool_index = next((i for i, x in enumerate(items)
                               if getattr(x, "supports_tools", False)), 0)
            chosen = next((i for i in range(self._detected_models.count())
                           if self._detected_models.itemData(i) == current), tool_index)
            self._detected_models.setCurrentIndex(chosen)
            self._model.setText(str(self._detected_models.currentData() or ""))
            self._probe_model_button.show()
        self._detected_models.blockSignals(False)

    def _show_manual_fallback(self, visible: bool) -> None:
        self._model.setVisible(visible)
        self._model_label.setVisible(visible)
        if visible:
            self._probe_model_button.show()

    def _choose_detected_model(self, label: str) -> None:
        # ``label`` fallback menjaga kompatibilitas caller lama; UI baru selalu
        # memakai userData (ID asli) agar label context-window tidak tersimpan.
        model = str(self._detected_models.currentData() or label or "")
        if model and model != "Pilih model setelah Tes Koneksi":
            self._model.setText(model)
            self._update_vision_support(model)

    def _update_vision_support(self, model: str = "") -> None:
        """Auto-tentukan apakah provider+model yang dipilih mendukung vision.

        Vision ditentukan dari capability provider (deklaratif) — bukan tebakan
        nama model. Bila didukung dan kolom vision model kosong, isi otomatis
        dengan model terpilih agar jalur vision langsung siap.
        """
        from jarvis.agent import providers
        name = self._combo.currentText()
        try:
            supports = providers.get_provider(name).supports("vision")
        except Exception:                                    # noqa: BLE001
            supports = False
        if supports:
            self._vision_hint.setText("Vision: didukung ✓ (provider ini)")
            if model and not self._vision_model.text().strip():
                self._vision_model.setText(model)
        else:
            self._vision_hint.setText("Vision: tidak didukung provider ini")

    def _detect_models(self) -> None:
        """Tes koneksi = discovery katalog 5 detik pada worker UI-safe."""
        name = self._combo.currentText()
        self._set_detected_models(())
        self._show_manual_fallback(False)
        self._set_connection_status("● Menguji koneksi dan mendeteksi model …", "testing")
        # Jangan persist credential hanya untuk tes. Snapshot draft dipakai
        # worker, lalu SIMPAN tetap menjadi aksi eksplisit user.
        from dataclasses import replace
        from jarvis.agent import providers
        stored = providers.get_provider(name)
        draft = replace(
            stored,
            base_url=self._base_url.text().strip() or stored.base_url,
            api_key=self._api_key.text().strip() or stored.api_key,
        )

        def worker() -> None:
            try:
                from jarvis.agent import providers_discovery
                models = providers_discovery.discover(draft)
                payload = {"provider": name, "state": "models_detected",
                           "models": models}
            except Exception as exc:  # safe discovery errors only
                from jarvis.agent import providers_discovery
                payload = {"provider": name, "state": "models_failed",
                           "error": str(exc),
                           "manual": isinstance(exc, providers_discovery.DiscoveryError)
                           and providers_discovery.manual_fallback_allowed(exc)}
            try:
                self._model_catalog_updated.emit(payload)
            except RuntimeError:
                pass

        threading.Thread(target=worker, daemon=True,
                         name=f"{name}-model-discovery").start()

    def _apply_model_catalog(self, state: dict) -> None:
        name = str(state.get("provider") or "")
        if name != self._combo.currentText():
            return
        if state.get("state") == "agent_probe":
            result = state.get("result")
            if getattr(result, "ready", False):
                self._set_connection_status(
                    "● Agent siap — chat dan native tool calling terverifikasi.",
                    "ok",
                )
            elif getattr(result, "chat_ok", False):
                self._set_connection_status(
                    "● Chat terhubung, tetapi native tool calling belum "
                    "terverifikasi. Pilih model yang mendukung tools.",
                    "error",
                )
            else:
                self._set_connection_status(
                    "● Tes model belum berhasil. Periksa konfigurasi lalu coba lagi.",
                    "error",
                )
            return
        if state.get("state") == "models_failed":
            self._set_detected_models(())
            manual = bool(state.get("manual"))
            self._show_manual_fallback(manual)
            if manual:
                message = "● Gagal — format katalog tidak dikenali. Masukkan model manual."
            else:
                message = "● Koneksi provider belum tersedia. Periksa konfigurasi lalu coba lagi."
            self._set_connection_status(message, "error")
            return
        models = tuple(state.get("models", ()))
        self._set_detected_models(models)
        self._show_manual_fallback(False)
        self._set_connection_status(
            f"● Terhubung — {len(models)} model ditemukan. "
            "Klik TEST NATIVE AGENT MODEL untuk verifikasi tool calling."
            if models else "● Terhubung, tetapi provider tidak memberi model yang dapat dipilih.",
            "ok")

    def _probe_selected_agent_model(self) -> None:
        """Tes chat + function calling; tidak menjalankan tool sungguhan."""

        from dataclasses import replace
        from jarvis.agent import providers

        name = self._combo.currentText()
        stored = providers.get_provider(name)
        draft = replace(
            stored,
            base_url=self._base_url.text().strip() or stored.base_url,
            api_key=self._api_key.text().strip() or stored.api_key,
            model=self._model.text().strip() or stored.model,
        )
        self._set_connection_status(
            "● Katalog terhubung — menguji native tool calling …", "testing")

        def worker() -> None:
            from jarvis.agent import provider_probe

            result = provider_probe.probe(draft)
            try:
                self._model_catalog_updated.emit({
                    "provider": name,
                    "state": "agent_probe",
                    "result": result,
                })
            except RuntimeError:
                pass

        threading.Thread(
            target=worker,
            daemon=True,
            name=f"{name}-agent-probe",
        ).start()

    def _test(self) -> None:
        """Kompatibilitas tombol TEST lama: kini selalu discovery non-blocking."""
        self._detect_models()

    # ── kompatibel dengan SettingsSheet lama ──────────────────────────────

    def open_centered(self, parent_w: int, parent_h: int) -> None:
        w, h = 680, min(980, max(760, parent_h - 48))
        self._reload_light_lane()
        self._reload_heavy_lane()
        self._reload_names()
        self.setGeometry((parent_w - w) // 2, (parent_h - h) // 2, w, h)
        self.show()
        self.raise_()
