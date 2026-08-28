"""Process-local authority owner for semantic Screen Control sessions."""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Callable

from jarvis.automation.desktop_service import DESKTOP
from jarvis.core import config, log
from jarvis.core.bus import BUS

_logger = log.get("ui.screen_control")

OFF = "off"
ACTIVE = "active"
HANDING_OFF = "handing_off"
_MAX_TTL_S = 3600.0


@dataclass(frozen=True)
class ScreenControlSnapshot:
    state: str = OFF
    session_id: str = ""
    task_id: str = ""
    expires_at: float = 0.0


class _ThreadScheduler:
    def call_later(self, delay_s: float, callback: Callable[[], None]):
        timer = threading.Timer(delay_s, callback)
        timer.daemon = True
        timer.start()
        return timer


class ScreenControlCoordinator:
    """Own one bounded desktop lease and its task/session binding."""

    def __init__(self, *, desktop=DESKTOP, bus=BUS, clock=time.monotonic,
                 scheduler=None) -> None:
        self._desktop = desktop
        self._bus = bus
        self._clock = clock
        self._scheduler = scheduler or _ThreadScheduler()
        self._lock = threading.RLock()
        self._state = OFF
        self._session_id = ""
        self._task_id = ""
        self._expires_at = 0.0
        self._timer = None
        self._generation = 0
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
            )

    def active(self) -> bool:
        return self.snapshot().state == ACTIVE

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

    def begin_handoff(self, task_id: str) -> bool:
        target = str(task_id or "").strip()
        with self._lock:
            if self._state != ACTIVE or self._task_id != target:
                return False
            owner = self._session_id
            self._desktop.release_authority(owner)
            self._state = HANDING_OFF
            snapshot = self.snapshot()
            generation = self._generation
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
                if not self._desktop.claim_authority(owner):
                    return False
                self._state = ACTIVE
                snapshot = self.snapshot()
                generation = self._generation
        if generation is None:
            self.release_task(target, "expired")
            return False
        self._publish_if_current(snapshot, generation, "resumed")
        return True

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
            held = self._state == ACTIVE
            timer = self._timer
            self._generation += 1
            retired_generation = self._generation
            if held:
                # Retire the pinned lease before exposing OFF. Otherwise the
                # same session could reactivate in the gap and have its newer
                # reservation cleared by this stale cleanup.
                self._desktop.release_authority(owner)
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
        if not current:
            return
        try:
            self._bus.publish(
                "screen_control.changed",
                state=snapshot.state,
                active=snapshot.state == ACTIVE,
                reason=str(reason or "")[:64],
                expires_at=snapshot.expires_at,
            )
        except Exception as exc:
            _logger.warning(
                "screen_control.state_publish_failed",
                error=type(exc).__name__,
            )


COORDINATOR = ScreenControlCoordinator()


def default_ttl_s() -> float:
    try:
        value = float(config.get("screen_control.session_ttl_s", 900.0))
    except (TypeError, ValueError):
        value = 900.0
    return min(_MAX_TTL_S, max(1.0, value))


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


__all__ = [
    "ACTIVE",
    "COORDINATOR",
    "HANDING_OFF",
    "OFF",
    "ScreenControlCoordinator",
    "ScreenControlSnapshot",
    "default_ttl_s",
    "install",
    "shutdown",
]
