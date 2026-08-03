"""Phase WA1 — countdown → orb visual driver.

Adapter tipis antara CountdownTimer (core) dan orb renderer (ui/orb.py
FROZEN — hanya memakai set_progress yang sudah ada). Ticker di-inject
(QTimer di window.py) agar testable tanpa Qt. Tanpa network/write.
"""
from __future__ import annotations

from typing import Callable


class CountdownDriver:
    """Tick timer → set_progress(orb); berhenti otomatis saat selesai."""

    def __init__(self, *, timer: object, orb: object,
                 set_progress: Callable[[float], None],
                 ticker_start: Callable[[], None],
                 ticker_stop: Callable[[], None]) -> None:
        self._timer = timer
        self._set_progress = set_progress
        self._ticker_start = ticker_start
        self._ticker_stop = ticker_stop
        self._attached = False
        self._done = False

    def attach(self) -> None:
        if self._attached:
            return
        self._attached = True
        self._ticker_start()

    def detach(self) -> None:
        if not self._attached:
            return
        self._attached = False
        self._ticker_stop()

    def tick(self) -> None:
        """Satu detak: sinkronkan orb dengan timer; stop saat done."""
        if self._done:
            return
        status = self._timer.status()
        if status in ("done", "cancelled"):
            self._set_progress(1.0 if status == "done" else 0.0)
            self._done = True
            self.detach()
            return
        self._set_progress(self._timer.progress())

    @property
    def attached(self) -> bool:
        return self._attached


__all__ = ["CountdownDriver"]
