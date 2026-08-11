"""Geometry, event-filter, and stage layout methods for MainWindow."""
from __future__ import annotations

import time

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QKeySequence, QShortcut

from jarvis.core import config, log
from jarvis.ui.orb import Corner, OrbState, PresentationMode
from jarvis.ui.stage import ContentStatus

_logger = log.get("ui")


def camera_owns_stage(stage) -> bool:
    """True when vision owns stage, including loading transition."""
    try:
        return stage.current == "vision" or stage.is_loading("vision")
    except Exception:
        return False


class WindowLayoutMixin:
    """Own geometry and visual-stage synchronization without owning state."""

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
            c.width(), c.height(), int(config.get("action_panel.above_input_px", 60)))
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
        if self.browser is None or self.browser._view is None or not js.strip():
            callback("no-view")
            return
        self.browser._view.page().runJavaScript(js, callback)

    def _tick_clock(self) -> None:
        self.action_panel.set_dimmed(self.stage.status is ContentStatus.ACTIVE)
        self._clock.setText(time.strftime("%H:%M:%S · %a %d %b"))

    def _on_stage_status(self, _status: str) -> None:
        """The only SPEAKING layout authority is real payload readiness."""
        active = self.stage.status is ContentStatus.ACTIVE
        self.orb.raise_()
        self.action_panel.set_dimmed(active)
        self._sync_action_panel_stage_indicators()
        self._sync_orb_visibility()
        if self._legacy_state == "SPEAKING" and not camera_owns_stage(self.stage):
            self.orb.set_presentation(
                PresentationMode.DOCKED_CONTENT_STAGE if active
                else PresentationMode.FULL_EMPTY_STAGE)

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
