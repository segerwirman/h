"""Process-local authority owner for semantic Screen Control sessions."""
from __future__ import annotations

import math
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Callable

from jarvis.automation.desktop_service import DESKTOP
from jarvis.automation.selected_tab_session import SELECTED_TABS
from jarvis.core import config, log
from jarvis.core.bus import BUS

_logger = log.get("ui.screen_control")

OFF = "off"
ACTIVE = "active"
HANDING_OFF = "handing_off"
DESKTOP_SURFACE = "desktop"
BROWSER_TAB_SURFACE = "browser_tab"
_MAX_TTL_S = 3600.0


@dataclass(frozen=True)
class ScreenControlSnapshot:
    state: str = OFF
    session_id: str = ""
    task_id: str = ""
    expires_at: float = 0.0
    surface_kind: str = ""
    surface_id: str = ""
    surface_generation: int = 0


class _ThreadScheduler:
    def call_later(self, delay_s: float, callback: Callable[[], None]):
        timer = threading.Timer(delay_s, callback)
        timer.daemon = True
        timer.start()
        return timer


class ScreenControlCoordinator:
    """Own one bounded Screen Control surface and its exact task binding."""

    def __init__(
        self,
        *,
        desktop=DESKTOP,
        selected_tabs=SELECTED_TABS,
        bus=BUS,
        clock=time.monotonic,
        scheduler=None,
        overlay=None,
        selected_tab_scope_check=None,
    ) -> None:
        self._desktop = desktop
        self._selected_tabs = selected_tabs
        self._selected_tab_scope_check = (
            selected_tab_scope_check or self._live_selected_tab_scope
        )
        self._bus = bus
        self._clock = clock
        self._scheduler = scheduler or _ThreadScheduler()
        self._lock = threading.RLock()
        self._state = OFF
        self._session_id = ""
        self._task_id = ""
        self._expires_at = 0.0
        self._surface_kind = ""
        self._surface_id = ""
        self._surface_generation = 0
        self._timer = None
        self._generation = 0
        self._overlay = overlay
        self._subscribe()

    def _subscribe(self) -> None:
        for topic in (
            "agent.tasks.cancel_all",
            "emergency.stop",
            "screen_control.unsafe",
            "window.closing",
            "application.shutdown",
        ):
            self._bus.subscribe(
                topic,
                lambda _data, reason=topic: self.revoke(reason),
            )
        self._bus.subscribe("task.finished", self._on_task_finished)

    def snapshot(self) -> ScreenControlSnapshot:
        with self._lock:
            return ScreenControlSnapshot(
                state=self._state,
                session_id=self._session_id,
                task_id=self._task_id,
                expires_at=self._expires_at,
                surface_kind=self._surface_kind,
                surface_id=self._surface_id,
                surface_generation=self._surface_generation,
            )

    def active(self) -> bool:
        return self.snapshot().state == ACTIVE

    def attach_overlay(self, overlay) -> bool:
        """Attach one visualization-only overlay while Screen Control is off."""
        required = (
            "show_state",
            "update_visual",
            "clear",
            "pause_for_capture",
            "resume_after_capture",
        )
        if overlay is None or not all(
            callable(getattr(overlay, name, None)) for name in required
        ):
            return False
        with self._lock:
            if self._state != OFF:
                return False
            previous = self._overlay
            self._overlay = overlay
        if previous is not None and previous is not overlay:
            self._overlay_call(previous, "clear")
        self._overlay_call(overlay, "clear")
        return True

    def update_visual(
        self,
        *,
        cursor=None,
        target_rect=None,
        status: str = "",
    ) -> bool:
        with self._lock:
            if self._state == OFF or self._overlay is None:
                return False
            overlay = self._overlay
        return self._overlay_call(
            overlay,
            "update_visual",
            cursor=cursor,
            target_rect=target_rect,
            status=str(status or "")[:64],
        )

    @contextmanager
    def capture_pause(self):
        """Synchronously retire overlay pixels when native exclusion is absent."""
        with self._lock:
            overlay = self._overlay
        paused = False
        if overlay is not None:
            try:
                paused = bool(overlay.pause_for_capture())
            except Exception as exc:
                _logger.warning(
                    "screen_control.overlay_capture_pause_failed",
                    error=type(exc).__name__,
                )
                raise RuntimeError("screen_control_capture_exclusion_unavailable") from exc
        try:
            yield
        finally:
            if overlay is not None and paused:
                if not self._overlay_call(overlay, "resume_after_capture"):
                    self.revoke("capture_resume_failed")

    def activate(self, session_id: str, task_id: str, *, ttl_s: float) -> bool:
        session = str(session_id or "").strip()
        task = str(task_id or "").strip()
        try:
            ttl = float(ttl_s)
        except (TypeError, ValueError):
            return False
        if (
            not session
            or not task
            or not math.isfinite(ttl)
            or ttl <= 0
            or ttl > _MAX_TTL_S
        ):
            return False
        with self._lock:
            if self._state != OFF:
                return False
            if not self._desktop.claim_authority(session):
                return False
            try:
                self._generation += 1
                generation = self._generation
                self._state = ACTIVE
                self._session_id = session
                self._task_id = task
                self._expires_at = self._clock() + ttl
                self._surface_kind = DESKTOP_SURFACE
                self._surface_id = ""
                self._surface_generation = 0
                self._timer = self._scheduler.call_later(
                    ttl,
                    lambda: self._expire(generation),
                )
            except Exception:
                self._desktop.release_authority(session)
                self._clear_locked()
                return False
            snapshot = self.snapshot()
        self._publish_if_current(snapshot, generation, "activated")
        return True

    def activate_browser_tab(
        self,
        session_id: str,
        task_id: str,
        *,
        target_id: str,
        target_generation: int,
        ttl_s: float,
    ) -> bool:
        session = str(session_id or "").strip()
        task = str(task_id or "").strip()
        target = str(target_id or "").strip()
        try:
            ttl = float(ttl_s)
        except (TypeError, ValueError):
            return False
        if (
            not session
            or not task
            or not target
            or type(target_generation) is not int
            or target_generation <= 0
            or not math.isfinite(ttl)
            or ttl <= 0
            or ttl > _MAX_TTL_S
        ):
            return False
        if not self._selected_tab_scope_check(session, task):
            return False
        with self._lock:
            if self._state != OFF:
                return False
            if not self._selected_tab_scope_check(session, task):
                return False
            if not self._selected_tabs.activate(
                session,
                task,
                target,
                target_generation=target_generation,
                ttl_s=ttl,
            ):
                return False
            try:
                self._generation += 1
                generation = self._generation
                lease = self._selected_tabs.snapshot()
                self._state = ACTIVE
                self._session_id = session
                self._task_id = task
                self._expires_at = lease.expires_at
                self._surface_kind = BROWSER_TAB_SURFACE
                self._surface_id = target
                self._surface_generation = target_generation
                self._timer = self._scheduler.call_later(
                    ttl,
                    lambda: self._expire(generation),
                )
            except Exception:
                self._selected_tabs.release_session(
                    session,
                    "activation_failed",
                )
                self._clear_locked()
                return False
            snapshot = self.snapshot()
        self._publish_if_current(snapshot, generation, "activated")
        return True

    @staticmethod
    def _live_selected_tab_scope(session_id: str, task_id: str) -> bool:
        try:
            from jarvis.agent import dispatch
            from jarvis.agent.tasks import REGISTRY, TaskStatus

            scope = dispatch.screen_control_scope()
            view = REGISTRY.get(task_id)
        except Exception:
            return False
        return bool(
            scope is not None
            and scope.session_id == session_id
            and scope.task_id == task_id
            and view is not None
            and view.status == TaskStatus.RUNNING
            and view.active
            and not view.cancelled
            and view.session_id == session_id
        )

    def selected_tab_binding_error(
        self,
        *,
        session_id: str = "",
        task_id: str = "",
        target_id: str = "",
        target_generation: int = 0,
    ) -> str:
        with self._lock:
            if self._state != ACTIVE:
                return "selected_tab_not_active"
            if self._surface_kind != BROWSER_TAB_SURFACE:
                return "selected_tab_surface_mismatch"
            expected_session = self._session_id
            expected_task = self._task_id
            expected_target = self._surface_id
            expected_generation = self._surface_generation
        requested_session = str(session_id or expected_session).strip()
        requested_task = str(task_id or expected_task).strip()
        requested_target = str(target_id or expected_target).strip()
        requested_generation = target_generation or expected_generation
        if requested_session != expected_session:
            return "selected_tab_lease_session_mismatch"
        if requested_task != expected_task:
            return "selected_tab_lease_task_mismatch"
        if requested_target != expected_target:
            return "selected_tab_lease_target_mismatch"
        if requested_generation != expected_generation:
            return "selected_tab_lease_generation_mismatch"
        return self._selected_tabs.binding_error(
            session_id=requested_session,
            task_id=requested_task,
            target_id=requested_target,
            target_generation=requested_generation,
        )

    def begin_handoff(self, task_id: str) -> bool:
        target = str(task_id or "").strip()
        with self._lock:
            if self._state != ACTIVE or self._task_id != target:
                return False
            owner = self._session_id
            surface_kind = self._surface_kind
            overlay = self._overlay
            if surface_kind == DESKTOP_SURFACE:
                self._desktop.release_authority(owner)
            self._state = HANDING_OFF
            snapshot = self.snapshot()
            generation = self._generation
        if overlay is not None:
            # Pre-CAPTCHA cursor and target rectangles are permanently retired.
            self._overlay_call(
                overlay,
                "update_visual",
                cursor=None,
                target_rect=None,
                status="handoff",
            )
        self._publish_if_current(snapshot, generation, "handoff")
        return True

    def resume_handoff(self, task_id: str) -> bool:
        target = str(task_id or "").strip()
        with self._lock:
            if self._state != HANDING_OFF or self._task_id != target:
                return False
            if self._clock() >= self._expires_at:
                generation = None
            else:
                owner = self._session_id
                if self._surface_kind == DESKTOP_SURFACE:
                    if not self._desktop.claim_authority(owner):
                        return False
                elif self._surface_kind == BROWSER_TAB_SURFACE:
                    lease_error = self._selected_tabs.binding_error(
                        session_id=owner,
                        task_id=self._task_id,
                        target_id=self._surface_id,
                        target_generation=self._surface_generation,
                    )
                    if lease_error:
                        return False
                else:
                    return False
                self._state = ACTIVE
                snapshot = self.snapshot()
                generation = self._generation
        if generation is None:
            self.release_task(target, "expired")
            return False
        self._publish_if_current(snapshot, generation, "resumed")
        return True

    def revoke_browser_tab(
        self,
        *,
        target_id: str,
        target_generation: int,
        reason: str,
    ) -> bool:
        target = str(target_id or "").strip()
        if not target or type(target_generation) is not int or target_generation <= 0:
            return False
        return self._revoke_matching(
            reason,
            lambda: (
                self._surface_kind == BROWSER_TAB_SURFACE
                and self._surface_id == target
                and self._surface_generation == target_generation
            ),
        )

    def release_session(self, session_id: str,
                        reason: str = "task_terminal") -> bool:
        owner = str(session_id or "").strip()
        return self._revoke_matching(
            reason,
            lambda: self._session_id == owner,
        )

    def release_task(self, task_id: str,
                     reason: str = "task_terminal") -> bool:
        target = str(task_id or "").strip()
        return self._revoke_matching(
            reason,
            lambda: self._task_id == target,
        )

    def revoke(self, reason: str = "revoked") -> bool:
        return self._revoke_matching(reason, lambda: True)

    def _revoke_matching(self, reason: str,
                         matches: Callable[[], bool]) -> bool:
        with self._lock:
            if self._state == OFF or not matches():
                return False
            owner = self._session_id
            surface_kind = self._surface_kind
            timer = self._timer
            self._generation += 1
            retired_generation = self._generation
            if surface_kind == DESKTOP_SURFACE and self._state == ACTIVE:
                # Retire the pinned lease before exposing OFF. Otherwise the
                # same session could reactivate in the gap and have its newer
                # reservation cleared by this stale cleanup.
                self._desktop.release_authority(owner)
            elif surface_kind == BROWSER_TAB_SURFACE:
                self._selected_tabs.release_session(owner, reason)
            self._clear_locked()
        if timer is not None:
            try:
                timer.cancel()
            except Exception as exc:
                _logger.warning(
                    "screen_control.timer_cancel_failed",
                    error=type(exc).__name__,
                )
        self._publish_if_current(
            ScreenControlSnapshot(),
            retired_generation,
            str(reason or "revoked"),
        )
        return True

    def _clear_locked(self) -> None:
        self._state = OFF
        self._session_id = ""
        self._task_id = ""
        self._expires_at = 0.0
        self._surface_kind = ""
        self._surface_id = ""
        self._surface_generation = 0
        self._timer = None

    def _expire(self, generation: int) -> None:
        self._revoke_matching(
            "expired",
            lambda: self._generation == generation,
        )

    def _on_task_finished(self, data: dict) -> None:
        task = data.get("task") or {}
        task_id = task.get("id") if isinstance(task, dict) else ""
        self.release_task(str(task_id or ""), "task_terminal")

    def _publish_if_current(self, snapshot: ScreenControlSnapshot,
                            generation: int, reason: str) -> None:
        with self._lock:
            current = self._generation == generation
            overlay = self._overlay
        if not current:
            return
        status = str(reason or "")[:64]
        if overlay is not None:
            if snapshot.state == OFF:
                self._overlay_call(overlay, "clear")
            else:
                self._overlay_call(
                    overlay,
                    "show_state",
                    mode=snapshot.state,
                    expires_at=snapshot.expires_at,
                    status=status,
                )
        try:
            self._bus.publish(
                "screen_control.changed",
                state=snapshot.state,
                active=snapshot.state == ACTIVE,
                reason=status,
                expires_at=snapshot.expires_at,
                surface_kind=snapshot.surface_kind,
                surface_id=snapshot.surface_id,
                surface_generation=snapshot.surface_generation,
            )
        except Exception as exc:
            _logger.warning(
                "screen_control.state_publish_failed",
                error=type(exc).__name__,
            )

    @staticmethod
    def _overlay_call(overlay, method: str, *args, **kwargs) -> bool:
        try:
            getattr(overlay, method)(*args, **kwargs)
            return True
        except Exception as exc:
            _logger.warning(
                "screen_control.overlay_update_failed",
                operation=method[:32],
                error=type(exc).__name__,
            )
            return False


