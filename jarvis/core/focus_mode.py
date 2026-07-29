"""FocusMode — Do-Not-Disturb (redesign §16).

Pauses spoken comment narration and reduces proactive suggestions while
still collecting events up to a bounded queue elsewhere (the comment
manager honours ``should_narrate_comments()``); emergency notifications and
the emergency-stop vision gesture are never gated by this module — the
gesture path in ``jarvis.vision.process`` doesn't consult FocusMode at all,
so it stays unconditionally active by construction.

Pure state + BUS events, no Qt dependency, so it is unit-testable headless.
"""
from __future__ import annotations

import threading
import time

from jarvis.core import log
from jarvis.core.bus import BUS

_logger = log.get("core.focus_mode")


class FocusMode:
    _instance: "FocusMode | None" = None

    @classmethod
    def get(cls) -> "FocusMode":
        if cls._instance is None:
            cls._instance = FocusMode()
        return cls._instance

    @classmethod
    def _reset_for_tests(cls) -> None:
        if cls._instance is not None:
            cls._instance._cancel_timer()
        cls._instance = None

    def __init__(self) -> None:
        self._active = False
        self._until: float | None = None
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None

    @property
    def active(self) -> bool:
        with self._lock:
            if self._active and self._until is not None and time.time() >= self._until:
                self._deactivate_locked()
            return self._active

    @property
    def resumes_at(self) -> float | None:
        return self._until

    def activate(self, duration_s: float | None = None) -> None:
        with self._lock:
            self._cancel_timer_locked()
            self._active = True
            self._until = (time.time() + duration_s) if duration_s else None
            if duration_s:
                self._timer = threading.Timer(duration_s, self._auto_resume)
                self._timer.daemon = True
                self._timer.start()
        _logger.info("focus.activated", duration_s=duration_s)
        BUS.publish("focus.changed", active=True, until=self._until)

    def deactivate(self) -> None:
        with self._lock:
            self._deactivate_locked()
        _logger.info("focus.deactivated")
        BUS.publish("focus.changed", active=False, until=None)

    def toggle(self, duration_s: float | None = None) -> bool:
        if self.active:
            self.deactivate()
        else:
            self.activate(duration_s)
        return self.active

    # ── policy surface consumed by comment manager / notifications / UI ─────

    def should_narrate_comments(self) -> bool:
        return not self.active

    def should_show_proactive_suggestions(self) -> bool:
        return not self.active

    def allows_notification(self, status: str = "info") -> bool:
        """Emergency/critical notifications always pass; ambient ones don't."""
        return (not self.active) or status == "error"

    # ── internals ─────────────────────────────────────────────────────────

    def _deactivate_locked(self) -> None:
        self._active = False
        self._until = None
        self._cancel_timer_locked()

    def _cancel_timer_locked(self) -> None:
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None

    def _cancel_timer(self) -> None:
        with self._lock:
            self._cancel_timer_locked()

    def _auto_resume(self) -> None:
        self.deactivate()
