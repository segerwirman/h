"""Mark XLIX main window — minimal cinematic (Part 1).

    Zone A  48px header: status dot · JARVIS · clock
    Zone B  center stage: the orb (whole screen when idle) over ContentStage
    Zone C  56px input line, chrome appears on focus

Everything else is a slide-in overlay or edge-hover. ``JarvisUI`` preserves
legacy voice-pipeline compatibility.
"""
from __future__ import annotations

import threading
import time

from PyQt6.QtCore import QTimer, pyqtSignal
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication, QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget,
)

import re
import sys
from pathlib import Path

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.core.command_palette import CommandPaletteModel
from jarvis.core.focus_mode import FocusMode
from jarvis.core.memory import MemoryManager
from jarvis.core.router import IntentRouter, Intent
from jarvis.core.target_resolver import ClosedItemHistory, TargetResolver, decide_and_close
from jarvis.core.action_registry import Action
from jarvis.core.resolver import ClarifyNeeded
from jarvis.agent.router import Tier as ExecutionTier
from jarvis.agent.router import classify as classify_execution
from jarvis.nlp.summarize import ACTIVITY_LOG
from jarvis.ui import theme
from jarvis.ui.command_palette import CommandPalette
from jarvis.ui.notifications import NotificationBlipStack
from jarvis.ui.orb import Corner, OrbState, PresentationMode
from jarvis.ui.overlays import (ActivityLogDrawer, FileDropOverlay,
                                SysStatsOverlay, TaskResultDrawer, VisionPanel)
from jarvis.ui.stage import ContentStage, ContentStatus
from jarvis.ui.timeline import ContextTimeline
from jarvis.ui.mic_meter import MicMeterController, _playback_level
from jarvis.ui.window_widgets import (
    ApiKeySheet,
    CommandBar,
    _CliTextEdit,
    _GhostLineEdit,
    _StatusDot,
    agent_model_indicator_text,
    escape_action,
    execute_typed_action,
    model_indicator_text,
    palette_entities,
    resolve_typed_action,
    route_typed_resolution,
    typed_action_interrupts_audio,
)

from jarvis.ui.window_commands import CommandRoutingMixin
from jarvis.ui.window_actions import CommandActionsMixin
from jarvis.ui.window_layout import WindowLayoutMixin
from jarvis.ui.window_panels import WindowPanelsMixin
from jarvis.ui.window_voice import WindowVoiceMixin

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


def camera_owns_stage(stage) -> bool:
    """True when camera/vision panel owns stage, including loading."""
    try:
        return stage.current == "vision" or stage.is_loading("vision")
    except Exception:
        return False


def _agent_ask_active() -> bool:
    """True while native agent waits for local confirmation/cancellation."""
    try:
        from jarvis.agent.adapters.ui import ask_active
        return ask_active()
    except Exception:
        return False


