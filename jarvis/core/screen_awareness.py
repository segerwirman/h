"""Continuous screen awareness — event-driven, adaptive sampling (redesign §11).

Deliberately NOT a high-frequency full-frame OCR/vision-inference loop.
A screenshot is captured/analyzed only when:
  * the foreground window/title changes,
  * the visual scene changes beyond a perceptual-hash threshold,
  * a caller explicitly requests a snapshot to ground a command,
  * an adaptive refresh interval expires (interval backs off while the
    scene stays static, resets to the minimum on real change).

Runs entirely off the GUI thread on a daemon watcher thread, publishes
``ScreenContextModel`` snapshots on the BUS, and honours a privacy denylist
+ retention cap so raw screenshots are never kept indefinitely. Disabled by
default (``awareness.enabled: false``) — nothing captures without explicit
opt-in from the caller.

Accessibility/UI-automation state is preferred over OCR for actionable
targets elsewhere in this codebase (``jarvis.core.target_resolver`` acts on
window titles, not OCR text); OCR here is a best-effort, fully-optional
content fallback (guarded ``pytesseract`` import) — the watcher still works
as a window/title tracker without it.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.core.privacy_denylist import is_denylisted

_logger = log.get("core.screen_awareness")


@dataclass
class ScreenContextModel:
    monitor: str
    app: str
    title: str
    timestamp: float
    screenshot_ref: str | None = None
    ocr_blocks: list[str] = field(default_factory=list)
    control_candidates: list[dict] = field(default_factory=list)
    app_candidates: list[str] = field(default_factory=list)
    confidence: float = 0.0
    provenance: str = "window_tracker"     # window_tracker | interval | manual | denylist
    stale: bool = False
    # Redesign §11 hierarchy — Desktop → Window → Chrome → Page. Elements
    # live in a scoped ScreenElementTree (jarvis.core.element_model); they
    # are never flattened into one unscoped control list here.
    window_id: str = ""
    process: str = ""
    active_tab: str = ""
    url: str = ""                          # only when safely available
    element_tree: object | None = None      # ScreenElementTree | None
    privacy: str = "normal"                 # normal | redacted


def _phash(image) -> int:
    """8x8 average-hash — no dependency beyond Pillow (already a project
    dependency) — sufficient to detect "meaningfully different scene"
    without pulling in a dedicated perceptual-hash library."""
    small = image.convert("L").resize((8, 8))
    pixels = list(small.get_flattened_data())
    avg = sum(pixels) / len(pixels)
    bits = 0
    for i, p in enumerate(pixels):
        if p > avg:
            bits |= (1 << i)
    return bits


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _is_denylisted(title: str, app: str) -> bool:
    """Compatibility wrapper for legacy watcher callers."""
    return is_denylisted(title, app)


class _ForegroundWindowTracker:
    """Real on Windows via pygetwindow (already a project dependency);
    an honest no-op elsewhere rather than a fake reading."""

    def __init__(self):
        try:
            import pygetwindow as gw
            self._gw = gw
            self.supported = True
        except ImportError:
            self._gw = None
            self.supported = False

    def current(self) -> str | None:
        if not self.supported:
            return None
        try:
            w = self._gw.getActiveWindow()
            return (w.title or "") if w is not None else ""
        except Exception:
            return None


class ScreenAwareness:
    """Owns the background watcher thread. Never starts on its own — the
    caller (UI wiring) decides when to call ``start()``, honouring
    ``awareness.enabled`` and any user consent flow."""

    def __init__(self):
        c = config.section("awareness")
        self._min_interval = float(c.get("min_interval_s", 2.0))
        self._max_interval = float(c.get("max_interval_s", 30.0))
        self._hash_threshold = int(c.get("hash_change_threshold", 8))
        self._window_poll_s = float(c.get("window_poll_s", 1.0))
        retention = (c.get("privacy", {}) or {}).get("retention", {}) or {}
        self._max_snapshots = int(retention.get("max_snapshots", 200))
        self._max_age_h = float(retention.get("max_age_hours", 24))

        self._tracker = _ForegroundWindowTracker()
        self._stop = threading.Event()
        self._paused = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_title = ""
        self._last_hash: int | None = None
        self._last_capture_t = 0.0
        self._snapshots: list[ScreenContextModel] = []
        self._lock = threading.Lock()

    # ── controls ──────────────────────────────────────────────────────

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="screen-awareness")
        self._thread.start()
        _logger.info("awareness.started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        _logger.info("awareness.stopped")

    def pause(self) -> None:
        self._paused.set()
        BUS.publish("awareness.status", paused=True)

    def resume(self) -> None:
        self._paused.clear()
        BUS.publish("awareness.status", paused=False)

    @property
    def paused(self) -> bool:
        return self._paused.is_set()

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def latest(self) -> ScreenContextModel | None:
        with self._lock:
            return self._snapshots[-1] if self._snapshots else None

    def history(self, limit: int = 50) -> list[ScreenContextModel]:
        with self._lock:
            return list(self._snapshots[-limit:])

    def clear_history(self) -> None:
        with self._lock:
            for s in self._snapshots:
                if s.screenshot_ref:
                    try:
                        Path(s.screenshot_ref).unlink(missing_ok=True)
                    except OSError:
                        pass
            self._snapshots.clear()

    # ── worker loop ───────────────────────────────────────────────────

    def _run(self) -> None:
        interval = self._min_interval
        while not self._stop.wait(self._window_poll_s):
            if self._paused.is_set():
                continue
            now = time.time()
            changed = self._check_foreground_change()
            due = (now - self._last_capture_t) >= interval
            if changed or due:
                self._capture(reason="window_change" if changed else "interval")
                interval = self._min_interval if changed else min(self._max_interval, interval * 1.5)
                self._last_capture_t = now
            self._retain()

    def _check_foreground_change(self) -> bool:
        title = self._tracker.current()
        if title is None:
            return False
        changed = title != self._last_title
        self._last_title = title
        return changed

    def request_snapshot(self, reason: str = "manual") -> ScreenContextModel | None:
        """Explicit, caller-requested capture for grounding a command —
        always allowed regardless of where the adaptive interval currently is."""
        return self._capture(reason=reason)

    def _capture(self, reason: str) -> ScreenContextModel | None:
        title = self._tracker.current() or ""
        app = title.split(" - ")[-1].strip() if " - " in title else title
        if _is_denylisted(title, app):
            model = ScreenContextModel(monitor="", app="[redacted]", title="[redacted]",
                                       timestamp=time.time(), provenance="denylist",
                                       confidence=1.0)
            with self._lock:
                self._snapshots.append(model)
            BUS.publish("awareness.context", model=model)
            return model

        screenshot_ref = None
        ocr_blocks: list[str] = []
        try:
            from PIL import ImageGrab
            img = ImageGrab.grab()
            h = _phash(img)
            changed_visually = self._last_hash is None or _hamming(h, self._last_hash) >= self._hash_threshold
            self._last_hash = h
            if changed_visually or reason != "interval":
                screenshot_ref = self._persist(img)
                ocr_blocks = self._maybe_ocr(img)
        except Exception as e:
            _logger.debug("awareness.capture_unavailable", error=str(e)[:100])

        model = ScreenContextModel(
            monitor="primary", app=app, title=title, timestamp=time.time(),
            screenshot_ref=screenshot_ref, ocr_blocks=ocr_blocks, provenance=reason,
            confidence=0.8 if title else 0.2)
        with self._lock:
            self._snapshots.append(model)
        BUS.publish("awareness.context", model=model)
        return model

    @staticmethod
    def _maybe_ocr(img) -> list[str]:
        try:
            import pytesseract
        except ImportError:
            return []
        try:
            text = pytesseract.image_to_string(img)
            return [ln.strip() for ln in text.splitlines() if ln.strip()][:20]
        except Exception:
            return []

    def _persist(self, img) -> str | None:
        try:
            out_dir = config.resolve_path("logs/screenshots")
            out_dir.mkdir(parents=True, exist_ok=True)
            path = out_dir / f"ctx_{int(time.time() * 1000)}.jpg"
            img.convert("RGB").save(path, "JPEG", quality=60)
            return str(path)
        except Exception:
            return None

    def _retain(self) -> None:
        with self._lock:
            cutoff = time.time() - self._max_age_h * 3600
            keep, drop = [], []
            for s in self._snapshots:
                (keep if s.timestamp >= cutoff else drop).append(s)
            overflow = len(keep) - self._max_snapshots
            if overflow > 0:
                drop.extend(keep[:overflow])
                keep = keep[overflow:]
            self._snapshots = keep
        for s in drop:
            if s.screenshot_ref:
                try:
                    Path(s.screenshot_ref).unlink(missing_ok=True)
                except OSError:
                    pass


_instance: ScreenAwareness | None = None


def get() -> ScreenAwareness:
    global _instance
    if _instance is None:
        _instance = ScreenAwareness()
    return _instance
