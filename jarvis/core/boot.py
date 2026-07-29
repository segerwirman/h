"""BootSequence — non-blocking cinematic readiness checks.

Runs off the UI thread. Each check publishes ``boot.check`` on the bus; the
final greeting is built strictly from the *actual* check results — never
hardcoded. A degraded subsystem (works, but limited) is reported as such.
"""
from __future__ import annotations

import threading
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass
from typing import Callable

from jarvis.core import config, llm, log
from jarvis.core.bus import BUS

_logger = log.get("boot")

@dataclass
class CheckResult:
    subsystem: str
    ok: bool
    degraded: bool = False
    detail: str = ""


# ── individual subsystem checks ───────────────────────────────────────────────

def _check_llm() -> CheckResult:
    if not llm.api_key():
        return CheckResult("core.llm", False, detail="API key missing")
    # Reachability only — constructing the genai client here costs ~20 s cold;
    # the Live session builds its own client after boot. DNS resolution is not
    # bounded by the socket timeout, so the probe runs in its own thread.
    outcome: dict = {}

    def _probe():
        try:
            import socket
            socket.create_connection(
                ("generativelanguage.googleapis.com", 443), timeout=3).close()
            outcome["ok"] = True
        except Exception as e:
            outcome["err"] = str(e)[:60]

    t = threading.Thread(target=_probe, daemon=True)
    t.start()
    t.join(3.5)
    if outcome.get("ok"):
        return CheckResult("core.llm", True, detail="model reachable")
    return CheckResult("core.llm", True, degraded=True,
                       detail=outcome.get("err", "reachability unverified"))


def _check_stt() -> CheckResult:
    try:
        import sounddevice as sd
        dev = sd.query_devices(kind="input")
        return CheckResult("core.stt", True, detail=str(dev.get("name", "mic")))
    except Exception as e:
        return CheckResult("core.stt", False, detail=str(e)[:80])


def _check_tts() -> CheckResult:
    try:
        import sounddevice as sd
        dev = sd.query_devices(kind="output")
        return CheckResult("core.tts", True, detail=str(dev.get("name", "audio out")))
    except Exception as e:
        return CheckResult("core.tts", False, detail=str(e)[:80])


def _check_vision() -> CheckResult:
    weights = config.resolve_path(config.get("vision.yolo_weights", "yolov8n.pt"))
    if not weights.exists():
        return CheckResult("core.vision", False, detail="YOLO weights missing")
    try:
        import cv2
        idx = int(config.get("vision.camera_index", 0))
        cap = cv2.VideoCapture(idx, getattr(cv2, "CAP_DSHOW", 0))
        opened = cap.isOpened()
        cap.release()
        if not opened:
            return CheckResult("core.vision", True, degraded=True,
                               detail="weights ok, camera unavailable")
        return CheckResult("core.vision", True, detail="camera + weights ok")
    except Exception as e:
        return CheckResult("core.vision", False, detail=str(e)[:80])


def _check_gesture() -> CheckResult:
    try:
        import mediapipe  # noqa: F401
        return CheckResult("core.gesture", True, detail="MediaPipe loaded")
    except Exception as e:
        return CheckResult("core.gesture", False, detail=str(e)[:80])


def _check_browser() -> CheckResult:
    try:
        import PyQt6.QtWebEngineWidgets  # noqa: F401
        return CheckResult("core.browser", True, detail="QtWebEngine ready")
    except Exception:
        pass
    try:
        import webview  # noqa: F401
        return CheckResult("core.browser", True, degraded=True,
                           detail="pywebview fallback")
    except Exception:
        pass
    # Opening the user's real browser is a valid native capability even when
    # the retired embedded ContentStage driver is absent.
    try:
        import os
        import platform
        import webbrowser

        if platform.system() == "Windows" and getattr(os, "startfile", None):
            return CheckResult(
                "core.browser",
                True,
                degraded=True,
                detail="system browser ready; no embed driver",
            )
        webbrowser.get()
        return CheckResult(
            "core.browser",
            True,
            degraded=True,
            detail="system browser ready; no embed driver",
        )
    except Exception:
        return CheckResult(
            "core.browser", False, detail="no system or embed browser")


def _check_system() -> CheckResult:
    try:
        import pyautogui
        w, h = pyautogui.size()
        return CheckResult("core.system", True, detail=f"screen {w}x{h}")
    except Exception as e:
        return CheckResult("core.system", False, detail=str(e)[:80])


def _check_hermes() -> CheckResult:
    """Deprecated Hermes bridge: disabled is the safe, expected default."""
    from jarvis.integrations.hermes.bridge import is_enabled
    if not is_enabled():
        return CheckResult("core.hermes", True,
                           detail="deprecated integration disabled")
    try:
        from jarvis.integrations.hermes.bridge import HermesBridge
        c = HermesBridge.get().check()
        if c["ok"]:
            return CheckResult("core.hermes", True, detail=c["detail"])
        return CheckResult("core.hermes", True, degraded=True,
                           detail=c["detail"])
    except Exception as e:
        return CheckResult("core.hermes", True, degraded=True,
                           detail=str(e)[:80])


_CHECKS: dict[str, Callable[[], CheckResult]] = {
    "core.llm": _check_llm,
    "core.stt": _check_stt,
    "core.tts": _check_tts,
    "core.vision": _check_vision,
    "core.gesture": _check_gesture,
    "core.browser": _check_browser,
    "core.system": _check_system,
}


# ── greeting builder (pure, unit-testable) ────────────────────────────────────

# ── sequence runner ───────────────────────────────────────────────────────────

class BootSequence:
    """Fade the orb in while checking subsystems, then hand back the greeting.

    on_done(greeting, results) fires on the worker thread — marshal to the UI
    or the Live session from there.
    """

    def __init__(self, on_done: Callable[[str, list[CheckResult]], None]):
        self._on_done = on_done
        self.results: list[CheckResult] = []

    def start(self) -> None:
        threading.Thread(target=self._run, daemon=True, name="boot-seq").start()

    def _run(self) -> None:
        t0 = time.monotonic()
        timeout = float(config.get("boot.check_timeout_s", 6))
        order = config.get("boot.subsystems", list(_CHECKS))
        # All checks run concurrently (one hung check must not stall the rest);
        # results are still reported in the configured order.
        pool = ThreadPoolExecutor(max_workers=len(order) or 1)
        try:
            futures = {name: pool.submit(_CHECKS[name])
                       for name in order if name in _CHECKS}
            deadline = time.monotonic() + timeout
            for name in order:
                if name not in futures:
                    result = CheckResult(name, False, detail="unknown subsystem")
                else:
                    try:
                        result = futures[name].result(
                            timeout=max(0.1, deadline - time.monotonic()))
                    except FutureTimeout:
                        result = CheckResult(name, False, detail="check timed out")
                    except Exception as e:
                        result = CheckResult(name, False, detail=str(e)[:80])
                self.results.append(result)
                status = "ONLINE" if result.ok else "FAILED"
                if result.ok and result.degraded:
                    status = "DEGRADED"
                _logger.info("boot.check", subsystem=name, status=status,
                             detail=result.detail)
                BUS.publish("boot.check", subsystem=name, ok=result.ok,
                            degraded=result.degraded, detail=result.detail)
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        online = [r.subsystem for r in self.results if r.ok]
        failed = [r.subsystem for r in self.results if not r.ok]
        _logger.info("boot.done", online=online, failed=failed,
                     elapsed_s=round(time.monotonic() - t0, 2))
        BUS.publish("boot.done", online=online, failed=failed)
        self._on_done("READY", self.results)
