"""Bounded daemon owner for offline-testable comment polling."""
from __future__ import annotations

import math
import threading
import time

from jarvis.core import log

_logger = log.get("comments.runtime")


class DeterministicReplyHandler:
    """Classify one event and send only deterministic AUTO decisions."""

    def __init__(self, manager, policy, *, audit=None) -> None:
        self._manager = manager
        self._policy = policy
        self._audit = audit or getattr(manager, "_audit", None)

    def __call__(self, event) -> None:
        decision = self._policy.classify(
            event.text,
            platform=event.platform,
            author_id=event.author_id,
        )
        if self._audit is not None:
            self._audit.record(
                event="reply_decision",
                platform=event.platform,
                comment_id=event.comment_id,
                disposition=decision.disposition.value,
                reason=decision.reason[:64],
            )
        if decision.disposition.value == "auto" and decision.reply:
            self._manager.reply(event, decision.reply)


class CommentRuntime:
    """Run one CommentManager polling loop outside the GUI thread."""

    def __init__(
        self,
        manager,
        *,
        poll_interval_s: float = 5.0,
        sleeper=None,
        thread_factory=threading.Thread,
        handler=None,
    ) -> None:
        self._manager = manager
        self._poll_interval_s = _valid_interval(poll_interval_s)
        self._sleeper = sleeper
        self._thread_factory = thread_factory
        self._handler = handler
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._thread = None
        self._started = False
        self._terminal = False

    @property
    def daemon(self) -> bool:
        with self._lock:
            return bool(self._thread is not None and self._thread.daemon)

    @property
    def running(self) -> bool:
        with self._lock:
            return bool(self._thread is not None and self._thread.is_alive())

    def start(self) -> bool:
        with self._lock:
            if (
                self._poll_interval_s is None
                or self._started
                or self._terminal
                or self._stop.is_set()
            ):
                return False
            self._started = True
            self._thread = self._thread_factory(
                target=self._run,
                daemon=True,
                name="comments-runtime",
            )
            thread = self._thread
        try:
            thread.start()
        except Exception:
            with self._lock:
                self._terminal = True
                self._thread = None
            return False
        return True

    def stop(self) -> None:
        self._stop.set()
        with self._lock:
            self._terminal = True

    def join(self, timeout: float | None = None) -> bool:
        with self._lock:
            thread = self._thread
        if thread is None:
            return True
        thread.join(timeout)
        return not thread.is_alive()

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                events = self._manager.poll_once()
                if self._handler is not None:
                    for event in tuple(events or ()):
                        try:
                            self._handler(event)
                        except Exception as exc:
                            _logger.warning(
                                "comments.runtime_handler_failed",
                                error=type(exc).__name__,
                            )
                if self._stop.is_set():
                    break
                if self._sleeper is None:
                    self._stop.wait(self._poll_interval_s)
                else:
                    self._sleeper(self._poll_interval_s)
        finally:
            with self._lock:
                self._terminal = True


def _valid_interval(value: float) -> float | None:
    try:
        interval = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(interval) or interval <= 0 or interval > 3600:
        return None
    return interval


__all__ = ["CommentRuntime", "DeterministicReplyHandler"]
