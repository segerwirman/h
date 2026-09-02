"""Local Qt widgets used by the Mark XLIX main window."""
from __future__ import annotations

import asyncio

from PyQt6.QtCore import QRectF, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QTextCursor
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QLineEdit, QPushButton, QTextEdit, QVBoxLayout, QWidget

from jarvis.core import action_registry, config
from jarvis.core.action_registry import Action
from jarvis.core.resolver import ClarifyNeeded, resolve
from jarvis.ui import theme
from jarvis.ui.orb import OrbState

_DOT_COLORS = {
    OrbState.IDLE: "accent_dim", OrbState.BOOT: "accent_dim",
    OrbState.LISTENING: "accent", OrbState.THINKING: "secondary",
    OrbState.SPEAKING: "accent", OrbState.EXECUTING: "success",
    OrbState.ERROR: "alert",
}


class _StatusDot(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(16, 16)
        self._color = QColor(theme.PAL.accent_dim)

    def set_state(self, state: OrbState) -> None:
        self._color = QColor(getattr(theme.PAL,
                                     _DOT_COLORS.get(state, "accent_dim")))
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        glow = QColor(self._color)
        glow.setAlpha(70)
        p.setBrush(glow)
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QRectF(1, 1, 14, 14))
        p.setBrush(self._color)
        p.drawEllipse(QRectF(4.5, 4.5, 7, 7))


def escape_action(*, speaking: bool, has_input: bool, panel_open: bool) -> str:
    if speaking:
        return "interrupt"
    if has_input:
        return "clear"
    return "close_panel" if panel_open else "none"


def model_indicator_text() -> str:
    try:
        from jarvis.agent import model_routing
        light = model_routing.role_statuses().get("light", {})
        return f"{light.get('model') or light.get('provider') or 'Model'} · Light"
    except Exception:
        return "Model · Light"


def agent_model_indicator_text() -> str:
    """Provider/model that actually executes tasks from the command box."""
    try:
        from jarvis.agent import model_routing
        heavy = model_routing.role_statuses().get("heavy", {})
        model = heavy.get("model") or heavy.get("provider") or "Agent"
        return f"AGENT · {model}"
    except Exception:
        return "AGENT · provider"


def palette_entities() -> list[str]:
    try:
        return action_registry.default_registry().all_entities()
    except Exception:
        return []


def resolve_typed_action(text: str, *, registry=None):
    return resolve(text, source="text", registry=registry)


def execute_typed_action(action: Action) -> str | None:
    """Run typed L0/L1; unsupported actions share voice's LLM fall-open."""
    from jarvis.integrations import local_action_executor
    try:
        return asyncio.run(local_action_executor.submit(action))
    except ValueError:
        return None


def typed_action_interrupts_audio() -> bool:
    # Text is an independent command channel, not acoustic barge-in. It never
    # cuts existing speech; only explicit ESC / interrupt owns that behavior.
    return False


def route_typed_resolution(outcome, text: str, *, execute=execute_typed_action,
                           fall_open, clarify) -> None:
    """Execute typed L0/L1 or preserve voice-equivalent fall-open semantics."""
    if isinstance(outcome, Action):
        if execute(outcome) is not None:
            return
        fall_open(text)
        return
    if isinstance(outcome, ClarifyNeeded):
        clarify(outcome)
        return
    fall_open(text)


class _CliTextEdit(QTextEdit):
    submitted = pyqtSignal(str)
    palette_requested = pyqtSignal(str)
    tab_pressed = pyqtSignal()
    focus_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ghost = ""
        self.setAcceptRichText(False)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.textChanged.connect(self._sync_height)
        self._sync_height()

    def _line_height(self) -> int:
        return self.fontMetrics().lineSpacing()

    def _max_height(self) -> int:
        return self._line_height() * 8 + self.contentsMargins().top() + self.contentsMargins().bottom()

    def _sync_height(self) -> None:
        blocks = self.document().blockCount()
        doc_h = max(int(self.document().size().height()), blocks * self._line_height())
        height = max(self._line_height(), min(doc_h, self._max_height()))
        self.setFixedHeight(height + self.contentsMargins().top() + self.contentsMargins().bottom())

    def set_ghost(self, ghost: str) -> None:
        self._ghost = ghost
        self.viewport().update()

    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.focus_changed.emit(True)

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.focus_changed.emit(False)

    def keyPressEvent(self, event):
        key, mods = event.key(), event.modifiers()
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter) and not mods & Qt.KeyboardModifier.ShiftModifier:
            text = self.toPlainText().strip()
            if text:
                self.submitted.emit(text)
            return
        if key == Qt.Key.Key_Tab and self._ghost:
            self.setPlainText(self.toPlainText() + self._ghost)
            self.moveCursor(QTextCursor.MoveOperation.End)
            self.set_ghost("")
            self.tab_pressed.emit()
            return
        if key == Qt.Key.Key_Slash and not self.toPlainText():
            self.palette_requested.emit("")
            return
        super().keyPressEvent(event)