COORDINATOR = ScreenControlCoordinator()


def default_ttl_s() -> float:
    try:
        value = float(config.get("screen_control.session_ttl_s", 900.0))
    except (TypeError, ValueError):
        value = 900.0
    return min(_MAX_TTL_S, max(1.0, value))


def install_overlay(*, coordinates=None, capture_exclusion=None) -> bool:
    """Create the top-level Qt overlay from the shared coordinate seam."""
    try:
        from jarvis.automation.screen_coordinates import (
            MonitorGeometry,
            ScreenCoordinateMapper,
        )
        from jarvis.ui.screen_cursor_overlay import ScreenCursorOverlay

        mapper = coordinates or ScreenCoordinateMapper(
            lambda: _qt_monitor_geometry(MonitorGeometry),
            uia_space="physical",
        )
        overlay = ScreenCursorOverlay(
            coordinates=mapper,
            capture_exclusion=capture_exclusion,
            clock=time.monotonic,
        )
        if not COORDINATOR.attach_overlay(overlay):
            overlay.close()
            return False
        return True
    except Exception as exc:
        _logger.warning(
            "screen_control.overlay_install_failed",
            error=type(exc).__name__,
        )
        return False


def _qt_monitor_geometry(monitor_type) -> tuple:
    from PyQt6.QtGui import QGuiApplication

    monitors = []
    for index, screen in enumerate(QGuiApplication.screens()):
        rect = screen.geometry()
        scale = float(screen.devicePixelRatio())
        logical = (rect.x(), rect.y(), rect.width(), rect.height())
        physical = (
            int(round(rect.x() * scale)),
            int(round(rect.y() * scale)),
            int(round(rect.width() * scale)),
            int(round(rect.height() * scale)),
        )
        monitors.append(
            monitor_type(
                screen.name() or f"screen-{index}",
                logical,
                physical,
                scale,
            )
        )
    return tuple(monitors)


