"""W3 — VisionSupervisor: pengawas deteksi objek realtime → Telegram (opt-in).

Berlangganan BUS vision (``vision.object`` / ``vision.status`` /
``vision.frame``) tanpa pernah memblokir pipeline kamera: handler hanya
menulis buffer ber-lock; thread pengirim terpisah melakukan coalesce +
throttle, lalu mengirim ringkasan objek (dan foto bila diizinkan) ke chat
Telegram pertama di allowlist.

Deny-by-default: ``vision_supervisor.enabled`` harus true. Laporan hanya saat
kamera hidup (``alive``) dan, dengan ``require_armed``, sedang di-arm.
"""
from __future__ import annotations

import threading
import time
from collections import deque
from typing import Any, Callable

from jarvis.core import config, log

_logger = log.get("integrations.vision_supervisor")

_started = False
_started_lock = threading.Lock()


class VisionSupervisor:
    """Coalescer + pengirim laporan deteksi objek (satu instance per runtime)."""

    def __init__(
        self,
        *,
        bus: Any | None = None,
        send_text: Callable[[str], bool] | None = None,
        send_photo: Callable[[str, str], bool] | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        if bus is None:
            from jarvis.core.bus import BUS
            bus = BUS
        self._bus = bus
        self._send_text = send_text or self._default_send_text
        self._send_photo = send_photo or self._default_send_photo
        self._now = now or time.monotonic
        self._lock = threading.Lock()
        self._buffer: deque[tuple[float, str]] = deque(maxlen=256)
        self._latest_jpeg: bytes = b""
        self._alive = False
        self._armed = False
        self._last_send: float | None = None
        self._running = False
        self._thread: threading.Thread | None = None
        self._started = False
        self._read_config()

    def _read_config(self) -> None:
        # Semua key dibaca sebagai literal config.get agar scanner kontrak
        # config (jarvis/core/config_contract.py) bisa mencocokkannya.
        self._enabled = bool(config.get("vision_supervisor.enabled", False))
        try:
            self._min_interval = max(
                1.0, float(config.get("vision_supervisor.min_interval_s", 30.0)))
        except (TypeError, ValueError):
            self._min_interval = 30.0
        try:
            self._poll_s = max(0.1, float(config.get("vision_supervisor.poll_s", 2.0)))
        except (TypeError, ValueError):
            self._poll_s = 2.0
        self._include_photo = bool(
            config.get("vision_supervisor.include_photo", True))
        self._require_armed = bool(
            config.get("vision_supervisor.require_armed", True))
        try:
            self._max_names = max(1, int(config.get("vision_supervisor.max_names", 12)))
        except (TypeError, ValueError):
            self._max_names = 12

    @staticmethod
    def _default_send_text(text: str) -> bool:
        from jarvis.agent.adapters.telegram import send_from_anywhere
        return bool(send_from_anywhere(text))

    @staticmethod
    def _default_send_photo(path: str, caption: str) -> bool:
        from jarvis.agent.adapters.telegram import send_photo_from_anywhere
        return bool(send_photo_from_anywhere(path, caption))

    # ── lifecycle ────────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._started:
            return
        self._started = True
        self._running = True
        self._bus.subscribe("vision.object", self._on_objects)
        self._bus.subscribe("vision.status", self._on_status)
        self._bus.subscribe("vision.frame", self._on_frame)
        self._thread = threading.Thread(
            target=self._loop, daemon=True, name="vision-supervisor")
        self._thread.start()
        _logger.info(
            "vision_supervisor.started",
            enabled=self._enabled,
            min_interval_s=self._min_interval,
        )

    def stop(self) -> None:
        self._running = False

    # ── handler BUS (thread publisher — HANYA buffering, dilarang I/O) ──────

    def _on_objects(self, data: dict) -> None:
        if not self._enabled or not self._alive:
            return
        if self._require_armed and not self._armed:
            return
        objects = data.get("objects") or []
        if not objects:
            return
        stamp = self._now()
        with self._lock:
            for item in objects:
                name = str((item or {}).get("name") or "").strip()
                if name:
                    self._buffer.append((stamp, name))

    def _on_status(self, data: dict) -> None:
        self._alive = bool(data.get("alive", self._alive))
        self._armed = bool(data.get("armed", self._armed))

    def _on_frame(self, data: dict) -> None:
        jpeg = data.get("jpeg")
        if jpeg:
            self._latest_jpeg = jpeg

    # ── thread pengirim ──────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            time.sleep(self._poll_s)
            try:
                self._tick()
            except Exception as exc:  # noqa: BLE001 - pengawas tak boleh mati
                _logger.warning("vision_supervisor.tick_failed",
                                error=type(exc).__name__)

    def _tick(self) -> None:
        if not self._enabled:
            return
        if self._require_armed and not self._armed:
            return
        if not self._alive:
            return
        now = self._now()
        with self._lock:
            if not self._buffer:
                return
            if self._last_send is not None \
                    and now - self._last_send < self._min_interval:
                return
            items = list(self._buffer)
            self._buffer.clear()
        report = self._compose(items)
        if not report:
            return
        ok = False
        try:
            ok = bool(self._send_text(report))
        except Exception as exc:  # noqa: BLE001
            _logger.warning("vision_supervisor.send_failed",
                            error=type(exc).__name__)
        if self._include_photo and self._latest_jpeg:
            path = self._write_photo(self._latest_jpeg)
            if path:
                try:
                    ok = bool(self._send_photo(path, report[:200])) or ok
                except Exception as exc:  # noqa: BLE001
                    _logger.warning("vision_supervisor.photo_failed",
                                    error=type(exc).__name__)
        if ok:
            self._last_send = now

    def _compose(self, items: list[tuple[float, str]]) -> str:
        counts: dict[str, int] = {}
        for _stamp, name in items:
            counts[name] = counts.get(name, 0) + 1
        top = sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[
            : self._max_names
        ]
        if not top:
            return ""
        parts = ", ".join(f"{name} x{n}" for name, n in top)
        window_s = max(1, int(round(self._min_interval)))
        return (
            f"👁 Pengawasan JARVIS: {parts} "
            f"(terdeteksi dalam {window_s} detik terakhir)."
        )

    def _write_photo(self, jpeg: bytes) -> str:
        try:
            from jarvis.agent.paths import generated_dir
            path = generated_dir() / f"vision_supervisor_{int(time.time())}.jpg"
            path.write_bytes(jpeg)
            return str(path)
        except Exception:  # noqa: BLE001 - foto gagal = omission jujur
            return ""


def start_vision_supervisor() -> VisionSupervisor | None:
    """Start pengawas dari UI bila enabled; no-op selain itu (deny-by-default)."""
    global _started
    try:
        if not bool(config.get("vision_supervisor.enabled", False)):
            return None
        with _started_lock:
            if _started:
                return None
            _started = True
        supervisor = VisionSupervisor()
        supervisor.start()
        return supervisor
    except Exception as exc:  # noqa: BLE001 - pengawas tak boleh mematikan boot
        _logger.warning("vision_supervisor.start_failed",
                        error=type(exc).__name__)
        return None