class CommandBar(QWidget):
    """Zone C — multiline CLI input with existing predictive ghost text."""

    submitted = pyqtSignal(str)

    def __init__(self, predictive, parent=None):
        super().__init__(parent)
        self._predictive = predictive
        self._suggestion = ""
        self.setFixedHeight(int(config.get("zones.input_height", 56)))
        self.setStyleSheet("background: transparent;")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(24, 8, 24, 12)
        lay.setSpacing(10)

        prompt = QLabel("›")
        prompt.setFont(theme.header_font(15))
        prompt.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;")
        lay.addWidget(prompt)

        self._agent_badge = QLabel(agent_model_indicator_text())
        self._agent_badge.setToolTip(
            "Tugas kompleks dari kotak ini dijalankan agent native melalui "
            "provider/model Heavy di Settings."
        )
        self._agent_badge.setMaximumWidth(180)
        self._agent_badge.setStyleSheet(
            f"color: {theme.PAL.accent_dim}; background: transparent; "
            "font-size: 10px; padding-right: 4px;"
        )
        lay.addWidget(self._agent_badge)

        self.input = _CliTextEdit(self)
        self.input.setPlaceholderText("ketik tugas agent atau mulai obrolan…")
        self.input.setFont(theme.mono_font(11))
        self.input.setStyleSheet(
            f"QTextEdit {{ background: transparent; color: {theme.PAL.text};"
            f" border: none; border-bottom: 1px solid {theme.PAL.panel};"
            f" padding: 4px 2px; }}"
            f"QTextEdit:focus {{ border-bottom: 1px solid {theme.PAL.accent_dim}; }}")
        self.input.submitted.connect(self._submit)
        self.input.textChanged.connect(lambda: self._update_ghost(self.input.toPlainText()))
        self.input.tab_pressed.connect(self._accept_ghost)
        lay.addWidget(self.input, stretch=1)

        self._send = QPushButton("▶")
        self._send.setFixedSize(30, 30)
        self._send.setCursor(Qt.CursorShape.PointingHandCursor)
        self._send.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {theme.PAL.accent};"
            f" border: none; font-size: 14px; }}")
        self._send.clicked.connect(self._submit_from_button)
        self._send.hide()
        lay.addWidget(self._send)
        self.input.focus_changed.connect(self._send.setVisible)

    def _update_ghost(self, text: str) -> None:
        self._suggestion = self._predictive.suggest(text) if self._predictive else ""
        self.input.set_ghost(self._suggestion[len(text):] if self._suggestion else "")

    def _accept_ghost(self) -> None:
        if self._suggestion:
            self.input.setPlainText(self._suggestion)
            self.input.moveCursor(QTextCursor.MoveOperation.End)
            self.input.set_ghost("")

    def _submit_from_button(self, _checked: bool = False) -> None:
        """QPushButton.clicked always sends ``checked``; never feed it to
        ``_submit``, which reads its first argument as the text to submit."""
        self._submit()

    def _submit(self, submitted_text: str | None = None) -> None:
        text = (submitted_text if submitted_text is not None else self.input.toPlainText()).strip()
        if not text:
            return
        self.input.clear()
        if self._predictive:
            self._predictive.record(text)
        self._agent_badge.setText(agent_model_indicator_text())
        self.submitted.emit(text)