def install(window_class) -> bool:
    """Publish the local window-close boundary before normal Qt teardown."""
    if getattr(window_class, "_jarvis_screen_control_teardown", False):
        return True
    original = getattr(window_class, "closeEvent", None)
    if not callable(original):
        return False

    def close_event(self, event):
        try:
            BUS.publish("window.closing")
        except Exception:
            COORDINATOR.revoke("window_closing")
        return original(self, event)

    window_class.closeEvent = close_event
    window_class._jarvis_screen_control_teardown = True
    return True


def shutdown() -> None:
    try:
        BUS.publish("application.shutdown")
    except Exception:
        COORDINATOR.revoke("application_shutdown")
    try:
        from jarvis.integrations.selected_tab_browser import shutdown_host

        shutdown_host()
    except Exception as exc:
        _logger.warning(
            "screen_control.selected_tab_host_shutdown_failed",
            error=type(exc).__name__,
        )


__all__ = [
    "ACTIVE",
    "BROWSER_TAB_SURFACE",
    "COORDINATOR",
    "DESKTOP_SURFACE",
    "HANDING_OFF",
    "OFF",
    "ScreenControlCoordinator",
    "ScreenControlSnapshot",
    "default_ttl_s",
    "install",
    "install_overlay",
    "shutdown",
]