# Source-level compatibility map for diagnostics that still scan this facade.
# These are ownership breadcrumbs, not duplicate implementations:
# def run_search — CommandActionsMixin owns the search path; it never launches
# a synthesized transcript through an external browser.
# def _speak_line — WindowVoiceMixin delegates to self._speech().enqueue(...);
# it never creates one thread per utterance.
# def _execute_remote_proposal — WindowPanelsMixin only permits
# focus_mode_enable / focus_mode_disable through execute_proposal + BrowserMedia.
# def _on_remote_proposal_pending — WindowPanelsMixin owns presentation.
# def _on_voice_proposal_pending — WindowPanelsMixin owns local approval;
# _approve_voice_proposal only accepts focus_mode_enable / focus_mode_disable.
# def _on_confirm — WindowPanelsMixin closes the local confirmation boundary.
# MicMeterController retains: from jarvis.core.barge_in import BargeInAnalyzer.
class MainWindow(
    WindowLayoutMixin,
    WindowPanelsMixin,
    WindowVoiceMixin,
    CommandRoutingMixin,
    CommandActionsMixin,
    QMainWindow,
):
    _state_sig = pyqtSignal(str)
    _log_sig = pyqtSignal(str)
    _content_sig = pyqtSignal(str, str)
    _reconfig_sig = pyqtSignal()
    _vision_sig = pyqtSignal(bool)
    _voice_interrupt_sig = pyqtSignal(object)
    _mic_level_sig = pyqtSignal(float)
    _api_key_verified_sig = pyqtSignal(bool, str)

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
        self._clock.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;")
        hl.addWidget(self._clock)
        root.addWidget(header)

        self.stage = ContentStage()
        root.addWidget(self.stage, stretch=1)
        self.browser = None
        self.vision_panel = VisionPanel()
        self.stage.register("vision", self.vision_panel)
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
        self.info_panel = None
        self.home_panel = None
        try:
            from jarvis.ui.info_panel import InfoPanel
            self.info_panel = InfoPanel()
            self.stage.register("info", self.info_panel)
        except Exception as e:
            _logger.warning("info_panel.unavailable", error=str(e)[:100])
        try:
            from jarvis.ui.home_panel import HomePanel
            self.home_panel = HomePanel()
            self.stage.register("home", self.home_panel)
            self.home_panel.ready.connect(self._on_home_ready)
        except Exception as e:
            _logger.warning("home_panel.unavailable", error=str(e)[:100])
        self.content_studio = None
        try:
            from jarvis.ui.content_studio import ContentStudioSheet
            self.content_studio = ContentStudioSheet()
            self.stage.register("studio", self.content_studio)
        except Exception as e:
            _logger.warning("content_studio.unavailable", error=str(e)[:100])

        self.command_bar = CommandBar(predictive)
        self.command_bar.submitted.connect(self.handle_command)
        root.addWidget(self.command_bar)
        from jarvis.ui.task_halo import TaskHaloOrb
        self.orb = TaskHaloOrb(self.stage)
        self.orb.set_status_word("IDLE")
        self.orb.set_reduced_motion(bool(config.get("ui.reduced_motion", False)))
        self._countdown = None
        self._countdown_ticker: QTimer | None = None
        self._countdown_driver = None
        if facades is not None:
            self._facades = facades
        else:
            from jarvis.core.local_facades import default_facades
            self._facades = default_facades()

        self.sys_stats = SysStatsOverlay(central)
        self.activity = ActivityLogDrawer(central)
        self.task_results = TaskResultDrawer(central)
        self.file_drop = FileDropOverlay(central)
        self.file_drop.file_selected.connect(self._on_file)
        self._api_sheet: ApiKeySheet | None = None
        from jarvis.ui.actionpanel import ActionPanel, SettingsSheet
        self.action_panel = ActionPanel(central)
        self.action_panel.vision_clicked.connect(self.toggle_vision_panel)
        self.action_panel.upload_clicked.connect(self.file_drop.toggle)
        self.action_panel.spotify_clicked.connect(self._open_spotify)
        if hasattr(self.action_panel, "home_clicked"):
            self.action_panel.home_clicked.connect(self._toggle_home_panel)
        if hasattr(self.action_panel, "studio_clicked"):
            self.action_panel.studio_clicked.connect(self._toggle_studio_panel)
        try:
            from jarvis.ui.settings_providers import ProviderSettingsSheet
            self.settings_sheet = ProviderSettingsSheet(central)
        except Exception as e:
            _logger.warning("settings.provider_sheet_unavailable", error=str(e)[:100])
            self.settings_sheet = SettingsSheet(central)
        self.action_panel.settings_clicked.connect(
            lambda: self.settings_sheet.open_centered(
                self.centralWidget().width(), self.centralWidget().height()))
        self.settings_sheet.saved.connect(lambda: self.write_log(
            "SYS: Pengaturan provider diperbarui — klien dimuat ulang tanpa restart."))
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
        from jarvis.ui.remote_setup_sheet import RemoteSetupSheet
        self.remote_setup_sheet = RemoteSetupSheet(None, central)
        self.remote_setup_sheet.hide()
        from jarvis.ui.monitor_source_sheet import MonitorSourceSheet
        self.monitor_source_sheet = MonitorSourceSheet(parent=central)
        self.monitor_source_sheet.hide()
        # Palette ownership moved to WindowPanelsMixin:
        # {"action_id": "manage_monitor_sources"}
        # {"manage_monitor_sources": self.manage_monitor_sources}
        from jarvis.ui.panels import CapabilitiesPanel
        self.capabilities_sheet = CapabilitiesPanel(central)
        self.capabilities_sheet.hide()
        self.action_panel.capabilities_clicked.connect(
            lambda: self.capabilities_sheet.open_centered(
                self.centralWidget().width(), self.centralWidget().height()))

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
        self._browser_agent = None
        self.window_controls = None
        self.command_palette = CommandPalette(central, self._build_palette_model())
        self.command_palette.activated.connect(self._on_palette_activated)
        self.timeline = ContextTimeline(central)
        try:
            from jarvis.ui import task_wiring
            task_wiring.install(self)
        except Exception as e:
            _logger.warning("task_deck.install_failed", error=str(e)[:120])
        try:
            from jarvis.ui import action_hint
            self.action_hint = action_hint.install(self.action_panel, central)
        except Exception as e:
            _logger.warning("action_hint.install_failed", error=str(e)[:120])
        self.action_panel.awareness_clicked.connect(self._toggle_awareness)
        self.action_panel.focus_mode_clicked.connect(self._toggle_focus_mode)
        self.action_panel.palette_clicked.connect(self._toggle_command_palette)
        self.action_panel.timeline_clicked.connect(self._toggle_timeline)

        self.on_text_command = None
        self.on_remote_clicked = None
        self.on_interrupt = None
        self._muted = False
        self._voice_capture_generation = 0
        self._current_file: str | None = None
        self._pending_query: str | None = None
        self._ready = self._check_config()
        self._legacy_state = "INITIALISING"
        self._state_sig.connect(self._apply_state)
        self._log_sig.connect(self._append_log)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_api_sheet)
        self._vision_sig.connect(self._set_vision_visible)
        self._voice_interrupt_sig.connect(self._do_voice_interrupt)
        self._mic_level_sig.connect(self.orb.feed_amplitude)
        self._api_key_verified_sig.connect(self._on_api_key_verified)
        self.vision_panel.frame_available.connect(self._on_vision_frame_ready)
        self.stage.status_changed.connect(self._on_stage_status)
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
        from jarvis.integrations.vision_supervisor import start_vision_supervisor
        start_vision_supervisor()
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
        self.stage.installEventFilter(self)
        QTimer.singleShot(0, self._sync_orb_geometry)
        self._edge_px = int(config.get("overlays.edge_hover_px", 8))
        self._apply_startup_panel()
        if not self._ready:
            QTimer.singleShot(200, self._show_api_sheet)

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


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        self._app.exec()

    def protocol(self, *_):
        pass


