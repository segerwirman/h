"""Panel parity (PARITY v2 §5) — Capabilities, Messaging, Settings.

Fase 2a: kerangka + registrasi di ContentStage.
Fase 2b: tab Skills nyata di CapabilitiesPanel — list (counter, badge
learned, toggle), search, sort, detail pane. UI bicara HANYA ke
``jarvis.agent.capability_service`` (§3), tidak langsung ke skills/sidecar.

Messaging (Fase 3) dan Settings (Fase 4) masih placeholder.
Semua token visual dari jarvis/ui/theme.py.
"""
from __future__ import annotations

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QComboBox, QFrame, QHBoxLayout, QLabel, QLineEdit,
                             QPushButton, QScrollArea, QSplitter,
                             QTextBrowser, QVBoxLayout, QWidget)

from jarvis.core import log
from jarvis.ui import theme

_logger = log.get("ui.panels")


class _ParityPanel(QWidget):
    """Kerangka panel: judul + subjudul + area isi (diisi subclass/fase lanjut)."""

    TITLE = ""
    HINT = ""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.base};")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(32, 24, 32, 24)
        lay.setSpacing(10)

        title = QLabel(self.TITLE)
        title.setFont(theme.header_font(14))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;"
                            "letter-spacing: 4px;")
        lay.addWidget(title)

        hint = QLabel(self.HINT)
        hint.setFont(theme.mono_font(9))
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        lay.addWidget(hint)

        self.body = QVBoxLayout()
        lay.addLayout(self.body, stretch=1)
        lay.addStretch()


# ── Capabilities — tab Skills (Fase 2b) ──────────────────────────────────────

def _chip(text: str, color: str) -> QLabel:
    chip = QLabel(text)
    chip.setFont(theme.mono_font(7))
    chip.setStyleSheet(
        f"color: {color}; background: transparent;"
        f" border: 1px solid {color}; border-radius: 3px; padding: 1px 6px;")
    return chip


