"""Single bounded shutdown authority for canonical JARVIS runtime."""
from __future__ import annotations

from collections.abc import Callable
from threading import Lock


class RuntimeSupervisor:
    """Own stop callbacks and non-daemon worker joins exactly once."""

    thread_daemon = False

    def __init__(self, *, join_timeout: float = 5.0,
                 on_error: Callable[[str, Exception], None] | None = None) -> None:
        self._join_timeout = max(0.0, float(join_timeout))
        self._on_error = on_error
        self._stops: list[tuple[str, Callable[[], None]]] = []
        self._threads: list[tuple[str, object]] = []
        self._closed = False
        self._lock = Lock()

    def add_stop(self, name: str, callback: Callable[[], None]) -> None:
        with self._lock:
            if self._closed:
                return
            self._stops.append((str(name), callback))

    def add_thread(self, name: str, thread: object) -> None:
        with self._lock:
            if self._closed:
                return
            self._threads.append((str(name), thread))

    def shutdown(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            stops = list(reversed(self._stops))
            threads = list(reversed(self._threads))
        for name, callback in stops:
            try:
                callback()
            except Exception as exc:  # noqa: BLE001
                if self._on_error:
                    self._on_error(name, exc)
        for name, thread in threads:
            try:
                if getattr(thread, "is_alive", lambda: False)():
                    thread.join(self._join_timeout)
            except Exception as exc:  # noqa: BLE001
                if self._on_error:
                    self._on_error(name, exc)