class _GhostLineEdit(QLineEdit):
    tab_pressed = pyqtSignal()
    focus_changed = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._ghost = ""

    def set_ghost(self, ghost: str) -> None:
        self._ghost = ghost
        self.update()

    def event(self, e):
        if (e.type() == e.Type.KeyPress
                and e.key() == Qt.Key.Key_Tab and self._ghost):
            self.tab_pressed.emit()
            return True
        return super().event(e)

    def focusInEvent(self, e):
        super().focusInEvent(e)
        self.focus_changed.emit(True)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        self.focus_changed.emit(False)

    def paintEvent(self, e):
        super().paintEvent(e)
        if self._ghost and self.hasFocus():
            p = QPainter(self)
            p.setPen(QColor(theme.PAL.text_dim))
            p.setFont(self.font())
            fm = self.fontMetrics()
            x = 4 + fm.horizontalAdvance(self.text())
            p.drawText(x, (self.height() + fm.ascent() - fm.descent()) // 2, self._ghost)


class ApiKeySheet(QWidget):
    """Minimal first-boot / reauth sheet (replaces the legacy SetupOverlay)."""

    done = pyqtSignal(str)
    _STATUS_COLORS = {"info": "text_dim", "error": "alert",
                      "success": "success"}

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 32, 40, 32)
        lay.setSpacing(14)
        title = QLabel("INITIALISATION")
        title.setFont(theme.header_font(15))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;" "letter-spacing: 4px;")
        lay.addWidget(title)
        hint = QLabel("Masukkan Gemini API key untuk mengaktifkan J.A.R.V.I.S")
        hint.setFont(theme.mono_font(9))
        hint.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        hint.setWordWrap(True)
        lay.addWidget(hint)
        self._key = QLineEdit()
        self._key.setEchoMode(QLineEdit.EchoMode.Password)
        self._key.setPlaceholderText("AIza…")
        self._key.setFont(theme.mono_font(11))
        self._key.setStyleSheet(
            f"QLineEdit {{ background: {theme.PAL.base}; color: {theme.PAL.text};"
            f" border: none; padding: 10px; }}")
        self._key.returnPressed.connect(self._submit)
        lay.addWidget(self._key)

        self._status = QLabel("")
        self._status.setFont(theme.mono_font(8))
        self._status.setWordWrap(True)
        self._status.setMinimumHeight(18)
        lay.addWidget(self._status)
        self._status_kind = "info"
        self.set_status("")

        self._activate = QPushButton("ACTIVATE")
        self._activate.setFont(theme.header_font(11))
        self._activate.setFixedHeight(38)
        self._activate.setCursor(Qt.CursorShape.PointingHandCursor)
        self._activate.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.base}; color: {theme.PAL.accent};"
            f" border: none; letter-spacing: 3px; }}")
        self._activate.clicked.connect(self._submit)
        lay.addWidget(self._activate)
        self._busy = False
        # Nilai yang sudah diserahkan ke pemilik, disimpan terpisah dari
        # kolom yang terlihat agar jalur "Coba lagi" tetap mungkin. Dibuang
        # permanen oleh clear_secret() saat pemilik mengonfirmasi keberhasilan.
        self._pending_secret = ""

    @property
    def busy(self) -> bool:
        return self._busy

    @property
    def status_text(self) -> str:
        return self._status.text()

    @property
    def status_kind(self) -> str:
        return self._status_kind

    def set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        self._key.setEnabled(not self._busy)
        self._activate.setEnabled(not self._busy)

    def set_status(self, text: str, kind: str = "info") -> None:
        kind = kind if kind in self._STATUS_COLORS else "info"
        self._status_kind = kind
        self._status.setText(str(text or ""))
        color = getattr(theme.PAL, self._STATUS_COLORS[kind])
        self._status.setStyleSheet(
            f"color: {color}; background: transparent;")

    def clear_secret(self) -> None:
        self._key.clear()
        self._pending_secret = ""

    def retry_secret(self) -> str:
        """Kembalikan secret ke kolom setelah pemilik melaporkan kegagalan.

        Fase 63 — jalur gagal tidak boleh berakhir buntu. ``_submit()`` kini
        mengosongkan kolom segera setelah hand-off agar secret tidak berlama-
        lama di dalam widget, tetapi ``window_voice.py:420`` menampilkan
        "Coba lagi" bila penyimpanan terenkripsi gagal. Tanpa pengembalian
        ini pesan itu bohong: kolomnya sudah kosong dan pemakai harus
        mengetik ulang seluruh key.

        Karena itu nilai yang diserahkan disimpan terpisah di
        ``_pending_secret`` — BUKAN di kolom yang terlihat — dan hanya
        dimasukkan kembali ke kolom saat pemilik secara eksplisit meminta
        retry. Nilai dihapus permanen oleh ``clear_secret()``.
        """
        pending = str(self._pending_secret or "")
        if pending:
            self._key.setText(pending)
        return self._key.text()

    def _submit(self):
        if self._busy:
            return
        key = self._key.text().strip()
        if not key:
            self.set_status("API key belum diisi.", "error")
            return
        self.set_busy(True)
        self.set_status("Memverifikasi provider …", "info")
        # Secret tidak boleh terbaca dari widget setelah diserahkan. Nilai
        # yang diserahkan disimpan terpisah agar jalur "Coba lagi" tetap
        # mungkin, lalu dibuang permanen oleh clear_secret() saat pemilik
        # mengonfirmasi keberhasilan.
        self._pending_secret = key
        self._key.clear()
        self.done.emit(key)