class _TogglePill(QPushButton):
    """Toggle on/off kecil: ON = accent penuh, OFF = kosong berbingkai dim."""

    def __init__(self, on: bool, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setChecked(on)
        self.setFixedSize(34, 16)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self._restyle()
        self.toggled.connect(lambda _: self._restyle())

    def _restyle(self) -> None:
        if self.isChecked():
            self.setStyleSheet(
                f"QPushButton {{ background: {theme.PAL.accent};"
                f" border: 1px solid {theme.PAL.accent}; border-radius: 8px; }}")
            self.setToolTip("Aktif — klik untuk mematikan")
        else:
            self.setStyleSheet(
                "QPushButton { background: transparent;"
                f" border: 1px solid {theme.PAL.text_dim}; border-radius: 8px; }}")
            self.setToolTip("Nonaktif — klik untuk mengaktifkan")


class _SkillRow(QFrame):
    """Satu baris skill: nama · chip kategori/learned · ×N · toggle."""

    selected = pyqtSignal(str)
    toggle_requested = pyqtSignal(str, bool)

    def __init__(self, skill: dict, parent=None):
        super().__init__(parent)
        self.name = skill["name"]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("skillRow")
        self.set_highlight(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        name = QLabel(skill["name"])
        name.setFont(theme.mono_font(9))
        color = theme.PAL.text if skill["enabled"] else theme.PAL.text_dim
        name.setStyleSheet(f"color: {color}; background: transparent;")
        lay.addWidget(name)

        lay.addWidget(_chip(skill["category"], theme.PAL.secondary))
        if skill["provenance"] == "agent":
            lay.addWidget(_chip("learned", theme.PAL.accent))
        lay.addStretch()

        if skill["usage"] > 0:                     # ×N hanya bila > 0 (§4.1)
            count = QLabel(f"×{skill['usage']}")
            count.setFont(theme.mono_font(8))
            count.setStyleSheet(
                f"color: {theme.PAL.text_dim}; background: transparent;")
            lay.addWidget(count)

        pill = _TogglePill(skill["enabled"])
        pill.clicked.connect(
            lambda checked: self.toggle_requested.emit(self.name, checked))
        lay.addWidget(pill)

    def set_highlight(self, on: bool) -> None:
        border = theme.PAL.accent_dim if on else "transparent"
        self.setStyleSheet(
            f"QFrame#skillRow {{ background: {theme.PAL.panel};"
            f" border: 1px solid {border}; border-radius: 4px; }}"
            f"QFrame#skillRow:hover {{ border: 1px solid {theme.PAL.text_dim}; }}")

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.name)
        super().mousePressEvent(event)


class _GroupRow(QFrame):
    """Satu baris grup tool: nama · subtitle · ×N calls · toggle.

    Grup unavailable (§5.5): abu, pill terkunci — bukan pilihan user.
    """

    selected = pyqtSignal(str)
    toggle_requested = pyqtSignal(str, bool)

    def __init__(self, group: dict, parent=None):
        super().__init__(parent)
        self.gid = group["id"]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("skillRow")                # gaya baris sama
        self.set_highlight(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        available = group["available"]
        name_col = theme.PAL.text if (available and group["enabled"]) \
            else theme.PAL.text_dim
        name = QLabel(group["name"])
        name.setFont(theme.mono_font(9))
        name.setStyleSheet(f"color: {name_col}; background: transparent;")
        lay.addWidget(name)

        sub = QLabel(group["subtitle"])
        sub.setFont(theme.mono_font(7))
        sub.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        lay.addWidget(sub)
        lay.addStretch()

        if group["calls"] > 0:
            count = QLabel(f"×{group['calls']}")
            count.setFont(theme.mono_font(8))
            count.setStyleSheet(
                f"color: {theme.PAL.text_dim}; background: transparent;")
            lay.addWidget(count)

        pill = _TogglePill(group["enabled"] and available)
        if not available:
            pill.setEnabled(False)
            pill.setToolTip("Tidak tersedia — dependency/kredensial hilang")
        else:
            pill.clicked.connect(
                lambda checked: self.toggle_requested.emit(self.gid, checked))
        lay.addWidget(pill)

    def set_highlight(self, on: bool) -> None:
        border = theme.PAL.accent_dim if on else "transparent"
        self.setStyleSheet(
            f"QFrame#skillRow {{ background: {theme.PAL.panel};"
            f" border: 1px solid {border}; border-radius: 4px; }}"
            f"QFrame#skillRow:hover {{ border: 1px solid {theme.PAL.text_dim}; }}")

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.gid)
        super().mousePressEvent(event)


class _HubRow(QFrame):
    """Baris skill hub: nama · chip kategori · Install / installed."""

    selected = pyqtSignal(str)
    install_requested = pyqtSignal(str)

    def __init__(self, skill: dict, parent=None):
        super().__init__(parent)
        self.name = skill["name"]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("skillRow")
        self.set_highlight(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        name = QLabel(skill["name"])
        name.setFont(theme.mono_font(9))
        name.setStyleSheet(f"color: {theme.PAL.text}; background: transparent;")
        lay.addWidget(name)
        lay.addWidget(_chip(skill["category"], theme.PAL.secondary))
        lay.addStretch()

        if skill["installed"]:
            lay.addWidget(_chip("installed", theme.PAL.accent))
        else:
            btn = QPushButton("Install")
            btn.setFont(theme.mono_font(8))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: {theme.PAL.panel};"
                f" color: {theme.PAL.accent}; border: 1px solid"
                f" {theme.PAL.accent_dim}; border-radius: 4px;"
                f" padding: 3px 12px; }}")
            btn.clicked.connect(
                lambda: self.install_requested.emit(self.name))
            lay.addWidget(btn)

    def set_highlight(self, on: bool) -> None:
        border = theme.PAL.accent_dim if on else "transparent"
        self.setStyleSheet(
            f"QFrame#skillRow {{ background: {theme.PAL.panel};"
            f" border: 1px solid {border}; border-radius: 4px; }}"
            f"QFrame#skillRow:hover {{ border: 1px solid {theme.PAL.text_dim}; }}")

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.name)
        super().mousePressEvent(event)