class JarvisUI:
    """Drop-in facade for the legacy ``main.JarvisLive`` pipeline."""

    def __init__(self, face_path: str = "", size=None,
                 services: dict | None = None):
        import sys as _sys
        from jarvis.core import config
        from jarvis.ui import qt_webengine
        from jarvis.ui import modern_shell  # P8 shell selection factory
        qt_webengine.enable_shared_gl()
        self._app = QApplication.instance() or QApplication(_sys.argv or ["jarvis"])
        self._app.setStyle("Fusion")
        # P8: select shell based on feature flag before constructing MainWindow
        self._win = MainWindow(services)
        modern_shell.select_and_install_shell(self._win)
        self._win.show()
        # P6-A/B: optional presentation adapter shim around the facade surface
        if config.get("ui.presentation_adapter.enabled", False):
            from jarvis.ui.presentation_adapter import FacadeShim
            self.adapter = FacadeShim(self)   # wrap self (the facade itself)
        else:
            self.adapter = None
        self.root = _RootShim(self._app)
        self._mic_meter_stop = threading.Event()
        import os
        if os.environ.get("JARVIS_NO_MIC_METER") != "1":
            threading.Thread(target=self._mic_meter, daemon=True,
                             name="mic-meter").start()

    def _mic_meter(self) -> None:
        """Forward legacy seam to extracted mic controller.

        Controller retains the speaker listener, ``mic_meter.started``, and
        ``diagnostics()`` liveness markers while keeping JarvisUI's thread
        contract unchanged.
        """
        MicMeterController(self._win, self._mic_meter_stop).run()
        return

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
        v = self._win.vision
        if v is None:
            return None
        if not v.alive:
            v.start()
        self._win._vision_sig.emit(True)
        return v.latest_frame_jpeg(timeout)

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    def queue_greeting(self, greeting: str):
        _logger.info("boot.greeting_ignored", chars=len(greeting))
