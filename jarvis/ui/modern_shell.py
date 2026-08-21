"""Modern GUI Shell — P8 first visual slice behind feature flag.

First visual slice only per roadmap §12:
- shell geometry
- header/status treatment
- command rail
- stage host
- task summary display
- notification surface

Two compositions live here:

1. ``ModernShellGeometry`` — the standalone modern composition. It is the
   P9 dual-shell host: built against a fresh window, reusing the existing
   ``ContentStage`` / ``CommandBar`` / ``NotificationBlipStack`` /
   ``TaskHaloOrb`` widget CLASSES (no new owner classes). It is never
   installed inside the legacy ``MainWindow``.

2. ``ModernShellInitialization`` — the in-place treatment applied to the
   live legacy ``MainWindow`` when ``ui.shell: modern``. It is deliberately
   NON-destructive:

   - it does not call ``setCentralWidget`` (no second widget tree);
   - it does not construct a second ContentStage, orb, or command bar;
   - it marks the window, applies bounded cosmetic treatment to the
     existing header/clock, and registers the P7 ``IntentController``
     seams so the command rail routes through the SAME owner
     (``MainWindow.handle_command``) as legacy.

Rollback behavior:
- Modern treatment failure logs a bounded diagnostic and falls back to the
  untouched legacy shell (``ui.modern_shell.fallback_to_legacy: true``);
- worker and voice initialization are never repeated;
- no second browser, task, or audio owner is ever created;
- setting ``ui.shell: legacy`` restores legacy operation exactly.

Thread ownership preserved:
- All deliveries use signals/BUS/queue, not shared mutable state;
- BUS UI subscribers run through ``drain_ui(max_events=64)`` on the Qt
  main thread (the legacy MainWindow drain timer is the only drain owner).

Evidence label: focused-tested (offline). Not runtime-wired,
endpoint-reachable, or live-proven until a separately authorized check.
"""
from __future__ import annotations

from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QHBoxLayout, QLabel, QMainWindow, QVBoxLayout, QWidget

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.ui import theme
from jarvis.ui.notifications import NotificationBlipStack
from jarvis.ui.stage import ContentStage, ContentStatus
from jarvis.ui.task_halo import TaskHaloOrb


_logger = log.get("ui.modern_shell")

SHELL_PROPERTY = "jarvis_shell"