class _ImageGenControls(QWidget):
    """Selektor interaktif Image Generation (Capabilities → Tools).

    Provider ber-capability image + model (statis/terdeteksi) + tier gpt-image-2
    Low/Medium/High. Menulis langsung ke ``image_generation.*`` config lewat
    ``image_gen_service`` sehingga pilihan langsung berlaku untuk tool
    ``image_generate``. Semua string warna dari theme (FROZEN — dibaca saja).
    """

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self._svc = None
        try:
            from jarvis.agent import image_gen_service
            self._svc = image_gen_service
        except Exception as exc:                             # noqa: BLE001
            _logger.error("panels.image_svc_import_failed", error=str(exc)[:100])
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 6, 0, 0)
        lay.setSpacing(6)

        head = QLabel("IMAGE GENERATION")
        head.setFont(theme.header_font(9))
        head.setStyleSheet(f"color: {theme.PAL.accent};"
                           " background: transparent; letter-spacing: 2px;")
        lay.addWidget(head)

        lay.addWidget(self._dim_label("Provider"))
        self._provider = QComboBox()
        self._style_combo(self._provider)
        self._provider.currentTextChanged.connect(self._on_provider_changed)
        lay.addWidget(self._provider)

        lay.addWidget(self._dim_label("Model (terdeteksi / default — pilih)"))
        self._model = QComboBox()
        self._model.setEditable(True)
        self._style_combo(self._model)
        self._model.currentTextChanged.connect(self._on_model_changed)
        lay.addWidget(self._model)

        self._detect_btn = QPushButton("DETEKSI MODEL")
        self._style_button(self._detect_btn)
        self._detect_btn.clicked.connect(self._detect_models)
        lay.addWidget(self._detect_btn)

        self._vision_lbl = QLabel("")
        self._vision_lbl.setFont(theme.mono_font(8))
        self._vision_lbl.setStyleSheet(self._dim_css())
        self._vision_lbl.setWordWrap(True)
        lay.addWidget(self._vision_lbl)

        lay.addWidget(self._dim_label("GPT Image 2 — kualitas (Codex OAuth)"))
        tier_row = QHBoxLayout()
        tier_row.setSpacing(6)
        self._tier_btns: dict[str, QPushButton] = {}
        tiers = getattr(self._svc, "GPT_IMAGE_TIERS", ()) if self._svc else ()
        for tier in tiers:
            btn = QPushButton(tier["label"].replace("GPT Image 2 ", ""))
            btn.setToolTip(tier["hint"])
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setFont(theme.mono_font(8))
            btn.clicked.connect(
                lambda _=False, q=tier["quality"]: self._select_tier(q))
            self._tier_btns[tier["quality"]] = btn
            tier_row.addWidget(btn)
        tier_row.addStretch()
        lay.addLayout(tier_row)

        self._status = QLabel("")
        self._status.setFont(theme.mono_font(8))
        self._status.setStyleSheet(self._dim_css())
        self._status.setWordWrap(True)
        lay.addWidget(self._status)
        lay.addStretch()

        self.reload()

    # ── styling helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _dim_css() -> str:
        return f"color: {theme.PAL.text_dim}; background: transparent;"

    def _dim_label(self, text: str) -> QLabel:
        lab = QLabel(text)
        lab.setFont(theme.mono_font(8))
        lab.setStyleSheet(self._dim_css())
        return lab

    def _style_combo(self, combo: QComboBox) -> None:
        combo.setFont(theme.mono_font(9))
        combo.setStyleSheet(
            f"QComboBox {{ background: {theme.PAL.base}; color: {theme.PAL.text};"
            f" border: 1px solid {theme.PAL.accent_dim}; border-radius: 4px;"
            f" padding: 4px 8px; }}"
            f"QComboBox QAbstractItemView {{ background: {theme.PAL.base};"
            f" color: {theme.PAL.text};"
            f" selection-background-color: {theme.PAL.accent_dim}; }}")

    def _style_button(self, btn: QPushButton) -> None:
        btn.setFont(theme.mono_font(8))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.panel};"
            f" color: {theme.PAL.accent}; border: 1px solid {theme.PAL.accent_dim};"
            f" border-radius: 4px; padding: 5px 12px; }}")

    # ── data flow ────────────────────────────────────────────────────────────

    def reload(self) -> None:
        if self._svc is None:
            return
        cur = self._svc.current()
        providers = self._svc.list_providers()
        self._provider.blockSignals(True)
        self._provider.clear()
        self._provider.addItem("(otomatis)", "")
        for p in providers:
            mark = "  ✓" if p.ready else f"  · {p.reason}" if p.reason else ""
            self._provider.addItem(f"{p.label} [{p.tag}]{mark}", p.name)
        idx = self._provider.findData(cur["provider"])
        self._provider.setCurrentIndex(idx if idx >= 0 else 0)
        self._provider.blockSignals(False)
        self._reload_models(cur["provider"], preselect=cur["model"])
        self._mark_tier(cur["quality"])

    def _reload_models(self, provider_name: str, *, preselect: str = "",
                       models: list[str] | None = None) -> None:
        if self._svc is None:
            return
        if models is None:
            models = self._svc.models_for(provider_name)
        self._model.blockSignals(True)
        self._model.clear()
        self._model.addItems(models)
        if preselect:
            self._model.setCurrentText(preselect)
        self._model.blockSignals(False)
        self._update_vision_hint(provider_name)

    def _current_provider(self) -> str:
        return str(self._provider.currentData() or "")

    def _on_provider_changed(self, _text: str) -> None:
        if self._svc is None:
            return
        name = self._current_provider()
        ok = self._svc.set_provider(name)
        self._reload_models(name)
        self._status.setText(
            f"Provider image: {name or '(otomatis)'}"
            + ("" if ok else "  — gagal simpan"))

    def _on_model_changed(self, model: str) -> None:
        if self._svc is None or not model.strip():
            return
        self._svc.set_model(model.strip())
        self._update_vision_hint(self._current_provider())

    def _detect_models(self) -> None:
        if self._svc is None:
            return
        name = self._current_provider()
        if not name:
            self._status.setText("Pilih provider konkret dulu untuk deteksi.")
            return
        self._status.setText("Mendeteksi model provider …")
        models = self._svc.detect_models(name)
        self._reload_models(name, preselect=self._model.currentText().strip(),
                            models=models)
        self._status.setText(f"{len(models)} model terdeteksi untuk {name}.")

    def _update_vision_hint(self, provider_name: str) -> None:
        """Auto-tentukan apakah provider aktif mendukung vision."""
        supports_vision = False
        try:
            from jarvis.agent import providers as prov
            if provider_name:
                supports_vision = prov.get_provider(provider_name).supports("vision")
        except Exception:                                    # noqa: BLE001
            supports_vision = False
        self._vision_lbl.setText(
            "Vision: didukung ✓" if supports_vision
            else "Vision: tidak didukung provider ini")

    def _select_tier(self, quality: str) -> None:
        if self._svc is None:
            return
        ok = self._svc.select_gpt_image_tier(quality)
        if ok:
            self._reload_models(self._current_provider(), preselect="gpt-image-2")
            self._mark_tier(quality)
            self._status.setText(f"GPT Image 2 tier: {quality} aktif.")
        else:
            self._status.setText("Tier tidak valid.")

    def _mark_tier(self, quality: str) -> None:
        for q, btn in self._tier_btns.items():
            active = q == quality
            btn.setStyleSheet(
                f"QPushButton {{ background:"
                f" {theme.PAL.accent_dim if active else theme.PAL.panel};"
                f" color: {theme.PAL.accent if active else theme.PAL.text};"
                f" border: 1px solid {theme.PAL.accent_dim};"
                f" border-radius: 4px; padding: 5px 10px; }}")


