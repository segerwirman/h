"""Mark XLIX main window — minimal cinematic (Part 1).

    Zone A  48px header: status dot · JARVIS · clock
    Zone B  center stage: the orb (whole screen when idle) over ContentStage
    Zone C  56px input line, chrome appears on focus

Everything else is a slide-in overlay (F1 task result + sys-stats, F2 activity
log, F3 file upload, F6 vision panel) or edge-hover. Do-not-regress hotkeys:
F4 mute, F11 fullscreen, ESC interrupt.

``JarvisUI`` at the bottom preserves the exact facade the legacy
``main.JarvisLive`` (Gemini Live audio, voice Charon) drives.
"""
from __future__ import annotations

import asyncio
import json
import re
import sys
import threading
import time

from PyQt6.QtCore import QPropertyAnimation, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QKeySequence, QPainter, QShortcut, QTextCursor
from PyQt6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit,
                             QMainWindow, QPushButton, QTextEdit, QVBoxLayout, QWidget)

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.core.command_palette import CommandPaletteModel
from jarvis.core.focus_mode import FocusMode
from jarvis.core.memory import MemoryManager
from jarvis.core.router import IntentRouter, Intent, search_url
from jarvis.core.target_resolver import ClosedItemHistory, TargetResolver, decide_and_close
from jarvis.core import action_registry
from jarvis.core.action_registry import Action
from jarvis.core.resolver import ClarifyNeeded, FallthroughToLLM, resolve
from jarvis.agent.router import Tier as ExecutionTier
from jarvis.agent.router import classify as classify_execution
from jarvis.nlp.summarize import ACTIVITY_LOG
from jarvis.ui import theme
from jarvis.ui.command_palette import CommandPalette
from jarvis.ui.notifications import NotificationBlipStack

from jarvis.ui.orb import Corner, OrbRenderer, OrbState, PresentationMode
from jarvis.ui.overlays import (ActivityLogDrawer, FileDropOverlay,
                                SysStatsOverlay, TaskResultDrawer, VisionPanel)
from jarvis.ui.stage import ContentStage, ContentStatus
from jarvis.ui.timeline import ContextTimeline

_logger = log.get("ui")

_LEGACY_STATE_MAP = {
    "LISTENING": OrbState.LISTENING,
    "SPEAKING": OrbState.SPEAKING,
    "THINKING": OrbState.THINKING,
    "PROCESSING": OrbState.EXECUTING,
    "SLEEPING": OrbState.IDLE,
    "INITIALISING": OrbState.BOOT,
    "MUTED": OrbState.IDLE,
    "ERROR": OrbState.ERROR,
    "IDLE": OrbState.IDLE,
    "EXECUTING": OrbState.EXECUTING,
}
_DOT_COLORS = {
    OrbState.IDLE: "accent_dim", OrbState.BOOT: "accent_dim",
    OrbState.LISTENING: "accent", OrbState.THINKING: "secondary",
    OrbState.SPEAKING: "accent", OrbState.EXECUTING: "success",
    OrbState.ERROR: "alert",
}


def camera_owns_stage(stage) -> bool:
    """True when the camera/vision panel is (or is becoming) the stage content.

    In that case the orb must disappear so it never overlaps the live camera /
    YOLO feed. Pure and defensive so it stays unit-testable against a bare
    ContentStage without a full window.
    """
    try:
        return stage.current == "vision" or stage.is_loading("vision")
    except Exception:
        return False


def _playback_level(win) -> float:
    """Level audio Jarvis 0..1 saat ini, diukur bukan diasumsikan (§19).

    Urutan: nilai eksplisit di window (untuk tes/seam mendatang) → tap
    playback nyata → 1.0. Fallback terakhir sengaja worst-case: echo yang
    tidak terukur akan memotong Jarvis sendiri, dan itulah cacat yang membuat
    barge-in dimatikan sejak awal.
    """
    explicit = getattr(win, "_playback_level", None)
    if explicit is not None:
        return max(0.0, min(1.0, float(explicit)))
    try:
        from jarvis.integrations import voice_playback_level as tap

        if not tap.is_installed():
            # Belum dipasang ≠ Jarvis sedang diam. Menyamakannya mematikan
            # echo guard diam-diam.
            return 1.0
        return max(0.0, min(1.0, float(tap.current_level())))
    except Exception:                                        # noqa: BLE001
        return 1.0


def _agent_ask_active() -> bool:
    """MK50 — True selama agent native menunggu confirm/cancel dari user,
    sehingga kata 'confirm'/'cancel' yang diketik dirutekan ke BUS, bukan
    ke router. Defensif: tanpa package agent pun window tetap jalan."""
    try:
        from jarvis.agent.adapters.ui import ask_active
        return ask_active()
    except Exception:
        return False


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
        self.input.setPlaceholderText(
            "ketik tugas agent atau mulai obrolan…"
        )
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
        self._send.clicked.connect(self._submit)
        self._send.hide()                       # no chrome until focused
        lay.addWidget(self._send)
        self.input.focus_changed.connect(self._send.setVisible)

    def _update_ghost(self, text: str) -> None:
        self._suggestion = self._predictive.suggest(text) if self._predictive else ""
        self.input.set_ghost(self._suggestion[len(text):]
                             if self._suggestion else "")

    def _accept_ghost(self) -> None:
        if self._suggestion:
            self.input.setPlainText(self._suggestion)
            self.input.moveCursor(QTextCursor.MoveOperation.End)
            self.input.set_ghost("")

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
        # Tab is consumed for focus traversal before keyPressEvent — intercept
        # here so it accepts the ghost suggestion instead.
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
            p.drawText(x, (self.height() + fm.ascent() - fm.descent()) // 2,
                       self._ghost)


class ApiKeySheet(QWidget):
    """Minimal first-boot / reauth sheet (replaces the legacy SetupOverlay)."""

    done = pyqtSignal(str)

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"background: {theme.PAL.panel};")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(40, 32, 40, 32)
        lay.setSpacing(14)
        title = QLabel("INITIALISATION")
        title.setFont(theme.header_font(15))
        title.setStyleSheet(f"color: {theme.PAL.accent}; background: transparent;"
                            "letter-spacing: 4px;")
        lay.addWidget(title)
        hint = QLabel("Masukkan Gemini API key untuk mengaktifkan J.A.R.V.I.S")
        hint.setFont(theme.mono_font(9))
        hint.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
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
        go = QPushButton("ACTIVATE")
        go.setFont(theme.header_font(11))
        go.setFixedHeight(38)
        go.setCursor(Qt.CursorShape.PointingHandCursor)
        go.setStyleSheet(
            f"QPushButton {{ background: {theme.PAL.base}; color: {theme.PAL.accent};"
            f" border: none; letter-spacing: 3px; }}")
        go.clicked.connect(self._submit)
        lay.addWidget(go)

    def _submit(self):
        key = self._key.text().strip()
        if key:
            self.done.emit(key)


