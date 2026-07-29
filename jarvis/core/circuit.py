"""Simple thread-safe circuit breaker (Fase 6).

closed → (N consecutive failures) → open → (reset timeout) → half-open →
one probe call → closed on success / open again on failure. Keeps a flaky
external service from hanging the whole app on every request.
"""
from __future__ import annotations

import threading
import time

from jarvis.core import log

_logger = log.get("circuit")


class CircuitOpenError(RuntimeError):
    pass


class CircuitBreaker:
    def __init__(self, name: str, failure_threshold: int = 5,
                 reset_timeout_s: float = 30.0):
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout_s = reset_timeout_s
        self._lock = threading.Lock()
        self._failures = 0
        self._state = "closed"           # closed | open | half-open
        self._opened_at = 0.0

    @property
    def state(self) -> str:
        with self._lock:
            if (self._state == "open"
                    and time.monotonic() - self._opened_at >= self.reset_timeout_s):
                self._state = "half-open"
            return self._state

    def allow(self) -> bool:
        return self.state != "open"

    def record_success(self) -> None:
        with self._lock:
            if self._state != "closed":
                _logger.info("circuit.closed", name=self.name)
            self._failures = 0
            self._state = "closed"

    def record_failure(self) -> None:
        with self._lock:
            self._failures += 1
            if self._state == "half-open" or \
                    self._failures >= self.failure_threshold:
                if self._state != "open":
                    _logger.warning("circuit.opened", name=self.name,
                                    failures=self._failures)
                self._state = "open"
                self._opened_at = time.monotonic()

    def call(self, fn, *args, **kwargs):
        if not self.allow():
            raise CircuitOpenError(
                f"circuit '{self.name}' is open — service temporarily skipped")
        try:
            result = fn(*args, **kwargs)
        except Exception:
            self.record_failure()
            raise
        self.record_success()
        return result