class CapabilitiesPanel(QWidget):
    """3 pane (PARITY §5.3): tab + search + list kiri, detail kanan."""

    TABS = ("Skills", "Tools", "MCP", "Browse Hub")
    _PLACEHOLDER = {"Skills": 'Try "github"', "Tools": 'Try "patch"'}

    def __init__(self, parent: QWidget | None = None,
                 service=None):
        super().__init__(parent)
        if service is None:
            from jarvis.agent import capability_service as service
        self._service = service
        self._sort_desc = True
        self._selected: str | None = None
        self._rows: dict[str, _SkillRow] = {}

        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.base};")

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 12)
        root.setSpacing(8)

        title_row = QHBoxLayout()
        title = QLabel("CAPABILITIES")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;"
                            "letter-spacing: 4px;")
        title_row.addWidget(title)
        title_row.addStretch()
        self._close_button = QPushButton("TUTUP")
        self._close_button.setFont(theme.mono_font(8))
        self._close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_button.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.panel}; color: "
            f"{theme.PAL.accent}; border: 1px solid {theme.PAL.accent_dim};"
            " border-radius: 4px; padding: 5px 12px; }}")
        self._close_button.clicked.connect(self.hide)
        title_row.addWidget(self._close_button)
        root.addLayout(title_row)

        split = QSplitter(Qt.Orientation.Horizontal)
        split.setChildrenCollapsible(False)
        root.addWidget(split, stretch=1)

        # ── pane kiri ────────────────────────────────────────────────────────
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 8, 0)
        ll.setSpacing(6)

        self._search = QLineEdit()
        self._search.setFont(theme.mono_font(9))
        self._search.setPlaceholderText(self._PLACEHOLDER["Skills"])
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.panel}; color: {theme.PAL.text};"
            f" border: 1px solid {theme.PAL.panel}; border-radius: 4px;"
            f" padding: 6px 10px; }}")
        self._search.textChanged.connect(lambda _: self._reload_list())
        ll.addWidget(self._search)

        tabs = QHBoxLayout()
        tabs.setSpacing(4)
        self._tab_buttons: dict[str, QPushButton] = {}
        for tab in self.TABS:
            b = QPushButton(tab)
            b.setFont(theme.mono_font(8))
            b.setCheckable(True)
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, t=tab: self._set_tab(t))
            self._tab_buttons[tab] = b
            tabs.addWidget(b)
        tabs.addStretch()
        ll.addLayout(tabs)

        self._sort_btn = QPushButton("↓ Most used")
        self._sort_btn.setFont(theme.mono_font(8))
        self._sort_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._sort_btn.setStyleSheet(
            "QPushButton { background: transparent; border: none;"
            f" color: {theme.PAL.text_dim}; text-align: left; }}"
            f"QPushButton:hover {{ color: {theme.PAL.accent}; }}")
        self._sort_btn.clicked.connect(self._flip_sort)
        ll.addWidget(self._sort_btn)

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

        note = QLabel("Changes apply to new sessions.")
        note.setFont(theme.mono_font(7))
        note.setAlignment(Qt.AlignmentFlag.AlignRight)
        note.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        ll.addWidget(note)

        split.addWidget(left)

        # ── pane kanan (detail + aksi curator §8) ───────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(6)
        self._detail = QTextBrowser()
        self._detail.setFont(theme.mono_font(9))
        self._detail.setOpenExternalLinks(False)
        self._detail.setStyleSheet(
            f"QTextBrowser {{ background: {theme.PAL.panel};"
            f" color: {theme.PAL.text}; border: none; border-radius: 4px;"
            f" padding: 14px; }}")
        rl.addWidget(self._detail, stretch=1)

        # Selektor Image Generation interaktif — hanya tampil saat grup
        # 'image_generation' dipilih di tab Tools.
        self._image_controls = _ImageGenControls()
        self._image_controls.hide()
        rl.addWidget(self._image_controls)

        act_row = QHBoxLayout()
        self._pin_btn = QPushButton("Pin")
        self._pin_btn.setFont(theme.mono_font(8))
        self._pin_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._pin_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.panel};"
            f" color: {theme.PAL.accent}; border: none; border-radius: 4px;"
            f" padding: 5px 12px; }}")
        self._pin_btn.clicked.connect(self._on_pin)
        self._pin_btn.hide()
        act_row.addWidget(self._pin_btn)
        self._archive_btn = QPushButton("Archive")
        self._archive_btn.setFont(theme.mono_font(8))
        self._archive_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._archive_btn.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.panel};"
            f" color: {theme.PAL.alert}; border: none; border-radius: 4px;"
            f" padding: 5px 12px; }}")
        self._archive_btn.clicked.connect(self._on_archive)
        self._archive_btn.hide()
        act_row.addWidget(self._archive_btn)
        act_row.addStretch()
        rl.addLayout(act_row)

        split.addWidget(right)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)

        self._set_tab("Skills")

    # ── tab ──────────────────────────────────────────────────────────────────

    def _set_tab(self, tab: str) -> None:
        self._tab = tab
        for name, btn in self._tab_buttons.items():
            active = name == tab
            btn.setChecked(active)
            color = theme.PAL.accent if active else theme.PAL.text_dim
            btn.setStyleSheet(
                "QPushButton { background: transparent; border: none;"
                f" color: {color}; padding: 3px 8px;"
                f" border-bottom: 1px solid {color if active else 'transparent'}; }}")
        self._search.setPlaceholderText(
            self._PLACEHOLDER.get(tab, "Search"))
        self._reload_list()

    def _flip_sort(self) -> None:
        self._sort_desc = not self._sort_desc
        self._sort_btn.setText(("↓ " if self._sort_desc else "↑ ") + "Most used")
        self._reload_list()

    # ── data ─────────────────────────────────────────────────────────────────

    def refresh(self) -> None:
        self._reload_list()

    def showEvent(self, event) -> None:                      # data segar tiap buka
        super().showEvent(event)
        self.refresh()

    def _clear_list(self) -> None:
        self._rows.clear()
        while self._list_lay.count() > 1:                    # sisakan stretch
            item = self._list_lay.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def _empty_state(self, text: str) -> None:
        self._clear_list()
        lbl = QLabel(text)
        lbl.setFont(theme.mono_font(9))
        lbl.setWordWrap(True)
        lbl.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;"
                          " padding: 18px;")
        self._list_lay.insertWidget(0, lbl)
        self._detail.setPlainText("")
        self._image_controls.hide()
        self._pin_btn.hide()
        self._archive_btn.hide()

    def _reload_list(self) -> None:
        if self._tab == "Tools":
            self._reload_tools()
            return
        if self._tab == "MCP":
            self._reload_mcp()
            return
        if self._tab == "Browse Hub":
            self._reload_hub()
            return

        try:
            items = self._service.list_skills(self._search.text().strip())
            items = self._service.sort_skills(items, self._sort_desc)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.skills_load_failed", error=str(e)[:120])
            self._empty_state("Gagal memuat skill — lihat log.")
            return

        self._clear_list()
        self._tab_buttons["Skills"].setText(
            f"Skills {self._service.skill_count()}")
        if not items:
            self._empty_state("Belum ada skill." if not self._search.text()
                              else "Tidak ada skill yang cocok.")
            return
        for skill in items:
            row = _SkillRow(skill)
            row.selected.connect(self._show_detail)
            row.toggle_requested.connect(self._on_toggle)
            self._rows[skill["name"]] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        if self._selected in self._rows:
            self._rows[self._selected].set_highlight(True)
            self._show_detail(self._selected)
        elif items:
            self._show_detail(items[0]["name"])

    def _reload_tools(self) -> None:
        try:
            items = self._service.list_tool_groups(self._search.text().strip())
            items = self._service.sort_tool_groups(items, self._sort_desc)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.tools_load_failed", error=str(e)[:120])
            self._empty_state("Gagal memuat grup tool — lihat log.")
            return

        self._clear_list()
        self._group_items = {g["id"]: g for g in items}
        self._tab_buttons["Tools"].setText(
            f"Tools {self._service.tool_group_count()}")
        if not items:
            self._empty_state("Tidak ada grup yang cocok.")
            return
        for group in items:
            row = _GroupRow(group)
            row.selected.connect(self._show_group_detail)
            row.toggle_requested.connect(self._on_group_toggle)
            self._rows[group["id"]] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        first = self._selected if self._selected in self._rows \
            else items[0]["id"]
        self._show_group_detail(first)

    def _reload_mcp(self) -> None:
        try:
            servers = self._service.list_mcp_servers()
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.mcp_load_failed", error=str(e)[:120])
            self._empty_state("Gagal membaca server MCP — lihat log.")
            return
        self._clear_list()
        if not servers:
            self._empty_state(
                "Belum ada server MCP. Tambahkan di config.yaml:\n\n"
                "mcp:\n  servers:\n    - name: fs\n      command: npx\n"
                "      args: [-y, \"@modelcontextprotocol/"
                "server-filesystem\", \"D:/data\"]\n\n"
                "Agent memakainya lewat tool mcp_list / mcp_call.")
            return
        self._mcp_items = {s["name"]: s for s in servers}
        for s in servers:
            row = _GroupRow({
                "id": s["name"], "name": s["name"],
                "subtitle": s["state"], "calls": 0, "tool_calls": {},
                "available": True, "enabled": s["enabled"]})
            row.selected.connect(self._show_mcp_detail)
            row.toggle_requested.connect(self._on_mcp_toggle)
            self._rows[s["name"]] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        first = self._selected if self._selected in self._rows \
            else servers[0]["name"]
        self._show_mcp_detail(first)

    def _show_mcp_detail(self, name: str) -> None:
        self._image_controls.hide()
        self._pin_btn.hide()
        self._archive_btn.hide()
        for row_id, row in self._rows.items():
            row.set_highlight(row_id == name)
        self._selected = name
        s = getattr(self, "_mcp_items", {}).get(name)
        if s is None:
            self._detail.setPlainText("")
            return
        tools = "\n".join(f"  - {t}" for t in s["tools"]) or "  (belum ada — "\
            "connect saat tool mcp_list/mcp_call dipakai agent)"
        err = f"\nError : {s['error']}" if s.get("error") else ""
        self._detail.setPlainText(
            f"{s['name']}\n[{s['state']}]\n\n"
            f"Command: {s['command']} {' '.join(s['args'])}{err}\n\n"
            f"Tools:\n{tools}")

    def _on_mcp_toggle(self, name: str, enabled: bool) -> None:
        try:
            ok = self._service.set_mcp_enabled(name, enabled)
            if not ok:
                _logger.error("panels.mcp_toggle_rejected", server=name)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.mcp_toggle_failed", error=str(e)[:120])
        self._reload_list()

    def _reload_hub(self) -> None:
        try:
            items = self._service.list_hub_skills(
                self._search.text().strip())
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.hub_load_failed", error=str(e)[:120])
            self._empty_state("Gagal membaca katalog hub — lihat log.")
            return
        self._clear_list()
        if not items:
            self._empty_state("Katalog hub kosong — cek skills.hub_sources "
                              "di config.yaml." if not self._search.text()
                              else "Tidak ada skill hub yang cocok.")
            return
        self._hub_items = {s["name"]: s for s in items}
        for s in items:
            row = _HubRow(s)
            row.selected.connect(self._show_hub_detail)
            row.install_requested.connect(self._on_hub_install)
            self._rows[s["name"]] = row
            self._list_lay.insertWidget(self._list_lay.count() - 1, row)
        first = self._selected if self._selected in self._rows \
            else items[0]["name"]
        self._show_hub_detail(first)

    def _show_hub_detail(self, name: str) -> None:
        self._image_controls.hide()
        self._pin_btn.hide()
        self._archive_btn.hide()
        for row_id, row in self._rows.items():
            row.set_highlight(row_id == name)
        self._selected = name
        s = getattr(self, "_hub_items", {}).get(name)
        if s is None:
            self._detail.setPlainText("")
            return
        status = "terinstal" if s["installed"] else "belum terinstal"
        self._detail.setPlainText(
            f"{s['name']}\n[{s['category']} · {status}]\n\n"
            f"{s['description']}\n\nSumber: {s['source_path']}")

    def _on_hub_install(self, name: str) -> None:
        try:
            ok, msg = self._service.install_hub_skill(name)
            if not ok:
                _logger.warning("panels.hub_install_rejected", msg=msg)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.hub_install_failed", error=str(e)[:120])
        self._reload_list()

    def _on_group_toggle(self, gid: str, enabled: bool) -> None:
        ok = False
        try:
            ok = self._service.set_group_enabled(gid, enabled)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.group_toggle_failed", error=str(e)[:120])
        if not ok:
            _logger.error("panels.group_toggle_rejected", group=gid)
        self._reload_list()

    def _show_group_detail(self, gid: str) -> None:
        self._pin_btn.hide()
        self._archive_btn.hide()
        for row_id, row in self._rows.items():
            row.set_highlight(row_id == gid)
        self._selected = gid
        g = getattr(self, "_group_items", {}).get(gid)
        if g is None:
            self._detail.setPlainText("")
            self._image_controls.hide()
            return
        # Grup Image Generation → tampilkan selektor provider/model/tier.
        is_image = gid == "image_generation"
        if is_image:
            self._image_controls.reload()
        self._image_controls.setVisible(is_image)
        status = []
        if not g["available"]:
            status.append("unavailable")
        if not g["enabled"]:
            status.append("disabled")
        # chip monospace per tool (§5.6): [read_file ×682] — hanya ×N > 0
        chips = "  ".join(
            f"[{t} ×{n}]" if n > 0 else f"[{t}]"
            for t, n in sorted(g["tool_calls"].items())) or "—"
        self._detail.setPlainText(
            f"{g['name']}\n{g['subtitle']}\n"
            + (f"[{' · '.join(status)}]\n" if status else "")
            + (f"\nAlasan: {g.get('availability_reason')}\n"
               if g.get("availability_reason") else "")
            + f"\nTotal calls: {g['calls']}\n\n{chips}")

    # ── interaksi ────────────────────────────────────────────────────────────

    def _on_toggle(self, name: str, enabled: bool) -> None:
        ok = False
        try:
            ok = self._service.set_skill_enabled(name, enabled)
        except Exception as e:                               # noqa: BLE001
            _logger.error("panels.toggle_failed", error=str(e)[:120])
        if not ok:
            _logger.error("panels.toggle_rejected", name=name)
        self._reload_list()

    def _on_pin(self) -> None:
        if self._selected:
            try:
                d = self._service.skill_detail(self._selected) or {}
                self._service.set_skill_pinned(self._selected,
                                               not d.get("pinned"))
            except Exception as e:                           # noqa: BLE001
                _logger.error("panels.pin_failed", error=str(e)[:120])
            self._reload_list()

    def _on_archive(self) -> None:
        if self._selected:
            try:
                ok, msg = self._service.archive_skill(self._selected)
                if not ok:
                    _logger.warning("panels.archive_rejected", msg=msg)
            except Exception as e:                           # noqa: BLE001
                _logger.error("panels.archive_failed", error=str(e)[:120])
            self._selected = None
            self._reload_list()

    def _show_detail(self, name: str) -> None:
        self._image_controls.hide()
        for row_name, row in self._rows.items():
            row.set_highlight(row_name == name)
        self._selected = name
        try:
            d = self._service.skill_detail(name)
        except Exception:                                    # noqa: BLE001
            d = None
        if d is None:
            self._detail.setPlainText("")
            self._pin_btn.hide()
            self._archive_btn.hide()
            return
        is_learned = d["provenance"] == "agent"
        self._pin_btn.setVisible(is_learned)
        self._pin_btn.setText("Unpin" if d.get("pinned") else "Pin")
        self._archive_btn.setVisible(is_learned)
        badges = [d["category"]]
        if is_learned:
            badges.append("learned")
        if d.get("pinned"):
            badges.append("pinned")
        if d.get("lifecycle") == "stale":
            badges.append("stale")
        if not d["enabled"]:
            badges.append("disabled")
        counters = f"use ×{d['use']} · view ×{d['view']} · patch ×{d['patch']}"
        triggers = ", ".join(d.get("triggers") or []) or "—"
        self._detail.setPlainText(
            f"{d['name']}\n[{' · '.join(badges)}]\n\n"
            f"{d['description']}\n\n"
            f"Triggers : {triggers}\n"
            f"Counter  : {counters}\n\n"
            f"{'─' * 40}\n{d['body']}")

    def open_centered(self, parent_w: int, parent_h: int) -> None:
        """Buka capabilities sebagai sheet lokal, bukan ContentStage legacy."""
        width, height = min(980, max(720, parent_w - 80)), \
            min(660, max(500, parent_h - 80))
        self.refresh()
        self.setGeometry((parent_w - width) // 2, (parent_h - height) // 2,
                         width, height)
        self.show()
        self.raise_()