class ModernShellGeometry:
    """Standalone modern composition (P9 dual-shell host).

    First visual slice: shell geometry, header/status, command rail,
    stage host, task summary, notification surface. Reuses existing widget
    classes; creates no new owner classes. Pure layout — routing wiring is
    the installer's job, so this can be built against any parent window.
    """

    def __init__(self, parent: QMainWindow):
        self._parent = parent
        self._create_geometry()

    def _create_geometry(self) -> None:
        central = QWidget()
        central.setStyleSheet(f"background: {theme.PAL.base};")
        central.setMouseTracking(True)
        self._parent.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # Header with modern treatment
        self.header = self._create_header(root)

        # Stage host: REUSE ContentStage class (no new stage owner type)
        self.stage_host = ContentStage()
        root.addWidget(self.stage_host, stretch=1)

        # Command rail: REUSE CommandBar class
        from jarvis.ui.window_widgets import CommandBar
        self.command_rail = CommandBar(None)
        root.addWidget(self.command_rail)

        # Task summary strip (display-only; data arrives via BUS task topics)
        self.task_strip = self._create_task_strip(root)

        # Notification surface: REUSE NotificationBlipStack
        self.notification_surface = NotificationBlipStack(central)

        # Orb: REUSE TaskHaloOrb bound to this stage host
        self.orb = TaskHaloOrb(self.stage_host)
        self.orb.set_status_word("IDLE")
        self.orb.set_reduced_motion(bool(config.get("ui.reduced_motion", False)))

    def _create_header(self, layout: QVBoxLayout) -> QWidget:
        header = QWidget()
        header.setFixedHeight(int(config.get("zones.header_height", 48)))
        header.setStyleSheet("background: transparent;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(20, 0, 20, 0)

        from jarvis.ui.window_widgets import _StatusDot
        self.status_dot = _StatusDot()
        hl.addWidget(self.status_dot)

        title = QLabel("JARVIS")
        title.setFont(theme.header_font(14))
        title.setStyleSheet(
            f"color: {theme.PAL.text}; background: transparent;"
            "letter-spacing: 8px; font-weight: 600;"
        )
        hl.addWidget(title)
        hl.addStretch()

        self.clock_label = QLabel("")
        self.clock_label.setFont(theme.mono_font(10))
        self.clock_label.setStyleSheet(
            f"color: {theme.PAL.text_dim}; background: transparent;"
        )
        hl.addWidget(self.clock_label)

        layout.addWidget(header)
        return header

    def _create_task_strip(self, layout: QVBoxLayout) -> QWidget:
        task_strip = QWidget()
        task_strip.setFixedHeight(
            int(config.get("ui.task_deck.mini_strip_height_px", 26)))
        task_strip.setStyleSheet(
            f"background: {theme.PAL.panel}; "
            f"border-top: 1px solid {theme.PAL.accent_dim};"
        )
        tl = QHBoxLayout(task_strip)
        tl.setContentsMargins(10, 0, 10, 0)
        tl.setSpacing(8)

        self.task_label = QLabel("Tugas")
        self.task_label.setFont(theme.mono_font(9))
        self.task_label.setStyleSheet(f"color: {theme.PAL.text_dim};")
        tl.addWidget(self.task_label)

        self.task_placeholder = QLabel("")
        self.task_placeholder.setStyleSheet(f"color: {theme.PAL.secondary};")
        tl.addWidget(self.task_placeholder)
        tl.addStretch()

        layout.addWidget(task_strip)
        return task_strip

    def update_clock(self) -> None:
        import time
        self.clock_label.setText(time.strftime("%H:%M:%S · %a %d %b"))

    def set_stage_status(self, status: ContentStatus) -> None:
        active = self.stage_host.status is ContentStatus.ACTIVE
        self.orb.raise_()
        self.orb.setVisible(status != ContentStatus.ERROR)
        return active

    def show_notification(self, title: str, level: str) -> None:
        try:
            self.notification_surface.post(title, level)
        except Exception as e:  # bounded: notification failure never crashes shell
            _logger.warning("modern_shell.notification_failed", error=str(e)[:120])


class ModernShellInitialization:
    """In-place modern treatment for the live legacy MainWindow.

    NON-destructive by contract: never replaces the central widget, never
    constructs a second stage/orb/command bar. Registers the P7 intent
    controller seams so the command rail keeps delegating to the SAME
    routing owner (MainWindow.handle_command).
    """

    def __init__(self, window: QMainWindow):
        self._window = window
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return

        shell_type = config.get("ui.shell", "legacy")
        if shell_type != "modern":
            _logger.info("shell.select_legacy", shell=str(shell_type))
            return

        try:
            self._install_modern_treatment()
            _logger.info("shell.modern_treatment_installed")
        except Exception as e:
            fallback = config.get("ui.modern_shell.fallback_to_legacy", True)
            if fallback:
                _logger.warning("shell.fallback_to_legacy", error=str(e)[:200])
                self._window.setProperty(SHELL_PROPERTY, "legacy")
            else:
                _logger.error("shell.initialization_fatal", error=str(e)[:200])
                raise

        self._initialized = True

    def _install_modern_treatment(self) -> None:
        win = self._window

        # Marker: exactly one shell is active on this window
        win.setProperty(SHELL_PROPERTY, "modern")

        # Bounded cosmetic treatment of the EXISTING header clock.
        # The legacy title/status dot keep their existing treatment.
        clock = getattr(win, "_clock", None)
        if clock is not None:
            clock.setFont(theme.mono_font(10))

        # P7 bridge: the intent controller delegates to the SAME owners
        # the legacy shell uses — no second router, no second interrupt
        # handler. submit_text → win.handle_command, interrupt → ESC path.
        try:
            from jarvis.ui.intent_controller import get_intent_controller
            controller = get_intent_controller()
            if hasattr(win, "handle_command"):
                controller.register_text_command_callback(win.handle_command)
            if hasattr(win, "_do_interrupt"):
                controller.register_interrupt_callback(win._do_interrupt)
        except Exception as e:
            # Controller seam is additive; its absence never blocks the shell
            _logger.warning("shell.intent_controller_unavailable",
                            error=str(e)[:120])


def select_and_install_shell(window: QMainWindow) -> None:
    """Select legacy or modern shell from the ``ui.shell`` feature flag.

    Legacy (default): no installation — MainWindow keeps its exact behavior.
    Modern: bounded in-place treatment; construction failure falls back to
    legacy per ``ui.modern_shell.fallback_to_legacy``.
    """
    shell_type = config.get("ui.shell", "legacy")

    if shell_type == "modern":
        ModernShellInitialization(window).initialize()
    else:
        _logger.info("shell.default_legacy", shell="legacy")
        window.setProperty(SHELL_PROPERTY, "legacy")
