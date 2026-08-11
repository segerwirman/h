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