class _PlatformRow(QFrame):
    """Baris platform: dot status + nama. Dot: accent = live, dim = lainnya,
    alert = startup_failed (img 5-7)."""

    selected = pyqtSignal(str)

    def __init__(self, plat: dict, parent=None):
        super().__init__(parent)
        self.pid = plat["id"]
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setObjectName("skillRow")
        self.set_highlight(False)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(10, 6, 10, 6)
        lay.setSpacing(8)

        color = (theme.PAL.accent if plat["live"]
                 else theme.PAL.alert if plat["state"] == "startup_failed"
                 else theme.PAL.text_dim)
        dot = QLabel("●")
        dot.setFont(theme.mono_font(8))
        dot.setStyleSheet(f"color: {color}; background: transparent;")
        lay.addWidget(dot)

        name = QLabel(plat["name"])
        name.setFont(theme.mono_font(9))
        name.setStyleSheet(f"color: {theme.PAL.text}; background: transparent;")
        lay.addWidget(name)
        lay.addStretch()

        state = QLabel(plat["state"])
        state.setFont(theme.mono_font(7))
        state.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        lay.addWidget(state)

    def set_highlight(self, on: bool) -> None:
        border = theme.PAL.accent_dim if on else "transparent"
        self.setStyleSheet(
            f"QFrame#skillRow {{ background: {theme.PAL.panel};"
            f" border: 1px solid {border}; border-radius: 4px; }}"
            f"QFrame#skillRow:hover {{ border: 1px solid {theme.PAL.text_dim}; }}")

    def mousePressEvent(self, event) -> None:
        self.selected.emit(self.pid)
        super().mousePressEvent(event)


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
        pid = self._selected
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