class MainWindow(QMainWindow):
    _state_sig = pyqtSignal(str)
    _log_sig = pyqtSignal(str)
    _content_sig = pyqtSignal(str, str)
    _reconfig_sig = pyqtSignal()
    _vision_sig = pyqtSignal(bool)        # thread-safe show/hide vision panel

    def __init__(self, services: dict | None = None,
                 facades: object | None = None):
        super().__init__()
        services = services or {}
        self.router = IntentRouter()
        self.assistant = services.get("assistant")
        self.vision = services.get("vision")
        predictive = (self.assistant.module("PredictiveText")
                      if self.assistant else None)

        self.setWindowTitle(config.get("window.title", "J.A.R.V.I.S — MARK XLIX"))
        self.resize(int(config.get("window.width", 1100)),
                    int(config.get("window.height", 760)))
        self.setMinimumSize(int(config.get("window.min_width", 860)),
                            int(config.get("window.min_height", 600)))
        central = QWidget()
        central.setStyleSheet(f"background: {theme.PAL.base};")
        central.setMouseTracking(True)
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Zone A ───────────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(int(config.get("zones.header_height", 48)))
        header.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)
        self._dot = _StatusDot()
        hl.addWidget(self._dot)
        title = QLabel("JARVIS")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(f"color: {theme.PAL.text}; background: transparent;"
                            "letter-spacing: 6px;")
        hl.addWidget(title)
        hl.addStretch()
        self._clock = QLabel("")
        self._clock.setFont(theme.mono_font(10))
        self._clock.setStyleSheet(f"color: {theme.PAL.text_dim}; background: transparent;")
        hl.addWidget(self._clock)
        root.addWidget(header)

        # ── Zone B ───────────────────────────────────────────────────────────
        self.stage = ContentStage()
        root.addWidget(self.stage, stretch=1)

        # MK50 §7 — panel browser lama dibuang dari ContentStage. Browser
        # untuk tugas agent = Playwright (browser_* tools, headful); perintah
        # URL/pencarian ringan dibuka di browser sistem (open_url/run_search).
        self.browser = None
        self.vision_panel = VisionPanel()
        self.stage.register("vision", self.vision_panel)
        # MK50 — popup kalori DI DALAM frame kamera (widget baru, additive;
        # VisionPanel/overlays.py tidak diubah) + registrasi agent native.
        self.calorie_overlay = None
        try:
            from jarvis.ui.calorie_popup import CalorieOverlay
            self.calorie_overlay = CalorieOverlay(self.vision_panel)
        except Exception as e:
            _logger.warning("calorie.overlay_unavailable", error=str(e)[:100])
        try:
            from jarvis.agent.adapters.ui import register_ui
            register_ui(self, self.vision)
        except Exception as e:
            _logger.warning("agent.ui_register_failed", error=str(e)[:100])
        # MK50 §7.2 — panel info (berita/cuaca/pencarian) + panel Home
        # Assistant (§8). Gagal import → Jarvis tetap start tanpa panel.
        self.info_panel = None
        self.home_panel = None
        try:
            from jarvis.ui.info_panel import InfoPanel
            self.info_panel = InfoPanel()
            self.stage.register("info", self.info_panel)
        except Exception as e:                               # noqa: BLE001
            _logger.warning("info_panel.unavailable", error=str(e)[:100])
        try:
            from jarvis.ui.home_panel import HomePanel
            self.home_panel = HomePanel()
            self.stage.register("home", self.home_panel)
            self.home_panel.ready.connect(self._on_home_ready)
        except Exception as e:                               # noqa: BLE001
            _logger.warning("home_panel.unavailable", error=str(e)[:100])
        # Studio A is local planning only; action toggles/provider work wait for later phases.
        self.content_studio = None
        try:
            from jarvis.ui.content_studio import ContentStudioSheet
            self.content_studio = ContentStudioSheet()
            self.stage.register("studio", self.content_studio)
        except Exception as e:                               # noqa: BLE001
            _logger.warning("content_studio.unavailable", error=str(e)[:100])

        # ── Zone C ───────────────────────────────────────────────────────────
        self.command_bar = CommandBar(predictive)
        self.command_bar.submitted.connect(self.handle_command)
        root.addWidget(self.command_bar)

        # orb floats above the stage (transparent for mouse)
        # Scope the transparent orb canvas to the stage; a full-window overlay
        # can otherwise cover the persistent header title on some Qt backends.
        # AUDIT §8.5 lapis 3 — subclass yang menambah arc progres di halo.
        # orb.py FROZEN; menukar kelas di satu titik konstruksi ini membuatnya
        # tetap utuh. State orb TIDAK diubah: SPEAKING > LISTENING > THINKING
        # > IDLE tetap berlaku, progres hanya lapisan tambahan.
        from jarvis.ui.task_halo import TaskHaloOrb
        self.orb = TaskHaloOrb(self.stage)
        self.orb.set_status_word("IDLE")
        self.orb.set_reduced_motion(bool(config.get("ui.reduced_motion", False)))
        # countdown native (Phase WA1) — hidden-by-default, lokal
        self._countdown = None
        self._countdown_ticker: QTimer | None = None
        self._countdown_driver = None
        # facade lokal (Phase 27/29) — UI memakai facade, tidak bypass
        if facades is not None:
            self._facades = facades
        else:
            from jarvis.core.local_facades import default_facades
            self._facades = default_facades()

        # overlays
        self.sys_stats = SysStatsOverlay(central)
        self.activity = ActivityLogDrawer(central)
        # Ringkasan user-facing hasil/progres agent. Tidak tampil permanen;
        # F1 membuka drawer ini berdampingan dengan Sys Monitor.
        self.task_results = TaskResultDrawer(central)
        self.file_drop = FileDropOverlay(central)
        self.file_drop.file_selected.connect(self._on_file)
        self._api_sheet: ApiKeySheet | None = None

        # action panel (Mark L Change 3) + settings sheet
        from jarvis.ui.actionpanel import ActionPanel, SettingsSheet
        self.action_panel = ActionPanel(central)
        self.action_panel.vision_clicked.connect(self.toggle_vision_panel)
        self.action_panel.upload_clicked.connect(self.file_drop.toggle)
        self.action_panel.spotify_clicked.connect(self._open_spotify)
        # MK50 §7.3 — ikon Home Assistant membuka panel "home" (§8)
        if hasattr(self.action_panel, "home_clicked"):
            self.action_panel.home_clicked.connect(
                self._toggle_home_panel)
        if hasattr(self.action_panel, "studio_clicked"):
            self.action_panel.studio_clicked.connect(self._toggle_studio_panel)
        # MK50 — sheet settings multi-provider (Gemini/OpenAI/Anthropic/
        # Local OpenAI-compatible/Custom); fallback ke sheet lama bila modul
        # baru tidak tersedia. SettingsSheet lama tetap utuh di actionpanel.
        try:
            from jarvis.ui.settings_providers import ProviderSettingsSheet
            self.settings_sheet = ProviderSettingsSheet(central)
        except Exception as e:
            _logger.warning("settings.provider_sheet_unavailable",
                            error=str(e)[:100])
            self.settings_sheet = SettingsSheet(central)
        self.action_panel.settings_clicked.connect(
            lambda: self.settings_sheet.open_centered(
                self.centralWidget().width(), self.centralWidget().height()))
        self.settings_sheet.saved.connect(lambda: self.write_log(
            "SYS: Pengaturan provider diperbarui — klien dimuat ulang "
            "tanpa restart."))
        # MK50 §11.7 — Messaging berada di Settings sheet tersendiri, bukan
        # ContentStage. Ini hanya wiring seam; layout dasar window tetap utuh.
        from jarvis.ui.settings_messaging import MessagingSettingsSheet
        self.messaging_settings_sheet = MessagingSettingsSheet(central)
        self.action_panel.messaging_clicked.connect(
            lambda: self.messaging_settings_sheet.open_centered(
                self.centralWidget().width(), self.centralWidget().height()))
        self.messaging_settings_sheet.saved.connect(lambda: self.write_log(
            "SYS: Pengaturan Telegram Control diperbarui."))
        from jarvis.ui.gateway_operations import GatewayOperationsSheet
        self.gateway_operations_sheet = GatewayOperationsSheet(central)
        self.action_panel.gateway_ops_clicked.connect(
            lambda: self.gateway_operations_sheet.open_centered(
                self.centralWidget().width(), self.centralWidget().height()))
        # Fase 15S — approval lokal untuk secure remote setup (Telegram upload).
        from jarvis.ui.remote_setup_sheet import RemoteSetupSheet
        self.remote_setup_sheet = RemoteSetupSheet(None, central)
        self.remote_setup_sheet.hide()
        from jarvis.ui.monitor_source_sheet import MonitorSourceSheet
        self.monitor_source_sheet = MonitorSourceSheet(parent=central)
        self.monitor_source_sheet.hide()
        from jarvis.ui.panels import CapabilitiesPanel
        self.capabilities_sheet = CapabilitiesPanel(central)
        # QWidget child biasanya ikut visible saat parent MainWindow tampil.
        # Capabilities adalah sheet opt-in, jadi construct/register ≠ show.
        self.capabilities_sheet.hide()
        self.action_panel.capabilities_clicked.connect(
            lambda: self.capabilities_sheet.open_centered(
                self.centralWidget().width(), self.centralWidget().height()))

        # ── redesign P1/P2 subsystems ────────────────────────────────────────
        self.notifications = NotificationBlipStack(central)
        self.memory = MemoryManager.get()
        self._focus_mode = FocusMode.get()
        from jarvis.agent.remote_proposals import get_queue as get_remote_proposal_queue
        from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet
        self._remote_proposal_sheet = RemoteProposalSheet(
            get_remote_proposal_queue(), executor=self._execute_remote_proposal,
            parent=central)
        self._remote_proposal_sheet.hide()
        from jarvis.ui.studio_focus import StudioFocusController
        self._studio_focus = StudioFocusController(self.stage, self._focus_mode)
        if self.content_studio is not None:
            self.content_studio.studio_focus_requested.connect(self._set_studio_focus)
        self._target_resolver = TargetResolver()
        self._closed_items = ClosedItemHistory()
        self._pending_close_decision = None
        # Compatibility sentinel for older callers/tests. MK50 §7 no longer
        # creates or mounts a browser-agent QWidget in ContentStage.
        self._browser_agent = None
        self.window_controls = None            # WindowControlRegistry, lazy
        self.command_palette = CommandPalette(central, self._build_palette_model())
        self.command_palette.activated.connect(self._on_palette_activated)
        self.timeline = ContextTimeline(central)
        # AUDIT §8.5 — Task Deck: mini strip + panel + arc halo
        try:
            from jarvis.ui import task_wiring
            task_wiring.install(self)
        except Exception as e:                               # noqa: BLE001
            _logger.warning("task_deck.install_failed", error=str(e)[:120])

        # Hint hover kustom untuk ikon ActionPanel (bukan QToolTip).
        try:
            from jarvis.ui import action_hint
            self.action_hint = action_hint.install(self.action_panel, central)
        except Exception as e:                               # noqa: BLE001
            _logger.warning("action_hint.install_failed", error=str(e)[:120])

        self.action_panel.awareness_clicked.connect(self._toggle_awareness)
        self.action_panel.focus_mode_clicked.connect(self._toggle_focus_mode)
        self.action_panel.palette_clicked.connect(self._toggle_command_palette)
        self.action_panel.timeline_clicked.connect(self._toggle_timeline)

        # MK50 §7.2: ContentStage tetap hanya vision/info/home. Capabilities
        # dibuka sebagai sheet lokal melalui ActionPanel, bukan dipasang kembali
        # ke ContentStage legacy.

        # ── wiring ───────────────────────────────────────────────────────────
        self.on_text_command = None       # ← legacy JarvisLive hook (CHAT path)
        self.on_remote_clicked = None
        self.on_interrupt = None
        self._muted = False
        self._current_file: str | None = None
        self._pending_query: str | None = None
        self._ready = self._check_config()
        self._legacy_state = "INITIALISING"

        self._state_sig.connect(self._apply_state)
        self._log_sig.connect(self._append_log)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_api_sheet)
        self._vision_sig.connect(self._set_vision_visible)
        self.vision_panel.frame_available.connect(self._on_vision_frame_ready)
        self.stage.status_changed.connect(self._on_stage_status)

        # voice reply flow (Mark L Change 1.5)
        from jarvis.browser.reply import ReplyFlow
        self._skip_next_intercept = False
        self.reply_flow = ReplyFlow(self._run_browser_js, self._speak_line)

        BUS.subscribe("log", self._on_bus_log, ui=True)
        BUS.subscribe("boot.check", self._on_boot_check, ui=True)
        BUS.subscribe("vision.gesture", self._on_gesture, ui=True)
        BUS.subscribe("vision.status", self._on_vision_status, ui=True)
        BUS.subscribe("notify", self._on_notify, ui=True)
        BUS.subscribe("info.card", self._on_info_card_shown, ui=True)
        BUS.subscribe("intent", self._on_intent_event, ui=True)
        BUS.subscribe("confirm", self._on_confirm, ui=True)
        BUS.subscribe("cancel", self._on_cancel, ui=True)
        BUS.subscribe("sentiment.updated", self._on_sentiment, ui=True)
        BUS.subscribe("remote_setup.pending", self._on_remote_setup_pending, ui=True)
        BUS.subscribe("remote_proposal.pending", self._on_remote_proposal_pending, ui=True)
        BUS.subscribe("voice_proposal.pending", self._on_voice_proposal_pending, ui=True)
        self._pending_voice_proposal_id: str | None = None

        self._drain = QTimer(self)
        self._drain.timeout.connect(BUS.drain_ui)
        self._drain.start(30)
        self._info_recenter_tmr: QTimer | None = None
        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        self._bind_hotkeys()
        central.installEventFilter(self)
        # Layout memberi ukuran stage setelah konstruktor MainWindow selesai;
        # dengarkan stage langsung agar Orb tidak sempat memakai 100×30 default.
        self.stage.installEventFilter(self)
        QTimer.singleShot(0, self._sync_orb_geometry)
        self._edge_px = int(config.get("overlays.edge_hover_px", 8))

        self._apply_startup_panel()

        if not self._ready:
            QTimer.singleShot(200, self._show_api_sheet)

    # ── layout ───────────────────────────────────────────────────────────────

    def _sync_orb_geometry(self) -> None:
        """Cocokkan canvas Orb dengan ContentStage setelah layout Qt settle."""
        if hasattr(self, "orb"):
            self.orb.setGeometry(self.stage.rect())

    def _apply_startup_panel(self) -> None:
        """Buka panel stage hanya atas konfigurasi eksplisit.

        Default ``ui.startup.panel: null`` mempertahankan boot orb-only.
        Capabilities, settings, messaging, dan gateway adalah sheet lokal;
        mereka sengaja tidak dapat menjadi startup panel ContentStage.
        """
        panel = config.get("ui.startup.panel", None)
        if not isinstance(panel, str) or not panel.strip():
            return
        name = panel.strip().lower()
        if name == "vision":
            self.toggle_vision_panel()
            return
        if name == "home":
            self._toggle_home_panel()
            return
        if name not in self.stage.registered_names:
            _logger.warning("ui.startup_panel_invalid", panel=name)
            return
        self.stage.activate(name)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        c = self.centralWidget()
        self._sync_orb_geometry()
        for ov in (self.sys_stats, self.activity, self.task_results, self.file_drop):
            ov.reposition()
        self.action_panel.reposition(
            c.width(), c.height(),
            int(config.get("action_panel.above_input_px", 60)))
        if getattr(self, "task_strip", None) is not None:
            from jarvis.ui import task_wiring
            task_wiring.reposition(self)
        if self.settings_sheet.isVisible():
            self.settings_sheet.open_centered(c.width(), c.height())
        if self.messaging_settings_sheet.isVisible():
            self.messaging_settings_sheet.open_centered(c.width(), c.height())
        if self.gateway_operations_sheet.isVisible():
            self.gateway_operations_sheet.open_centered(c.width(), c.height())
        if self.capabilities_sheet.isVisible():
            self.capabilities_sheet.open_centered(c.width(), c.height())
        if self._api_sheet is not None:
            self._center_sheet()
        self.notifications.reposition()
        if self.command_palette.isVisible():
            self.command_palette.open_centered(c.width(), c.height())
        if self.timeline.isVisible():
            self.timeline.open_centered(c.width(), c.height())

    def changeEvent(self, e) -> None:
        super().changeEvent(e)
        if e.type() == e.Type.ActivationChange and not self.isActiveWindow():
            # parallax must not drift while the window is unfocused
            self.orb.set_parallax_target(0.0, 0.0)

    def eventFilter(self, obj, ev):
        if obj is self.stage and ev.type() in (ev.Type.Resize, ev.Type.Show):
            self._sync_orb_geometry()
        if ev.type() == ev.Type.MouseMove and obj is self.centralWidget():
            x = ev.position().x()
            w = self.centralWidget().width()
            if x <= self._edge_px:
                self.sys_stats.set_shown(True)
            elif self.sys_stats.shown and x > self.sys_stats.size_px + 40:
                self.sys_stats.set_shown(False)
            if x >= w - self._edge_px:
                self.activity.set_shown(True)
            elif self.activity.shown and x < w - self.activity.size_px - 40:
                self.activity.set_shown(False)
            if bool(config.get("ui.parallax.enabled", True)) and self.isActiveWindow():
                y = ev.position().y()
                h = self.centralWidget().height()
                self.orb.set_parallax_target((x - w / 2) * 0.02, (y - h / 2) * 0.02)
        return super().eventFilter(obj, ev)

    def _bind_hotkeys(self) -> None:
        binds = {
            config.get("hotkeys.task_result_view", "F1"): self._toggle_task_result_view,
            config.get("hotkeys.activity_log", "F2"): self.activity.toggle,
            config.get("hotkeys.file_upload", "F3"): self.file_drop.toggle,
            config.get("hotkeys.mute", "F4"): self.toggle_mute,
            config.get("hotkeys.vision_panel", "F6"): self.toggle_vision_panel,
            config.get("hotkeys.gesture_arm", "F8"): self.toggle_gesture_arm,
            config.get("hotkeys.fullscreen", "F11"): self._toggle_fullscreen,
            config.get("hotkeys.interrupt", "Escape"): self._do_interrupt,
            config.get("hotkeys.timeline", "F5"): self._toggle_timeline,
            config.get("hotkeys.focus_mode", "F7"): self._toggle_focus_mode,
            config.get("hotkeys.command_palette", "F9"): self._toggle_command_palette,
        }
        for key, fn in binds.items():
            QShortcut(QKeySequence(key), self).activated.connect(fn)

    def _toggle_task_result_view(self) -> None:
        """F1: ringkasan hasil agent di kanan + Sys Monitor di kiri.

        Keduanya sengaja satu shortcut agar user melihat status mesin dan
        hasil task berdampingan, namun tetap dapat disembunyikan bersama seperti
        Activity Log (F2). Bila salah satu drawer terbuka, F1 menyatukan state
        menjadi terlihat; bila keduanya terbuka, F1 menutup keduanya.
        """
        shown = not (self.sys_stats.shown and self.task_results.shown)
        self.sys_stats.set_shown(shown)
        self.task_results.set_shown(shown)

    def _run_browser_js(self, js: str, callback) -> None:
        # MK50 §7 — panel browser dibuang; runner JS degrade jujur.
        if self.browser is None or self.browser._view is None or not js.strip():
            callback("no-view")
            return
        self.browser._view.page().runJavaScript(js, callback)

    def _open_spotify(self) -> None:
        self.write_log("SYS: Membuka Spotify …")

        def _run():
            try:
                from actions.open_app import open_app as legacy_open
                legacy_open(parameters={"app_name": "Spotify"},
                            response=None, player=None)
            except Exception as e:
                self.write_log(f"ERR: Spotify — {str(e)[:80]}")
        threading.Thread(target=_run, daemon=True, name="spotify").start()

    def _on_info_card_shown(self, _data: dict) -> None:
        """Kartu info baru (§6.4/§7.2) → tampilkan panel info bila stage
        sedang kosong/info; panel aktif lain (vision/home) tidak direbut."""
        if self.info_panel is not None and \
                self.stage.current in (None, "info"):
            self.stage.show_child("info")

    def _toggle_studio_panel(self) -> None:
        """Toggle Studio local-only; ContentStage owns visibility, controller owns focus restore."""
        if self.content_studio is None:
            self._deferred_panel_notice("Content Studio", "panel tidak tersedia — lihat log")
            return
        self._studio_focus.toggle()
        self._sync_orb_visibility()

    def _set_studio_focus(self, active: bool) -> None:
        if self._studio_focus.set_studio_focus(bool(active)) and self.content_studio is not None:
            self.content_studio.set_studio_focus_active(bool(active))

    def _toggle_home_panel(self) -> None:
        """Buka Home lewat state LOADING; data/empty-state mengaktifkan panel."""
        if self.stage.current == "home" or self.stage.is_loading("home"):
            self._close_stage_panels()
            return
        if self.home_panel is None:
            self._deferred_panel_notice(
                "Home Assistant", "panel tidak tersedia — lihat log")
            return
        self.stage.begin_loading("home")
        self._sync_orb_visibility()
        self.home_panel.refresh()

    def _on_home_ready(self) -> None:
        if self.stage.is_loading("home"):
            self.stage.activate("home")
            self._sync_orb_visibility()

    def _deferred_panel_notice(self, name: str,
                               detail: str | None = None) -> None:
        detail = detail or (
            "tidak berada di ContentStage dan belum tersedia pada build ini")
        self.write_log(f"SYS: {name} — {detail}.")
        self.notifications.push(name, detail, "info")

    def go_home(self) -> None:
        """Clear ContentStage, return the orb to center, IDLE, panel undim."""
        self._close_stage_panels()
        self.write_log("SYS: Kembali ke tampilan utama.")

    def _close_stage_panels(self) -> None:
        """Tutup panel stage via cross-fade dan buang riwayat yang tak lagi
        relevan. Dipakai toggle, ESC, dan tombol kembali ke Home."""
        if getattr(self.stage, "current", None) == "studio":
            self._studio_focus.close()
        history = getattr(self, "stage_history", None)
        if history is not None:
            history.clear()
        self.stage.hide_all()
        self._sync_orb_visibility()
        self.orb.undock()
        self.orb.set_state(OrbState.IDLE)
        self.action_panel.set_dimmed(False)

    def _tick_clock(self) -> None:
        self.action_panel.set_dimmed(self.stage.status is ContentStatus.ACTIVE)
        self._clock.setText(time.strftime("%H:%M:%S · %a %d %b"))

    # ── command handling (Part 3.1 flows) ────────────────────────────────────

    def _on_stage_status(self, _status: str) -> None:
        """The only SPEAKING layout authority is real payload readiness."""
        active = self.stage.status is ContentStatus.ACTIVE
        self.orb.raise_()
        self.action_panel.set_dimmed(active)
        self._sync_action_panel_stage_indicators()
        self._sync_orb_visibility()
        if self._legacy_state == "SPEAKING" and not camera_owns_stage(self.stage):
            self.orb.set_presentation(PresentationMode.DOCKED_CONTENT_STAGE
                                      if active else PresentationMode.FULL_EMPTY_STAGE)

    def _sync_action_panel_stage_indicators(self) -> None:
        """Glow ikon selalu mencerminkan panel ContentStage yang benar-benar
        ACTIVE. Ikon lain padam otomatis saat user berpindah panel/menutupnya."""
        active = self.stage.status is ContentStatus.ACTIVE
        current = self.stage.current if active else None
        self.action_panel.set_camera_active(current == "vision")
        for name in ("home", "tasks"):
            self.action_panel.set_indicator(name, current == name)

    def _sync_orb_visibility(self) -> None:
        """The orb disappears exactly while the camera panel owns the stage,
        and is restored for every other content (browser, summary, home)."""
        self.orb.setVisible(not camera_owns_stage(self.stage))

    def _on_browser_ready(self, ok: bool) -> None:
        if ok:
            self.stage.activate("browser")
        else:
            self.stage.fail_loading()

    def _on_vision_frame_ready(self) -> None:
        if self.stage.status is ContentStatus.LOADING:
            self.stage.activate("vision")

    _CONFIRM_WORDS = ("confirm", "konfirmasi")
    _CANCEL_WORDS = ("cancel", "batalkan aksi")

    def handle_command(self, text: str) -> None:
        # typed path routes here directly — the You: echo must not re-route
        # through the voice intercept in _append_log
        self._skip_next_intercept = True
        self.write_log(f"You: {text}")
        # Destructive-action confirmation gate (redesign §13) uses distinct
        # words from ReplyFlow's ya/batal so the two confirmation contexts
        # never collide.
        if (self._pending_close_decision is not None
                or self._pending_voice_proposal_id is not None
                or _agent_ask_active()):
            low = text.strip().lower()
            if low in self._CONFIRM_WORDS:
                BUS.publish("confirm")
                return
            if low in self._CANCEL_WORDS:
                BUS.publish("cancel")
                return
        if self.reply_flow.handle_utterance(text):     # CONFIRM: ya / batal
            return
        # Jawaban untuk pertanyaan klarifikasi yang tertunda ditangani SEBELUM
        # routing — kalau tidak, "aplikasi" akan diklasifikasi ulang sebagai
        # perintah baru. Kalimat panjang sengaja tidak ditelan (clarify_state
        # mengembalikan None), sehingga user tetap bisa ganti topik.
        # Konfirmasi "matikan dirimu" ditangani sebelum routing — jawaban
        # "ya" tidak boleh diklasifikasi ulang sebagai perintah baru.
        if self._confirm_self_shutdown(text):
            return
        if self._handle_clarify_answer(text):
            return
        local = resolve_typed_action(text)
        def _execute_local(action):
            confirmation = execute_typed_action(action)
            if confirmation is not None:
                self.write_log(f"Jarvis: {confirmation}")
            return confirmation
        # Do not send FallthroughToLLM to Gemini Live yet. Doing that here and
        # then classifying T2 below started both Live chat and the native agent
        # for the same text, which looked like fluent conversation but caused
        # duplicate/competing execution. Local actions and clarification still
        # return immediately; unresolved text is routed exactly once below.
        if isinstance(local, Action):
            if _execute_local(local) is not None:
                return
        elif isinstance(local, ClarifyNeeded):
            self.write_log(f"Jarvis: {local.question}")
            return
        route = classify_execution(text, {"source": "text"})
        _logger.info(
            "router.decision",
            source="text",
            tier=int(route.tier),
            lane=route.lane,
            reason=route.reason,
        )
        if route.tier >= ExecutionTier.AGENT:
            self._run_agent_native(text)
            return
        from jarvis.integrations import google_direct
        google_call = google_direct.match_command(text)
        if google_call is not None:
            self._run_google_light(*google_call)
            return
        c = self.router.classify(text)
        BUS.publish("intent", intent=c.intent.value, text=text, meta=c.slots)
        self._dispatch_command(c, text)

    def _dispatch_command(self, c, text: str) -> None:
        """Normal command routing (no in-frame agent). Shared by the typed path
        and the in-frame agent's fallback so behaviour is identical."""
        if c.intent is Intent.SEARCH_WEB:
            query = c.slots.get("query", text)
            mode = c.slots.get("mode")
            if mode == "news":
                self.run_news(query)
            elif mode == "search":
                self.run_information(query)
            else:
                self.run_search(query)
        elif c.intent is Intent.OPEN_URL:
            self.open_url(c.slots.get("url", ""))
        elif c.intent is Intent.OPEN_BROWSER_AGENT:
            self.open_browser_agent(c.slots)
        elif c.intent is Intent.CLARIFY:
            self._ask_clarify(c.slots)
        elif c.intent is Intent.OPEN_APP:
            self.open_app(c.slots.get("app", text))
        elif c.intent is Intent.SYSTEM:
            self.run_system(c.slots, text)
        elif c.intent is Intent.NATIVE_AGENT_TASK:
            self.run_native_task(c.slots, text)
        else:
            self._chat(text)

    def _run_google_light(self, tool_name: str, args: dict) -> None:
        """T1 Google langsung via registry; tidak pernah masuk agent loop."""
        self.orb.set_state(OrbState.THINKING)

        def work():
            import asyncio
            from jarvis.agent import registry
            from jarvis.integrations import google_direct
            try:
                tool = registry.get(tool_name)
                if tool is None:
                    message = google_direct.unavailable_message(tool_name)
                    self.write_log(f"SYS: {message}")
                    self._speak_line(message)
                    return
                if not google_direct.enabled_by_tool_group(tool_name):
                    message = ("Tool Google Cloud sedang dimatikan di "
                               "Capabilities.")
                    self.write_log(f"SYS: {message}")
                    self._speak_line(message)
                    return
                result = asyncio.run(registry.execute(tool_name, args))
                text = str(result.display or result.for_llm())
                if result.ok:
                    self._speak_line(text)
                else:
                    message = result.error or "Google API gagal tanpa detail."
                    self.write_log(f"ERR: {message}")
                    self._speak_line(f"Maaf, {message}")
            except Exception as exc:
                message = f"Google tool gagal: {type(exc).__name__}"
                self.write_log(f"ERR: {message}")
                self._speak_line(f"Maaf, {message}")
            finally:
                self._restore_orb()

        threading.Thread(target=work, daemon=True,
                         name=f"google-light-{tool_name}").start()

    def run_search(self, query: str) -> None:
        """§23 — cari sungguhan, lalu tampilkan SUMBERNYA.

        Bentuk lama mengirim ``search_url(query)`` ke browser sistem, dan
        ``query`` kerap jatuh ke transkrip mentah. Yang muncul di layar Takeda
        adalah kalimatnya sendiri:

            'kan saya restoran yang - Search - Google Chrome'

        Itu memantulkan ucapan, bukan menjawabnya. Sekarang pencarian dijalankan
        lewat tool ``web_search`` yang menghasilkan sumber nyata (web, media
        sosial, peta), dan sumber itulah yang ditawarkan untuk dibuka.
        """
        self._run_web_lookup(query, mode="text", label="Informasi")

    def _run_web_lookup(self, query: str, *, mode: str, label: str) -> None:
        """Shared UI worker untuk berita/informasi; tool menentukan fallback."""
        self.orb.set_state(OrbState.THINKING)
        self.write_log(f"SYS: Mengambil {label.lower()} — {query} …")

        def _run() -> None:
            try:
                from actions.web_search import web_search
                result = web_search({"query": query, "mode": mode}, player=self)
                text = str(result or (
                    "Tidak menemukan berita untuk itu, sir."
                    if mode == "news" else "Tidak menemukan informasi untuk itu, sir."))
                self.write_log(f"Jarvis: {text[:700]}")
                self._content_sig.emit(label.upper(), text)
                self._speak_line(text[:900])
            except Exception as exc:                         # noqa: BLE001
                _logger.error("web_lookup.ui_route_failed", mode=mode,
                              exc_type=type(exc).__name__, error=str(exc)[:200])
                message = ("Sumber berita sedang bermasalah, sir. Coba lagi beberapa saat."
                           if mode == "news" else
                           "Tidak bisa menjangkau sumber informasi. Koneksi bermasalah.")
                self.write_log(f"ERR: {label.lower()} — {type(exc).__name__}")
                self._speak_line(message)
            finally:
                self._restore_orb()

        threading.Thread(target=_run, daemon=True,
                         name=f"{mode}-fetch").start()

    def run_news(self, query: str) -> None:
        """Berita nyata: Gemini Grounded + DDG fallback, bukan URL browser."""
        self._run_web_lookup(query, mode="news", label="BERITA")

    def run_information(self, query: str) -> None:
        """Pencarian informasi: Gemini Grounded + DDG fallback, bukan browser."""
        self._run_web_lookup(query, mode="search", label="INFORMASI")

    _YT_WATCH_RE = re.compile(
        r"(?:youtube\.com/watch\?(?:.*&)?v=|youtu\.be/)([\w-]{6,})", re.I)

    def open_url(self, url: str) -> None:
        if not url:
            return
        # deterministic URL policy (§6): only allowlisted schemes may load;
        # a schemeless value is treated as https, never executed via a shell.
        # Explicit-scheme detection requires "://" so "localhost:8080" stays a
        # host:port, not a scheme.
        allowed = set(config.get("browser.allowed_schemes", ["https", "http"]))
        m_scheme = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*)://", url)
        if m_scheme:
            if m_scheme.group(1).lower() not in allowed:
                self.write_log(
                    f"ERR: skema URL tidak diizinkan — {m_scheme.group(1)}://")
                return
        elif re.match(r"^[a-zA-Z][a-zA-Z0-9+.-]*:(?!\d)", url):
            self.write_log("ERR: skema URL tidak diizinkan.")
            return          # javascript:, data:… — reject; host:port passes
        else:
            url = f"https://{url}"
        # MK50 §7 — panel browser dibuang: URL tervalidasi dibuka di browser
        # sistem. Skema tetap dibatasi allowlist di atas (keamanan tak turun).
        from jarvis.core.native_actions import open_external_url

        result = open_external_url(url)
        if result.ok:
            self.write_log(f"SYS: Membuka {url} di browser sistem.")
        else:
            self.write_log(
                f"ERR: browser sistem gagal dibuka — {result.detail}")

    # ── penutupan aplikasi berpenjaga (DIAGNOSIS_2 MASALAH 3) ────────────

    def _close_named_app(self, slots: dict) -> None:
        """Tutup aplikasi BERNAMA di worker thread — guard ada di dalamnya."""
        name = str(slots.get("value") or "").strip()
        all_windows = bool(slots.get("all_windows"))

        def _run() -> None:
            try:
                from actions.close_app import close_app
                outcome = close_app(name, all_windows=all_windows)
            except Exception as exc:                         # noqa: BLE001
                outcome = None
                self.write_log(f"ERR: gagal menutup {name} — {str(exc)[:80]}")
            if outcome is not None:
                self.write_log(f"SYS: {outcome.message}")
                self._speak_line(outcome.message)

        threading.Thread(target=_run, daemon=True, name="close-app").start()

    def _request_self_shutdown(self) -> None:
        """'matikan dirimu' — minta konfirmasi, jangan langsung berhenti."""
        from jarvis.integrations import voice_safety

        message, _ok = voice_safety.handle_shutdown({})
        prompt = ("Anda yakin ingin saya berhenti sepenuhnya? "
                  "Jawab 'ya' untuk konfirmasi.")
        self.write_log(f"Jarvis: {prompt}")
        self._speak_line(prompt)
        self._pending_self_shutdown = True
        _ = message

    def _confirm_self_shutdown(self, text: str) -> bool:
        """``True`` bila teks ini menjawab permintaan berhenti."""
        if not getattr(self, "_pending_self_shutdown", False):
            return False
        low = text.strip().lower()
        if low in self._CONFIRM_WORDS or low in ("ya", "yes", "iya", "betul"):
            self._pending_self_shutdown = False
            from jarvis.integrations import voice_safety
            self.write_log("SYS: Menutup dengan rapi…")
            voice_safety.graceful_shutdown()
            return True
        if low in self._CANCEL_WORDS or low in ("tidak", "jangan", "batal",
                                                "no"):
            self._pending_self_shutdown = False
            self.write_log("SYS: Dibatalkan — saya tetap di sini.")
            return True
        return False

    # ── klarifikasi ambigu (DIAGNOSIS_2 MASALAH 2) ───────────────────────

    def _ask_clarify(self, slots: dict) -> None:
        """Bertanya satu kalimat, lalu menunggu — bukan menebak."""
        from jarvis.core import clarify_state

        question = str(slots.get("question") or "Maksud Anda yang mana?")
        clarify_state.set_pending(
            topic=str(slots.get("topic") or ""), question=question,
            options=list(slots.get("options") or []),
            app=str(slots.get("app") or ""), url=str(slots.get("url") or ""))
        self.write_log(f"Jarvis: {question}")
        self._speak_line(question)

    def _handle_clarify_answer(self, text: str) -> bool:
        """``True`` bila teks ini adalah jawaban dan sudah ditindaklanjuti."""
        from jarvis.core import clarify_state

        outcome = clarify_state.resolve(text)
        if outcome is None:
            return False
        kind, ask = outcome
        if kind == "declined":
            self.write_log("SYS: Dibatalkan.")
            return True
        if kind == "app":
            self.open_app(ask.app or ask.topic)
        else:
            self.open_url(ask.url)
        # Preferensi sudah disimpan clarify_state.resolve — pertanyaan yang
        # sama tidak akan diajukan lagi.
        self.write_log(
            f"SYS: Dicatat — '{ask.topic}' berarti "
            f"{'aplikasi' if kind == 'app' else 'browser'}.")
        return True

    def open_app(self, app: str) -> None:
        self.orb.set_state(OrbState.EXECUTING)

        def _run():
            try:
                from actions.open_app import launch_application

                outcome = launch_application(app)
                level = "SYS" if outcome.ok else "ERR"
                self.write_log(f"{level}: {outcome.message}")
            except Exception as e:
                self.write_log(f"ERR: gagal membuka {app} — {str(e)[:80]}")
            finally:
                self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="open-app").start()

    def run_system(self, slots: dict, text: str) -> None:
        action = slots.get("action", "")
        if action == "gesture_arm":
            self.set_gesture_armed(True)
            return
        if action == "gesture_disarm":
            self.set_gesture_armed(False)
            return
        if action == "vision_open":                    # Change 5
            self._set_vision_visible(True)
            return
        if action == "vision_close":
            self._set_vision_visible(False)
            return
        if action == "home":                           # Change 7
            self.go_home()
            return
        if action == "reply":                          # Change 1.5
            if self.stage.current == "browser":
                self.reply_flow.begin(slots.get("value", ""))
            else:
                self._speak_line("Buka halaman pesan terlebih dahulu, sir.")
            return
        # ── DIAGNOSIS_2 MASALAH 3 — penutupan yang tidak pernah kena diri ──
        if action == "close_app":
            self._close_named_app(slots)
            return
        if action == "close_blocked":
            name = slots.get("value", "itu")
            msg = (f"Saya tidak menutup '{name}' — proses itu saya sendiri. "
                   f"Kalau memang ingin saya berhenti, katakan 'matikan "
                   f"dirimu' dan saya akan minta konfirmasi dulu.")
            self.write_log(f"SYS: {msg}")
            self._speak_line(msg)
            return
        if action == "shutdown_jarvis_request":
            self._request_self_shutdown()
            return
        if action == "close_target":                    # redesign §13
            target = slots.get("value", "").strip()
            self._begin_close_target(target)
            return
        if action == "reopen_last_tab":                  # redesign §13
            self._reopen_last_tab()
            return
        if action == "calorie_analyze":                  # MK50 — kalori kamera
            self._run_calorie_analysis(slots.get("value", "") or "")
            return
        self.orb.set_state(OrbState.EXECUTING)

        def _run():
            try:
                from actions.computer_settings import computer_settings
                result = computer_settings(
                    parameters={"action": action, "description": text,
                                "value": slots.get("value", "")},
                    response=None, player=None)
                self.write_log(f"SYS: {result or 'Selesai.'}")
            except Exception as e:
                self.write_log(f"ERR: {action} — {str(e)[:80]}")
            finally:
                self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="system-action").start()

    def run_native_task(self, slots: dict, text: str) -> None:
        """Execute compatibility messaging/task intents using native Jarvis.

        Telegram keeps its existing direct adapter. Other external actions go
        through the native agent registry so tool-level confirmation and audit
        logging remain mandatory. There is intentionally no process/CLI
        fallback.
        """
        tier = int(slots.get("tier", 3))

        _tg_running = False
        if tier == 2 and slots.get("action") == "send" \
                and slots.get("platform", "telegram") == "telegram":
            try:
                from jarvis.agent.adapters import telegram as tg
                _tg_running = tg.TelegramService.get().running
            except Exception:
                _tg_running = False
        if _tg_running:
            # bot Telegram native berjalan → kirim langsung, tanpa Hermes
            msg = slots.get("text") or text
            self.orb.set_state(OrbState.EXECUTING)

            def _native_send():
                try:
                    from jarvis.agent.adapters import telegram as tg
                    ok = tg.send_from_anywhere(msg)
                    if ok:
                        self.write_log("SYS: Pesan terkirim ke telegram.")
                        self._speak_line("Pesan terkirim ke telegram, sir.")
                    else:
                        self.write_log("ERR: kirim telegram gagal.")
                        self._speak_line("Maaf, pengiriman pesan gagal.")
                finally:
                    self._restore_orb()
            threading.Thread(target=_native_send, daemon=True,
                             name="agent-tg-send").start()
            return

        task = slots.get("task") or text
        if tier == 2 and slots.get("action") == "send":
            platform = str(slots.get("platform", "") or "").strip().lower()
            message = str(slots.get("text") or "").strip()
            if platform == "whatsapp":
                task = (
                    "Gunakan tool whatsapp_send_message untuk memenuhi "
                    f"permintaan user berikut: {text}. Payload setelah nama "
                    f"platform: {message}. Gunakan hanya kontak allowlist; "
                    "jika kontak atau isi pesan ambigu, minta klarifikasi."
                )
            else:
                task = (
                    f"Kirim pesan melalui adapter native {platform}. "
                    f"Isi pesan: {message}"
                )
        self._run_agent_native(task)

    def run_hermes(self, slots: dict, text: str, **_) -> None:
        """Deprecated method alias; execution is permanently native."""
        self.run_native_task(slots, text)

    def _run_agent_native(self, task: str) -> None:
        """MK50 — jalankan T2+ dengan ACK lalu laporan hasil yang konkret."""
        from jarvis.agent import conversation_context, interactive_dispatch
        from jarvis.agent import delivery_lifecycle
        from jarvis.agent.adapters.ui import UIAdapter

        conversation_id = "typed-desktop"

        # Ultra low-latency: "buka gambar itu / tampilkan hasilnya" → langsung
        # buka artefak terakhir tanpa round-trip agent penuh. JARVIS tetap
        # ingat apa yang baru dikerjakannya.
        if conversation_context.is_artifact_reference(task):
            art_path, art_kind = conversation_context.STORE.last_artifact(
                conversation_id)
            if art_path and self._open_artifact(art_path, art_kind):
                return
            # Tidak ada artefak yang diingat → jujur, jangan diam.
            if not art_path:
                self.write_log("SYS: Belum ada hasil terbaru untuk dibuka.")
                self._speak_line(
                    "Belum ada hasil terbaru yang bisa saya buka, sir.")
                return

        task = conversation_context.STORE.augment(conversation_id, task)
        self._record_task_result("TUGAS", task)
        self.orb.set_state(OrbState.EXECUTING)

        def _on_ack(_raw: str, report: str):
            delivery_lifecycle.acknowledged("typed", report)
            self._speak_line(report)

        def _on_done(result: str, report: str):
            delivery = delivery_lifecycle.success(
                result, task, source="typed", naturalize=True
            )
            conversation_context.STORE.remember_success(
                conversation_id, task=task, delivery=delivery
            )
            short = delivery.display_text[:600]
            self._record_task_result("HASIL", delivery.display_text)
            self.write_log(f"Agent: {short}")
            self._content_sig.emit("AGENT — hasil tugas", delivery.display_text)
            self._speak_line(delivery.speech_text)
            self._restore_orb()

        def _on_error(err: str, report: str):
            delivery = delivery_lifecycle.failure(err, task, source="typed")
            self._record_task_result("GAGAL", delivery.display_text)
            self.write_log(f"ERR: agent task — {delivery.display_text[:160]}")
            self._speak_line(delivery.speech_text)
            self._restore_orb()

        started = interactive_dispatch.start(
            task,
            adapter=UIAdapter(self),
            on_ack=_on_ack,
            on_done=_on_done, on_error=_on_error)
        if started:
            self.write_log(f"SYS: Agent mengerjakan — {task[:90]} …")
        else:
            self.write_log(
                "SYS: Agent belum siap (provider belum dikonfigurasi) atau "
                "tugas serupa masih berjalan."
            )

    def _open_artifact(self, path: str, kind: str = "file") -> bool:
        """Buka artefak terakhir (gambar/file) secara lokal. Return False bila
        file hilang sehingga caller bisa jujur ke user."""
        import os
        clean = str(path or "").strip()
        if not clean or not os.path.exists(clean):
            self.write_log(f"SYS: File tidak ditemukan lagi — {clean}")
            self._speak_line("Berkasnya sudah tidak ada, sir.")
            return False
        name = os.path.basename(clean)
        if kind == "image" and callable(getattr(self, "show_image", None)):
            try:
                self.show_image(clean, f"Ini {name}, sir.")
            except Exception:                                # noqa: BLE001
                pass
        try:
            if os.name == "nt":
                os.startfile(clean)                          # noqa: S606
            else:
                import subprocess
                opener = "open" if sys.platform == "darwin" else "xdg-open"
                subprocess.Popen([opener, clean])
        except Exception as exc:                             # noqa: BLE001
            self.write_log(f"ERR: gagal membuka {name} — {type(exc).__name__}")
            self._speak_line(f"Maaf sir, saya gagal membuka {name}.")
            return False
        self.write_log(f"SYS: Membuka {name} …")
        self._speak_line(f"Ini {name} yang tadi saya buat, sir.")
        return True

    def show_image(self, path: str, caption: str = "") -> None:
        """Tampilkan gambar di ContentStage (dipakai UIAdapter.send_image).
        Best-effort: bila stage tidak mendukung, hanya catat path di log."""
        clean = str(path or "").strip()
        emitter = getattr(self, "_content_sig", None)
        stage = getattr(self, "stage", None)
        shown = False
        if stage is not None and hasattr(stage, "show_image"):
            try:
                stage.show_image(clean, caption)
                shown = True
            except Exception:                                # noqa: BLE001
                shown = False
        if not shown and emitter is not None:
            try:
                emitter.emit("AGENT — gambar", f"{caption}\n{clean}".strip())
                shown = True
            except Exception:                                # noqa: BLE001
                shown = False
        if not shown:
            self.write_log(f"SYS: gambar tersimpan — {clean} {caption}".rstrip())

    def _run_calorie_analysis(self, question: str = "") -> None:
        """MK50 — analisis kalori makanan dari frame kamera live; hasil
        muncul sebagai pop-up DI DALAM frame kamera (CalorieOverlay) plus
        satu kalimat suara. Kamera dibuka otomatis bila belum."""
        if self.vision is None:
            self.write_log("ERR: subsistem vision tidak tersedia.")
            self._speak_line("Subsistem kamera tidak tersedia, sir.")
            return
        self._set_vision_visible(True)
        self.orb.set_state(OrbState.EXECUTING)
        self.write_log("SYS: Menganalisis kalori makanan di kamera …")
        BUS.publish("vision.calories", state="analyzing",
                    message="Menganalisis makanan…")

        def _work():
            try:
                jpeg = self.vision.latest_frame_jpeg(timeout=6.0)
                if not jpeg:
                    BUS.publish("vision.calories", state="error",
                                message="Kamera belum siap — coba lagi.")
                    self._speak_line("Kamera belum siap, sir.")
                    return
                from jarvis.vision import food_calories
                analysis = food_calories.analyze_jpeg(jpeg, question)
                if analysis.error:
                    BUS.publish("vision.calories", state="error",
                                message=analysis.error)
                else:
                    BUS.publish("vision.calories", state="result",
                                analysis=analysis)
                    self.write_log("Jarvis: " + analysis.summary_line())
                self._speak_line(analysis.summary_line())
            except Exception as e:
                _logger.error("calorie.failed", error=str(e)[:150])
                BUS.publish("vision.calories", state="error",
                            message=str(e)[:120])
            finally:
                self._restore_orb()

        threading.Thread(target=_work, daemon=True,
                         name="calorie-analysis").start()

    def _chat(self, text: str) -> None:
        # live voice pipeline first (it answers with TTS); NLP fallback
        if self.on_text_command is not None:
            threading.Thread(target=self.on_text_command, args=(text,),
                             daemon=True).start()
            return
        if self.assistant is None:
            self.write_log("ERR: tidak ada kanal percakapan yang aktif.")
            return
        self.orb.set_state(OrbState.THINKING)

        def _run():
            resp = self.assistant.handle_blocking(text)
            self.write_log(f"Jarvis: {resp.text}")
            if resp.show_on_stage:
                self._content_sig.emit(resp.source, resp.text)
            self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="nlp-chat").start()

    def _restore_orb(self) -> None:
        state = _LEGACY_STATE_MAP.get(self._legacy_state, OrbState.IDLE)
        if state in (OrbState.EXECUTING, OrbState.THINKING):
            state = OrbState.IDLE
        self._state_sig.emit(state.value)

    # ── search summary plumbing ──────────────────────────────────────────────

    def _on_page_content(self, text: str, url: str) -> None:
        if self._pending_query is None:
            return
        query, self._pending_query = self._pending_query, None
        BUS.publish("info.card", kind="search", title=query,
                    lines=[text[:1600]], source=url, ts="")
        self._restore_orb()

    def _on_intent_event(self, d: dict) -> None:
        # OnlineSearch (NLP path) publishes SEARCH_WEB with prepared meta
        if d.get("intent") == "SEARCH_WEB" and d.get("meta", {}).get("url") \
                and self._pending_query is None and d.get("meta", {}).get("query"):
            if self.stage.current != "browser":
                self.run_search(d["meta"]["query"])

    # ── redesign P1/P2: palette, timeline, focus mode, awareness, resolver ──

    def _build_palette_model(self) -> CommandPaletteModel:
        model = CommandPaletteModel()
        model.set_commands([
            {"label": "Go home", "action_id": "go_home"},
            {"label": "Toggle mute", "action_id": "toggle_mute"},
            {"label": "Toggle vision panel", "action_id": "toggle_vision_panel"},
            {"label": "Toggle gesture control", "action_id": "toggle_gesture_arm"},
            {"label": "Toggle Focus Mode", "action_id": "toggle_focus_mode"},
            {"label": "Toggle screen awareness", "action_id": "toggle_awareness"},
            {"label": "Open context timeline", "action_id": "open_timeline"},
            {"label": "Reopen last closed tab", "action_id": "reopen_last_tab"},
            {"label": "Open system browser", "action_id": "open_browser_agent"},
            {"label": "Manage monitor sources", "action_id": "manage_monitor_sources"},
        ])
        model.set_sites(dict(self.router._known_sites))
        try:
            from jarvis.core.router import _APP_HINTS
            model.set_apps(sorted(_APP_HINTS))
        except ImportError:
            pass
        try:
            model.set_recent(self.memory.get_recent_episodes(limit=15))
        except Exception:
            pass
        try:
            model.set_macros(self.memory.list_macros(approved_only=True))
        except Exception:
            pass
        return model

    _PALETTE_COMMANDS = {
        "go_home": lambda self: self.go_home(),
        "toggle_mute": lambda self: self.toggle_mute(),
        "toggle_vision_panel": lambda self: self.toggle_vision_panel(),
        "toggle_gesture_arm": lambda self: self.toggle_gesture_arm(),
        "toggle_focus_mode": lambda self: self._toggle_focus_mode(),
        "toggle_awareness": lambda self: self._toggle_awareness(),
        "open_timeline": lambda self: self._toggle_timeline(),
        "reopen_last_tab": lambda self: self._reopen_last_tab(),
        "open_browser_agent": lambda self: self.open_browser_agent(),
        "manage_monitor_sources": lambda self: self._open_monitor_source_sheet(),
    }

    def _on_palette_activated(self, cand) -> None:
        if cand.kind == "command" and cand.action_id in self._PALETTE_COMMANDS:
            self._PALETTE_COMMANDS[cand.action_id](self)
        elif cand.kind == "app":
            self.open_app(cand.action_id)
        elif cand.kind == "site":
            self.open_url(cand.action_id)
        elif cand.kind == "macro":
            steps = cand.meta.get("steps", [])
            self.write_log(f"SYS: macro '{cand.label}' — {len(steps)} step(s) tersimpan. "
                           f"Eksekusi macro belum diaktifkan tanpa konfirmasi eksplisit lebih lanjut.")
        elif cand.kind == "recent":
            self.write_log(f"SYS: dari riwayat — {cand.label}")

    def _open_monitor_source_sheet(self) -> None:
        self.monitor_source_sheet.open_centered(
            self.centralWidget().width(), self.centralWidget().height())

    def _toggle_command_palette(self) -> None:
        if self.command_palette.isVisible():
            self.command_palette.hide()
            return
        self.command_palette.model = self._build_palette_model()
        c = self.centralWidget()
        self.command_palette.open_centered(c.width(), c.height())

    def _toggle_timeline(self) -> None:
        if self.timeline.isVisible():
            self.timeline.hide()
            return
        c = self.centralWidget()
        self.timeline.open_centered(c.width(), c.height())

    def _toggle_focus_mode(self) -> None:
        duration = float(config.get("live_comments.focus_mode.default_duration_s", 1800))
        active = self._focus_mode.toggle(duration_s=duration)
        self.action_panel.set_indicator("focus_mode", active)
        self.action_panel.set_button_state(
            "focus_mode", "Focus Mode — AKTIF (klik untuk nonaktif)"
            if active else "Focus Mode — pause comment narration")
        self.write_log(f"SYS: Focus Mode {'AKTIF' if active else 'nonaktif'}.")
        # Push the confirmation blip BEFORE arming notification suppression,
        # otherwise turning Focus Mode on would swallow its own confirmation and
        # the icon would look unresponsive.
        self.notifications.push("Focus Mode", "AKTIF" if active else "nonaktif", "info")
        self.notifications.set_focus_mode(active)

    def _toggle_awareness(self) -> None:
        # Clicking the icon is itself an explicit opt-in, so it always starts
        # awareness — the ``awareness.enabled`` config flag only governs
        # boot-time auto-start (no capture happens without this deliberate act).
        from jarvis.core import screen_awareness
        aw = screen_awareness.get()
        if not aw.running:
            aw.start()
            self.action_panel.set_indicator("awareness", True)
            self.action_panel.set_button_state("awareness", "Screen awareness — ACTIVE (click to pause)")
            self.write_log("SYS: screen awareness AKTIF.")
            self.notifications.push("Awareness", "started", "info")
        elif aw.paused:
            aw.resume()
            self.action_panel.set_indicator("awareness", True)
            self.action_panel.set_button_state("awareness", "Screen awareness — ACTIVE (click to pause)")
            self.write_log("SYS: screen awareness dilanjutkan.")
            self.notifications.push("Awareness", "resumed", "info")
        else:
            aw.pause()
            self.action_panel.set_indicator("awareness", False)
            self.action_panel.set_button_state("awareness", "Screen awareness — PAUSED (click to resume)")
            self.write_log("SYS: screen awareness dijeda.")
            self.notifications.push("Awareness", "paused", "info")

    def _begin_close_target(self, target: str) -> None:
        if not target:
            self.write_log("SYS: sebutkan target yang ingin ditutup.")
            return
        decision = decide_and_close(target, self._target_resolver)
        if decision.status == "executed":
            detail = decision.result.detail if decision.result else "closed"
            self.write_log(f"SYS: {detail} — {target}")
            self.notifications.push("Closed", target, "success")
        elif decision.status == "no_target":
            self.write_log(f"SYS: tidak menemukan jendela untuk '{target}'.")
            self.notifications.push("No target", target, "warning")
        else:
            self._pending_close_decision = decision
            names = ", ".join(c.window.title for c in decision.candidates[:3])
            self.write_log(
                f"SYS: konfirmasi diperlukan untuk menutup '{target}' ({decision.reason}). "
                f"Kandidat: {names or '-'}. Ucapkan/ketik 'confirm' atau gestur jempol untuk "
                f"melanjutkan, 'cancel' atau jempol turun untuk membatalkan.")
            self.notifications.push("Confirm required", decision.reason, "warning")

    def _execute_remote_proposal(self, action: str) -> bool:
        wanted = {"focus_mode_enable": True, "focus_mode_disable": False}.get(action)
        if wanted is not None:
            if self._focus_mode.active != wanted:
                self._toggle_focus_mode()
            return self._focus_mode.active == wanted
        if not str(action).startswith("media_"):
            return False
        try:
            import asyncio
            from jarvis.agent.remote_media_execution import execute_proposal
            from jarvis.agent.tools.browser import BrowserMedia

            result = asyncio.run(execute_proposal(action, runner=BrowserMedia().run))
            return bool(result.get("ok"))
        except Exception:
            return False

    def _on_remote_proposal_pending(self, data: dict) -> None:
        proposal_id = str(data.get("proposal_id") or "")
        actor_id = str(data.get("actor_id") or "")
        session_id = str(data.get("session_id") or "")
        if self._remote_proposal_sheet.present(proposal_id, actor_id=actor_id,
                                               session_id=session_id):
            self.notifications.push("Remote proposal", "Menunggu persetujuan lokal", "warning")

    def _on_voice_proposal_pending(self, data: dict) -> None:
        """Voice may request; only this desktop UI may approve a named action."""
        proposal_id = str(data.get("proposal_id") or "")
        action = str(data.get("action") or "")
        if not proposal_id or action not in {"focus_mode_enable", "focus_mode_disable"}:
            return
        self._pending_voice_proposal_id = proposal_id
        self.write_log("SYS: proposal voice diterima — ketik 'confirm' atau 'cancel'.")
        self.notifications.push("Voice proposal", "Menunggu persetujuan lokal", "warning")

    def _approve_voice_proposal(self) -> bool:
        proposal_id = self._pending_voice_proposal_id
        if not proposal_id:
            return False
        from jarvis.integrations.voice_desktop_proposals import get_queue

        def execute(action: str) -> bool:
            wanted = action == "focus_mode_enable"
            if self._focus_mode.active != wanted:
                self._toggle_focus_mode()
            return self._focus_mode.active == wanted

        self._pending_voice_proposal_id = None
        result = get_queue().approve_local(proposal_id, executor=execute)
        if result.get("executed"):
            self.write_log("SYS: proposal voice disetujui secara lokal.")
            return True
        self.write_log("SYS: proposal voice tidak dapat dijalankan.")
        return True

    # ── countdown native (Phase WA1) ─────────────────────────────────────────
    def start_countdown(self, duration_s: int) -> bool:
        """Mulai countdown native via FACADE lokal (Phase 29); orb progress.

        UI tidak pernah bypass facade — durasi terbatas (1..3600s), murni
        lokal, tanpa remote/network/write.
        """
        from jarvis.ui.countdown_driver import CountdownDriver

        outcome = self._facades.invoke("start_countdown",
                                       duration_s=duration_s)
        if not outcome.get("ok"):
            return False
        timer = outcome["artifacts"]["timer"]
        if self._countdown_ticker is None:
            self._countdown_ticker = QTimer(self)
            self._countdown_ticker.setInterval(200)
            self._countdown_ticker.timeout.connect(self._on_countdown_tick)
        self._countdown = timer
        self._countdown_driver = CountdownDriver(
            timer=timer,
            orb=self.orb,
            set_progress=self.orb.set_progress,
            ticker_start=self._countdown_ticker.start,
            ticker_stop=self._countdown_ticker.stop,
        )
        self._countdown_driver.attach()
        self.write_log(f"Timer {duration_s} dtk berjalan (lokal).")
        return True

    def cancel_countdown(self) -> bool:
        """Batalkan countdown yang berjalan (idempotent)."""
        if self._countdown is None:
            return False
        cancelled = self._countdown.cancel()
        if cancelled:
            self.write_log("Timer dibatalkan.")
        return cancelled

    def _on_countdown_tick(self) -> None:
        if self._countdown_driver is not None:
            self._countdown_driver.tick()

    def _on_confirm(self, _d: dict) -> None:
        if self._approve_voice_proposal():
            return
        if self._pending_close_decision is None:
            return
        decision, self._pending_close_decision = self._pending_close_decision, None
        if not decision.candidates:
            return
        top = decision.candidates[0]
        result_decision = decide_and_close("", self._target_resolver,
                                           confirmed_target=top.window)
        ok = result_decision.status == "executed"
        detail = result_decision.result.detail if result_decision.result else "failed"
        self.write_log(f"SYS: {detail} — {top.window.title}")
        self.notifications.push("Closed" if ok else "Failed", top.window.title,
                                "success" if ok else "error")

    def _on_cancel(self, _d: dict) -> None:
        if self._pending_voice_proposal_id is not None:
            self._pending_voice_proposal_id = None
            self.write_log("SYS: proposal voice dibatalkan secara lokal.")
            return
        if self._pending_close_decision is not None:
            self._pending_close_decision = None
            self.write_log("SYS: aksi dibatalkan.")
            self.notifications.push("Cancelled", "", "info")

    def _reopen_last_tab(self) -> None:
        item = self._closed_items.pop_last("tab")
        if item is None:
            self.write_log("SYS: tidak ada tab yang bisa dibuka kembali.")
            return
        url = item["meta"].get("url", "")
        if url:
            self.open_url(url)

    def _on_sentiment(self, d: dict) -> None:
        self.orb.feed_sentiment(float(d.get("value", 0.0)))

    def _on_remote_setup_pending(self, d: dict) -> None:
        """Tampilkan approval lokal hanya untuk runtime-owned SetupQueue."""
        from jarvis.agent.remote_setup import get_setup_queue

        request_id = str(d.get("request_id", "") or "")
        if not request_id:
            return
        sheet = getattr(self, "remote_setup_sheet", None)
        if sheet is None:
            return
        # The BUS carries only the opaque request id; the queue is the
        # process-local runtime-owned instance, never a caller-supplied object.
        queue = getattr(self, "_setup_queue", None) or get_setup_queue()
        sheet._queue = queue
        if not sheet.present(request_id):
            return
        c = self.centralWidget()
        if c is not None:
            w, h = min(520, c.width()), min(320, c.height())
            sheet.setGeometry((c.width() - w) // 2, (c.height() - h) // 2, w, h)
        sheet.raise_()
    def open_browser_agent(self, slots: dict | None = None) -> None:
        """MK50 §7 — panel browser dibuang dari ContentStage: perintah
        "buka browser" membuka browser sistem. Alur web bertujuan (multi-
        langkah) ditangani agent lewat browser_* tools (Playwright)."""
        slots = slots or {}
        from jarvis.core.native_actions import open_external_url

        url = slots.get("url") or str(config.get(
            "router.known_sites.google", "https://www.google.com"))
        result = open_external_url(url)
        if result.ok:
            self.write_log("SYS: dibuka di browser sistem (panel browser "
                           "sudah dipensiunkan, MK50 §7).")
        else:
            self.write_log(
                f"ERR: browser sistem gagal dibuka — {result.detail}")

    def _window_control_registry(self):
        if self.window_controls is None:
            from jarvis.core.window_controls import WindowControlRegistry
            self.window_controls = WindowControlRegistry(
                own_window=self, resolver=self._target_resolver)
        return self.window_controls

    # ── vision integration ───────────────────────────────────────────────────

    def toggle_vision_panel(self) -> None:
        """Klik ikon vision yang sama menutup, termasuk selama LOADING."""
        visible = not (self.stage.current == "vision"
                       or self.stage.is_loading("vision"))
        self._set_vision_visible(visible)

    def _set_vision_visible(self, visible: bool) -> None:
        if visible:
            if self.vision is not None and not self.vision.alive:
                self.vision.start()
            self.stage.begin_loading("vision")
            self._sync_orb_visibility()          # orb hides the moment camera opens
            if self.vision_panel.has_payload:
                self.stage.activate("vision")
        elif self.stage.current == "vision" or self.stage.is_loading("vision"):
            self._close_stage_panels()
            self._sync_orb_visibility()          # camera gone → orb reappears
            self._restore_orb()
            self.orb.undock()
            # Fully release the physical camera on close (LED off) — but keep
            # the worker alive while gesture control is armed (it needs the feed).
            if self.vision is not None and self.vision.alive and not self.vision.armed:
                threading.Thread(target=self.vision.stop, daemon=True,
                                 name="vision-stop").start()

    def toggle_gesture_arm(self) -> None:
        self.set_gesture_armed(not (self.vision.armed if self.vision else False))

    def set_gesture_armed(self, armed: bool) -> None:
        if self.vision is None:
            self.write_log("ERR: subsistem vision tidak tersedia.")
            return
        if armed:
            if not self.vision.alive:
                self.vision.start()
            self.vision.arm()
            self.stage.begin_loading("vision")
            if self.vision_panel.has_payload:
                self.stage.activate("vision")
            self.write_log("SYS: Kontrol gestur DIAKTIFKAN — telapak terbuka "
                           "3 detik untuk berhenti darurat.")
        else:
            self.vision.disarm()
            self.write_log("SYS: Kontrol gestur dinonaktifkan.")

    def _on_gesture(self, d: dict) -> None:
        g = d.get("gesture", "")
        if g == "PEACE_V":
            self.toggle_mute()
        elif g == "SPREAD_TO_FIST":
            self._do_interrupt()
        elif g in ("THUMBS_UP", "THUMBS_DOWN"):
            BUS.publish("confirm" if g == "THUMBS_UP" else "cancel")

    def _on_vision_status(self, d: dict) -> None:
        if not d.get("alive", True):
            self.write_log(f"SYS: vision — {d.get('detail', 'offline')}")
            self.notifications.push("Vision", d.get("detail", "offline"), "warning")

    # ── boot / notifications / logging ───────────────────────────────────────

    def _on_boot_check(self, d: dict) -> None:
        mark = "✓" if d["ok"] else "✗"
        if d.get("degraded"):
            mark = "~"
        self.orb.set_status_word(f"{d['subsystem']} {mark}")
        self.write_log(f"SYS: [{mark}] {d['subsystem']} — {d.get('detail','')}")
        if not d["ok"]:
            self.notifications.push(d["subsystem"], d.get("detail", ""),
                                    "warning" if d.get("degraded") else "error")

    def _on_notify(self, d: dict) -> None:
        self.write_log(f"SYS: ◈ {d.get('title','')}: {d.get('body','')[:120]}")
        self.notifications.push(d.get("title", ""), d.get("body", ""), "info")

    def _on_bus_log(self, d: dict) -> None:
        msg = d.get("message", "")
        src = d.get("source", "")
        self.activity.add_line(d.get("level", "INFO"), f"[{src}] {msg}")

    def _record_task_result(self, kind: str, text: str) -> None:
        """Tambahkan ringkasan task ke drawer F1; aman dari worker thread."""
        drawer = getattr(self, "task_results", None)
        if drawer is not None:
            drawer.add_entry(kind, text)

    def _append_log(self, text: str) -> None:
        level = "INFO"
        tl = text.lower()
        if tl.startswith("you:"):
            level = "USER"
        elif tl.startswith("jarvis:"):
            level = "AI"
        elif "err" in tl[:6]:
            level = "ERROR"
        self.activity.add_line(level, text)
        # Hanya informasi task yang bermakna bagi user masuk drawer F1.
        # Activity Log F2 tetap menyimpan jejak teknis penuh.
        if tl.startswith("jarvis:"):
            self._record_task_result("AGENT", text[7:].strip())
        elif tl.startswith("sys:") and ("mengerjakan" in tl or "🔧" in text):
            self._record_task_result("PROSES", text[4:].strip())
        ACTIVITY_LOG.add(text)
        # voice path: the Live model handles chat itself; intercept only the
        # UI-local intents (vision, home, reply, gesture, known sites)
        if level == "USER":
            if self._skip_next_intercept:
                self._skip_next_intercept = False
            else:
                self._voice_intercept(text[4:].strip())

    _VOICE_ACTIONS = ("vision_open", "vision_close", "home", "reply",
                      "gesture_arm", "gesture_disarm",
                      "calorie_analyze")           # MK50 — kalori via suara

    def _voice_intercept(self, spoken: str) -> None:
        """Voice transcript routing. Browser intents (URL, search, browser
        open, tab controls) take the SAME canonical path as typed commands —
        browser sistem untuk aksi ringan — sehingga voice dan keyboard tidak
        divergen. Free-form conversation tetap ke live assistant."""
        if not spoken:
            return
        if self.reply_flow.handle_utterance(spoken):
            return
        # Fase 15 — jawaban konfirmasi lewat suara. Kanal baru, gerbang lama:
        # ucapan tegas menerbitkan event BUS yang sama persis dengan kata yang
        # diketik. ReplyFlow di atas sudah lewat, jadi dua konteks konfirmasi
        # tidak saling mencuri: selama ReplyFlow berstatus CONFIRM, "ya" tetap
        # miliknya.
        if self._handle_spoken_confirmation(spoken):
            return
        route = classify_execution(spoken, {"source": "voice"})
        _logger.info(
            "router.decision",
            source="voice",
            tier=int(route.tier),
            lane=route.lane,
            reason=route.reason,
        )
        if route.tier >= ExecutionTier.AGENT:
            # The root Gemini Live seam owns the actual voice hand-off.  This
            # UI intercept observes the transcript after the fact, so it must
            # only suppress duplicate legacy actions for heavy requests.
            return
        c = self.router.classify(spoken)
        if c.intent is Intent.SYSTEM and c.slots.get("action") in self._VOICE_ACTIONS:
            self.run_system(c.slots, spoken)
        elif c.intent is Intent.OPEN_BROWSER_AGENT:
            self.open_browser_agent(c.slots)
        elif c.intent is Intent.OPEN_URL:
            self.open_url(c.slots.get("url", ""))
        elif c.intent is Intent.SEARCH_WEB:
            self.run_search(c.slots.get("query", spoken))

    def _handle_spoken_confirmation(self, spoken: str) -> bool:
        """Terbitkan confirm/cancel bila ucapan ini menjawab pertanyaan aktif.

        Hanya berlaku SELAMA ada pertanyaan yang menunggu. Di luar jendela itu
        "ya" tetap percakapan biasa — kata setuju tidak boleh melayang lalu
        menyetujui aksi yang belum pernah ditanyakan.
        """
        pending = (self._pending_close_decision is not None
                   or self._pending_voice_proposal_id is not None
                   or _agent_ask_active())
        if not pending:
            return False
        try:
            from jarvis.agent import voice_consent
            decision = voice_consent.decide(spoken)
        except Exception as exc:                             # noqa: BLE001
            _logger.warning("voice.consent_unavailable", error=str(exc)[:100])
            return False
        if decision is None:
            return False
        BUS.publish(decision)
        self.write_log(
            f"SYS: konfirmasi suara — {'disetujui' if decision == 'confirm' else 'dibatalkan'}.")
        return True

    def _speak_line(self, line: str) -> None:
        """Say one exact sentence via the live voice; log regardless."""
        self.write_log(f"Jarvis: {line}")
        if self.on_text_command is not None:
            msg = ("Ucapkan kalimat berikut PERSIS seperti tertulis, tanpa "
                   "tambahan: «" + line + "»")
            threading.Thread(target=self.on_text_command, args=(msg,),
                             daemon=True).start()

    def _show_content(self, title: str, text: str) -> None:
        if self.info_panel is None:
            self.write_log(f"ERR: panel info tidak tersedia — {title}")
            return
        lines = [line for line in text.splitlines() if line.strip()]
        self.info_panel.add_card("result", title, lines or [text],
                                 source="Jarvis", ts="")
        self.stage.show_child("info")
        self._schedule_info_recenter()

    def _schedule_info_recenter(self) -> None:
        """Setelah kartu INFO tampil, kembalikan orb ke tengah sesudah jeda —
        kartu tetap terlihat di panel, hanya orb yang un-dock. Hanya berlaku
        untuk stage 'info' agar konten yang dibaca (vision/browser) tak direbut.
        """
        delay = int(config.get("ui.info_panel.orb_recenter_ms", 4000))
        if delay <= 0:
            return
        if self._info_recenter_tmr is None:
            self._info_recenter_tmr = QTimer(self)
            self._info_recenter_tmr.setSingleShot(True)
            self._info_recenter_tmr.timeout.connect(self._recenter_orb_for_info)
        self._info_recenter_tmr.start(delay)

    def _recenter_orb_for_info(self) -> None:
        """Orb pulang ke tengah bila stage masih menampilkan kartu INFO dan
        pipeline sedang tenang (bukan SPEAKING/EXECUTING)."""
        if self.stage.current != "info":
            return
        if self._legacy_state in ("SPEAKING", "EXECUTING"):
            # jangan ganggu layout saat masih bicara/mengerjakan; coba lagi.
            self._schedule_info_recenter()
            return
        self.orb.undock()

    # ── legacy facade internals ──────────────────────────────────────────────

    def _apply_state(self, state: str) -> None:
        if state == "SPEAKING" and self._legacy_state != "SPEAKING":
            self._speaking_since = time.monotonic()   # barge-in grace anchor
        self._legacy_state = state
        orb_state = _LEGACY_STATE_MAP.get(state, OrbState.IDLE)
        self.orb.set_state(orb_state)
        self._dot.set_state(orb_state)
        if state == "SPEAKING":
            self.orb.set_presentation(PresentationMode.DOCKED_CONTENT_STAGE
                                      if self.stage.status is ContentStatus.ACTIVE
                                      else PresentationMode.FULL_EMPTY_STAGE)
        if state == "MUTED":
            self.orb.set_status_word("MUTED")
        elif orb_state not in (OrbState.SPEAKING, OrbState.EXECUTING):
            # stay docked while the stage is showing content — the orb must
            # not jump back over the page the user is reading
            if self.stage.current is None:
                self.orb.undock()
            else:
                self.orb.dock(Corner.BOTTOM_RIGHT)
    def toggle_mute(self) -> None:
        self._muted = not self._muted
        self.notifications.set_muted(self._muted)
        if self._muted:
            self._apply_state("MUTED")
            self.write_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self.write_log("SYS: Microphone active.")

    def _toggle_fullscreen(self) -> None:
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _do_interrupt(self) -> None:
        """ESC. Interupsi suara adalah do-not-regress dan SELALU menang.

        Hanya bila Jarvis benar-benar tidak sedang bicara DAN ada panel
        terbuka, ESC berarti "kembali". Urutan ini tidak boleh dibalik:
        memotong ucapan adalah alasan utama tombol ini ada.
        """
        speaking = self._legacy_state in ("SPEAKING", "TRANSCRIBING")
        if not speaking and self.stage.current:
            # ESC adalah close panel, bukan navigasi mundur tersembunyi. Riwayat
            # dibersihkan bersama toggle agar klik/ESC setelah panel switch tidak
            # mendarat pada panel lama secara membingungkan.
            self._close_stage_panels()
            return
        if self.on_interrupt:
            self.on_interrupt()

    def _on_file(self, path: str) -> None:
        self._current_file = path
        if self.assistant is not None:
            self.assistant.ctx.uploaded_file = path
        self.write_log(f"FILE: {path}")
        
        import os
        ext = os.path.splitext(path)[1].lower()
        if ext in {'.pdf', '.docx', '.doc', '.txt', '.md', '.csv'}:
            self._handle_document_upload(path)
        elif ext in {'.png', '.jpg', '.jpeg', '.webp'}:
            self._handle_image_upload(path)
        else:
            if self.on_text_command:
                msg = (f"[FILE_UPLOADED] path={path} | Briefly tell the user you "
                       f"can see the file and ask what to do with it.")
                threading.Thread(target=self.on_text_command, args=(msg,),
                                 daemon=True).start()

    def _handle_document_upload(self, path: str) -> None:
        """Upload → Extracting → Summarizing → Complete/Failed, with explicit
        status on the stage and a spoken outcome for every path (no silence)."""
        self.orb.set_state(OrbState.THINKING)
        import os
        name = os.path.basename(path)

        def _run():
            try:
                self._content_sig.emit(f"Dokumen: {name}",
                                       "⏳ Membaca dan mengekstrak teks…")
                from jarvis.nlp.document import read_document_ex
                text, err = read_document_ex(path)
                if err:
                    self._content_sig.emit(f"Dokumen: {name} — GAGAL", err)
                    self._speak_line(f"Maaf, {err}")
                    return
                self._content_sig.emit(f"Dokumen: {name}",
                                       "⏳ Teks terbaca — membuat ringkasan…")
                from jarvis.core import llm
                from jarvis.nlp.doc_extract import summarize_long
                summary = summarize_long(text, llm.generate)
                if not summary:
                    # extraction OK, LLM failed — say so, never go silent
                    preview = text[:600] + ("…" if len(text) > 600 else "")
                    self._content_sig.emit(
                        f"Dokumen: {name} — ringkasan gagal",
                        "Teks berhasil dibaca, tetapi layanan ringkasan "
                        "sedang bermasalah.\n\nCuplikan awal:\n" + preview)
                    self._speak_line(
                        "Dokumen berhasil saya baca, tetapi layanan ringkasan "
                        "sedang bermasalah. Silakan coba lagi.")
                    return
                self._content_sig.emit(f"Dokumen: {name}", summary)
                self._speak_line(
                    f"Berikut adalah ringkasan dari dokumen {name}: {summary}")
            except Exception as e:
                self.write_log(f"ERR: document upload — {str(e)[:80]}")
                self._content_sig.emit(f"Dokumen: {name} — GAGAL",
                                       "Terjadi kesalahan internal saat "
                                       "memproses dokumen.")
                self._speak_line("Maaf, terjadi kesalahan saat memproses "
                                 "dokumen ini.")
            finally:
                self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="doc-upload").start()

    def _handle_image_upload(self, path: str) -> None:
        self.orb.set_state(OrbState.THINKING)
        import os
        from pathlib import Path
        img_url = Path(path).as_uri()
        html = f'<img src="{img_url}" width="400" />'
        self._content_sig.emit(f"Gambar: {os.path.basename(path)}", html)
        
        def _run():
            try:
                from jarvis.core import llm
                from google import genai
                from google.genai import types
                client_key = llm.api_key()
                if not client_key:
                    self._speak_line("API key belum dikonfigurasi untuk melihat gambar.")
                    return
                client = genai.Client(api_key=client_key)
                with open(path, "rb") as f:
                    image_bytes = f.read()
                ext = os.path.splitext(path)[1].lower()
                mime = f"image/{ext[1:]}" if ext != '.jpg' else "image/jpeg"
                response = client.models.generate_content(
                    model='gemini-3.5-flash',
                    contents=[
                        types.Part.from_bytes(data=image_bytes, mime_type=mime),
                        "Deskripsikan gambar ini dengan singkat dalam Bahasa Indonesia (maksimal 2 kalimat)."
                    ]
                )
                desc = response.text or "Gambar telah dimuat."
                self._speak_line(desc)
            except Exception as e:
                self.write_log(f"ERR: image upload — {str(e)[:80]}")
            finally:
                self._restore_orb()
        threading.Thread(target=_run, daemon=True, name="img-upload").start()

    def write_log(self, text: str) -> None:
        self._log_sig.emit(text)

    # ── API key sheet ────────────────────────────────────────────────────────

    def _check_config(self) -> bool:
        try:
            from jarvis.core import llm
            return bool(llm.api_key())
        except Exception:
            return False

    def _center_sheet(self) -> None:
        if self._api_sheet is None:
            return
        c = self.centralWidget()
        w, h = 480, 240
        self._api_sheet.setGeometry((c.width() - w) // 2,
                                    (c.height() - h) // 2, w, h)

    def _show_api_sheet(self) -> None:
        if self._api_sheet is None:
            self._api_sheet = ApiKeySheet(self.centralWidget())
            self._api_sheet.done.connect(self._on_api_key)
        self._center_sheet()
        self._api_sheet.show()
        self._api_sheet.raise_()

    def _on_api_key(self, key: str) -> None:
        from jarvis.core import llm, secrets_store
        if not secrets_store.set("jarvis/llm/gemini", key):
            self.write_log("ERR: API key gagal disimpan terenkripsi.")
            return
        llm.reset_client()
        self._ready = True
        if self._api_sheet:
            self._api_sheet.hide()
        self.write_log("SYS: API key tersimpan — sistem online.")


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


class JarvisUI:
    """Drop-in facade for the legacy ``main.JarvisLive`` pipeline (Mark XLIX).

    Exposes the exact surface the Gemini Live audio pipeline drives, mapped
    onto the new window: set_state → orb state machine, write_log → activity
    drawer, show_content → ContentStage, camera stream → vision process panel.
    """

    def __init__(self, face_path: str = "", size=None,
                 services: dict | None = None):
        import sys as _sys
        # QtWebEngine/Chromium parses QApplication's argv — an empty list
        # (no argv[0]) makes the render-process launch fastfail (0xC0000409).
        self._app = QApplication.instance() or QApplication(_sys.argv or ["jarvis"])
        self._app.setStyle("Fusion")
        self._win = MainWindow(services)
        self._win.show()
        self.root = _RootShim(self._app)
        self._mic_meter_stop = threading.Event()
        import os
        if os.environ.get("JARVIS_NO_MIC_METER") != "1":
            threading.Thread(target=self._mic_meter, daemon=True,
                             name="mic-meter").start()

    # amplitude: real mic RMS while LISTENING; synthetic pulse while SPEAKING.
    # Mark L Change 4: while SPEAKING the same stream runs a VAD gate — a
    # sustained loud mic signal (user talking over TTS) triggers the exact
    # ESC interrupt path. Grace window + cooldown keep speaker echo from
    # retriggering (lightweight gate, not full echo cancellation).
    def _mic_meter(self) -> None:
        # §19 — keputusan interupsi pindah ke jarvis/core/barge_in.py:
        # noise floor adaptif, pembeda suara-vs-transien, dan echo guard yang
        # berlaku SEPANJANG ucapan. Gerbang RMS ambang tetap 0.14 yang lama
        # itulah yang membuat barge-in harus dimatikan sejak awal.
        from jarvis.core.barge_in import BargeInAnalyzer, BargeInConfig

        analyzer = BargeInAnalyzer(BargeInConfig.from_config())
        analyzer.start_calibration(time.monotonic())

        try:
            import numpy as np
            import sounddevice as sd

            def cb(indata, frames, t, status):
                now = time.monotonic()
                state = self._win._legacy_state
                rms = float(np.sqrt(np.mean(indata ** 2)))
                speaking = state == "SPEAKING"
                if state == "LISTENING" and not self._win._muted:
                    self._win.orb.feed_amplitude(min(1.0, rms * 12))
                elif speaking:
                    import random
                    self._win.orb.feed_amplitude(random.uniform(0.35, 0.95))

                if self._win._muted:
                    return
                verdict = analyzer.process_block(
                    indata, now, speaking=speaking,
                    speaking_since=getattr(self._win, "_speaking_since", 0.0),
                    # Level playback DIUKUR dari audio yang benar-benar
                    # diputar (voice_playback_level tap). Mengasumsikan volume
                    # penuh membuat ambang begitu tinggi sehingga tidak ada
                    # yang bisa memotong — barge-in "menyala" tapi mati dalam
                    # praktik. Worst-case 1.0 hanya dipakai bila tap belum
                    # terpasang, karena echo yang tak terukur lebih berbahaya
                    # daripada interupsi yang terlewat.
                    playback_level=_playback_level(self._win),
                )
                if verdict.interrupt:
                    _logger.info("voice.barge_in", rms=round(verdict.rms, 3),
                                 threshold=round(verdict.threshold, 3),
                                 noise_floor=round(verdict.noise_floor, 4))
                    self._win.write_log("SYS: Interupsi suara terdeteksi.")
                    self._win._do_interrupt()

            with sd.InputStream(callback=cb, channels=1, samplerate=16000,
                                blocksize=1024):
                # §22 — penanda "mic meter HIDUP". Tanpa ini, thread yang mati
                # dan barge-in yang tidak pernah memicu sama-sama terlihat
                # sunyi di log, dan sunyi tidak membedakan apa pun.
                _logger.info("mic_meter.started", **analyzer.diagnostics())
                while not self._mic_meter_stop.wait(0.2):
                    pass
        except Exception as e:
            _logger.warning("mic_meter.unavailable", error=str(e)[:100])

    # ── legacy API (verbatim surface) ────────────────────────────────────────

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win.toggle_mute()

    @property
    def current_file(self):
        return self._win._current_file

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def write_log(self, text: str):
        self._win.write_log(text)

    def show_content(self, title: str, text: str):
        self._win._content_sig.emit(title[:64], text[:6000])

    def wait_for_api_key(self, timeout: float | None = None,
                         should_stop=None) -> bool:
        """Tunggu API key sampai BATAS waktu. True bila siap, False bila
        habis waktu atau dibatalkan.

        Bentuk lama menunggu tanpa batas (``while not _ready: sleep(0.1)``)
        pada thread ``jarvis-live`` yang dibuat ``daemon=False``. Bila key
        belum diisi, ``JarvisLive`` tak pernah dibuat sehingga
        ``ui.on_text_command`` tak pernah ter-bind — gejalanya sama persis
        dengan boot-diam 2026-08-04 walau penyebabnya berbeda — dan proses
        tidak bisa keluar bersih.
        """
        if timeout is None:
            try:
                timeout = float(config.get("voice.api_key_wait_timeout_s", 300))
            except (TypeError, ValueError):
                timeout = 300.0
        deadline = time.monotonic() + max(0.0, float(timeout))
        while not self._win._ready:
            if should_stop is not None and should_stop():
                _logger.info("voice.api_key_wait_cancelled")
                return False
            if time.monotonic() >= deadline:
                _logger.warning("voice.api_key_wait_timeout",
                                timeout_s=round(float(timeout), 1))
                return False
            time.sleep(0.1)
        return True

    def prompt_reconfig(self):
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def notify_phone_connected(self):
        self.write_log("SYS: Phone connected via Remote Dashboard.")

    def show_camera_frame(self, img_bytes: bytes):
        BUS.publish("vision.frame", jpeg=img_bytes)
        self._win._vision_sig.emit(True)

    def start_camera_stream(self):
        if self._win.vision is not None and not self._win.vision.alive:
            self._win.vision.start()
        self._win._vision_sig.emit(True)

    def stop_camera_stream(self):
        self._win._vision_sig.emit(False)

    def get_camera_snapshot(self, timeout: float = 2.5):
        """Newest clean frame from the running vision worker (single camera
        owner) — so JARVIS never opens a second camera handle."""
        v = self._win.vision
        if v is None:
            return None
        if not v.alive:
            v.start()
        self._win._vision_sig.emit(True)          # show the panel while looking
        return v.latest_frame_jpeg(timeout)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def queue_greeting(self, greeting: str):
        """Legacy-compatible no-op; Mark XLIX never creates a boot briefing."""
        _logger.info("boot.greeting_ignored", chars=len(greeting))
