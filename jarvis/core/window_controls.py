"""WindowControlRegistry — normalized window-management semantics (§9).

Every window-management action J.A.R.V.I.S understands is one of the
``WindowControl`` values below; free-form phrases ("maximise", "kecilkan",
"perbesar") normalize into them so minimize / maximize / restore / close are
always distinct semantic controls, never "some button that looks similar".

Recognition/actuation sources, in the spec's priority order:
  1. ``QtOwnWindowAdapter`` — J.A.R.V.I.S's own windows via Qt itself
     (exact, provenance "qt").
  2. ``WindowsWindowControlAdapter`` — foreign windows on Windows via
     pygetwindow (Win32), the same dependency the target resolver already
     uses; snap falls back to the OS Win+Arrow shortcut via pyautogui.
  3. ``UnsupportedWindowControlAdapter`` — macOS/Linux/Wayland report their
     capabilities honestly instead of pretending (AT-SPI/AX adapters can
     slot in here later without touching callers).

Safety: CLOSE is destructive and always routes through the existing
``jarvis.core.target_resolver`` policy (revalidation, unsaved-work checks,
confirmation round-trip, graceful-first, never force-kill by default). Every
execution is audited with target, control, and result.
"""
from __future__ import annotations

import json
import platform
import time
from dataclasses import dataclass
from enum import Enum

from jarvis.core import config, log
from jarvis.core.target_resolver import (CloseDecision, TargetResolver,
                                         WindowInfo, decide_and_close)

_logger = log.get("core.window_controls")


class WindowControl(str, Enum):
    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"
    RESTORE = "restore"
    CLOSE = "close"
    FULLSCREEN = "fullscreen"
    EXIT_FULLSCREEN = "exit_fullscreen"
    MOVE = "move"
    RESIZE = "resize"
    SNAP_LEFT = "snap_left"
    SNAP_RIGHT = "snap_right"
    SNAP_LAYOUT = "snap_layout"
    SWITCH_WINDOW = "switch_window"
    SWITCH_TAB = "switch_tab"
    CLOSE_TAB = "close_tab"
    REOPEN_TAB = "reopen_tab"


_SYNONYMS = {
    "minimize": WindowControl.MINIMIZE, "minimise": WindowControl.MINIMIZE,
    "kecilkan": WindowControl.MINIMIZE, "minimalkan": WindowControl.MINIMIZE,
    "maximize": WindowControl.MAXIMIZE, "maximise": WindowControl.MAXIMIZE,
    "perbesar": WindowControl.MAXIMIZE, "maksimalkan": WindowControl.MAXIMIZE,
    "restore": WindowControl.RESTORE, "kembalikan": WindowControl.RESTORE,
    "close": WindowControl.CLOSE, "tutup": WindowControl.CLOSE,
    "fullscreen": WindowControl.FULLSCREEN,
    "layar penuh": WindowControl.FULLSCREEN,
    "exit fullscreen": WindowControl.EXIT_FULLSCREEN,
    "keluar layar penuh": WindowControl.EXIT_FULLSCREEN,
    "snap left": WindowControl.SNAP_LEFT, "snap kiri": WindowControl.SNAP_LEFT,
    "snap right": WindowControl.SNAP_RIGHT, "snap kanan": WindowControl.SNAP_RIGHT,
    "switch window": WindowControl.SWITCH_WINDOW,
    "ganti jendela": WindowControl.SWITCH_WINDOW,
    "switch tab": WindowControl.SWITCH_TAB, "ganti tab": WindowControl.SWITCH_TAB,
    "close tab": WindowControl.CLOSE_TAB, "tutup tab": WindowControl.CLOSE_TAB,
    "reopen tab": WindowControl.REOPEN_TAB,
    "buka lagi tab": WindowControl.REOPEN_TAB,
}


def normalize(phrase: str) -> WindowControl | None:
    return _SYNONYMS.get(phrase.strip().lower())


@dataclass
class ControlResult:
    ok: bool
    control: WindowControl
    detail: str = ""
    needs_confirmation: bool = False
    decision: CloseDecision | None = None


class WindowControlAdapter:
    platform_name = "unknown"

    def capabilities(self) -> dict[WindowControl, bool]:
        return {c: False for c in WindowControl}

    def execute(self, control: WindowControl, win: WindowInfo) -> ControlResult:
        return ControlResult(False, control,
                             f"{control.value} not supported on {self.platform_name}")


class QtOwnWindowAdapter(WindowControlAdapter):
    """Priority source 1 — exact control of J.A.R.V.I.S-owned windows via
    Qt itself; no accessibility guessing needed."""

    platform_name = "qt"

    def __init__(self, qt_window):
        self._win = qt_window

    def capabilities(self) -> dict[WindowControl, bool]:
        caps = {c: False for c in WindowControl}
        for c in (WindowControl.MINIMIZE, WindowControl.MAXIMIZE,
                  WindowControl.RESTORE, WindowControl.CLOSE,
                  WindowControl.FULLSCREEN, WindowControl.EXIT_FULLSCREEN,
                  WindowControl.MOVE, WindowControl.RESIZE):
            caps[c] = True
        return caps

    def execute(self, control: WindowControl, win: WindowInfo | None = None
                ) -> ControlResult:
        w = self._win
        try:
            if control is WindowControl.MINIMIZE:
                w.showMinimized()
            elif control is WindowControl.MAXIMIZE:
                w.showMaximized()
            elif control is WindowControl.RESTORE:
                w.showNormal()
            elif control is WindowControl.FULLSCREEN:
                w.showFullScreen()
            elif control is WindowControl.EXIT_FULLSCREEN:
                w.showNormal()
            elif control is WindowControl.CLOSE:
                w.close()          # graceful — closeEvent runs shutdown hooks
            else:
                return ControlResult(False, control,
                                     f"{control.value} not implemented for own window")
            return ControlResult(True, control, "qt")
        except Exception as e:
            return ControlResult(False, control, str(e)[:120])


class WindowsWindowControlAdapter(WindowControlAdapter):
    platform_name = "windows"

    def __init__(self):
        try:
            import pygetwindow as gw
            self._gw = gw
            self.supported = True
        except ImportError:
            self._gw = None
            self.supported = False

    def capabilities(self) -> dict[WindowControl, bool]:
        caps = {c: False for c in WindowControl}
        if not self.supported:
            return caps
        for c in (WindowControl.MINIMIZE, WindowControl.MAXIMIZE,
                  WindowControl.RESTORE, WindowControl.CLOSE,
                  WindowControl.MOVE, WindowControl.RESIZE,
                  WindowControl.SWITCH_WINDOW):
            caps[c] = True
        try:
            import pyautogui  # noqa: F401 — snap uses the OS Win+Arrow shortcut
            caps[WindowControl.SNAP_LEFT] = True
            caps[WindowControl.SNAP_RIGHT] = True
        except ImportError:
            pass
        return caps

    def _revalidate(self, win: WindowInfo):
        """A handle resolved even a second ago may be gone — re-find by
        title immediately before acting (§9 safety)."""
        try:
            matches = [w for w in self._gw.getAllWindows()
                       if (w.title or "").strip() == win.title]
            return matches[0] if matches else None
        except Exception:
            return None

    def execute(self, control: WindowControl, win: WindowInfo) -> ControlResult:
        if not self.supported:
            return ControlResult(False, control, "pygetwindow unavailable")
        live = self._revalidate(win)
        if live is None:
            return ControlResult(False, control,
                                 "target vanished before action (revalidation failed)")
        try:
            if control is WindowControl.MINIMIZE:
                live.minimize()
            elif control is WindowControl.MAXIMIZE:
                live.maximize()
            elif control is WindowControl.RESTORE:
                live.restore()
            elif control is WindowControl.SWITCH_WINDOW:
                live.activate()
            elif control in (WindowControl.SNAP_LEFT, WindowControl.SNAP_RIGHT):
                import pyautogui
                live.activate()
                pyautogui.hotkey("win", "left" if control is WindowControl.SNAP_LEFT
                                 else "right")
            else:
                return ControlResult(False, control,
                                     f"{control.value} unsupported via this adapter")
            return ControlResult(True, control, "win32")
        except Exception as e:
            return ControlResult(False, control, str(e)[:120])


class UnsupportedWindowControlAdapter(WindowControlAdapter):
    """Honest degradation for platforms without a real adapter yet —
    notably Wayland, where global window control is restricted by design."""

    def __init__(self, platform_name: str):
        self.platform_name = platform_name


def _platform_adapter() -> WindowControlAdapter:
    system = platform.system()
    if system == "Windows":
        return WindowsWindowControlAdapter()
    return UnsupportedWindowControlAdapter(system.lower() or "unknown")


class WindowControlRegistry:
    """Routes a normalized control to the right adapter, applies the
    destructive-close policy, and audits every execution."""

    def __init__(self, own_window=None, resolver: TargetResolver | None = None,
                 adapter: WindowControlAdapter | None = None):
        self._own = QtOwnWindowAdapter(own_window) if own_window is not None else None
        self._adapter = adapter or _platform_adapter()
        self._resolver = resolver or TargetResolver(self._resolver_adapter())
        self._tab_handler = None    # BrowserAgentView registers itself here

    def _resolver_adapter(self):
        from jarvis.core.target_resolver import get_adapter
        return get_adapter()

    def register_tab_handler(self, handler) -> None:
        """handler: object with switch_tab(delta)/close_current_tab()/
        reopen_last_tab() — the embedded BrowserAgentView."""
        self._tab_handler = handler

    def capabilities(self) -> dict[WindowControl, bool]:
        caps = self._adapter.capabilities()
        if self._own is not None:
            for c, ok in self._own.capabilities().items():
                caps[c] = caps.get(c, False) or ok
        for c in (WindowControl.SWITCH_TAB, WindowControl.CLOSE_TAB,
                  WindowControl.REOPEN_TAB):
            caps[c] = self._tab_handler is not None
        return caps

    def execute(self, control: WindowControl | str, target_query: str = "",
                own_window: bool = False) -> ControlResult:
        control = WindowControl(control)

        # embedded-browser tab semantics
        if control in (WindowControl.SWITCH_TAB, WindowControl.CLOSE_TAB,
                       WindowControl.REOPEN_TAB):
            if self._tab_handler is None:
                return self._audited(ControlResult(
                    False, control, "no embedded browser open"), target_query)
            try:
                if control is WindowControl.SWITCH_TAB:
                    self._tab_handler.switch_tab(1)
                elif control is WindowControl.CLOSE_TAB:
                    self._tab_handler.close_current_tab()
                else:
                    self._tab_handler.reopen_last_tab()
                return self._audited(ControlResult(True, control, "browser_agent"),
                                     target_query)
            except Exception as e:
                return self._audited(ControlResult(False, control, str(e)[:120]),
                                     target_query)

        # J.A.R.V.I.S-owned window: Qt is the exact, first-priority source
        if own_window and self._own is not None:
            return self._audited(self._own.execute(control), "own")

        # destructive close of a foreign window → full resolver policy
        if control is WindowControl.CLOSE:
            decision = decide_and_close(target_query, self._resolver)
            result = ControlResult(
                ok=decision.status == "executed", control=control,
                detail=decision.reason or (decision.result.detail
                                           if decision.result else ""),
                needs_confirmation=decision.status == "needs_confirmation",
                decision=decision)
            return self._audited(result, target_query)

        # non-destructive foreign-window controls
        targets = self._resolver.resolve(target_query)
        if not targets:
            return self._audited(ControlResult(
                False, control, "no matching window"), target_query)
        # §9: multiple matching windows always need clarification, even when
        # each individual match is high-confidence.
        if len(targets) > 1 or targets[0].confidence < 0.85:
            return self._audited(ControlResult(
                False, control, "ambiguous target — clarification required",
                needs_confirmation=True), target_query)
        result = self._adapter.execute(control, targets[0].window)
        return self._audited(result, target_query,
                             confidence=targets[0].confidence)

    def _audited(self, result: ControlResult, target: str,
                 confidence: float | None = None) -> ControlResult:
        try:
            path = config.resolve_path("logs/window_controls_audit.jsonl")
            path.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "a", encoding="utf-8") as f:
                f.write(json.dumps({
                    "ts": time.time(), "control": result.control.value,
                    "target": target, "ok": result.ok,
                    "needs_confirmation": result.needs_confirmation,
                    "confidence": confidence, "detail": result.detail[:200],
                }) + "\n")
        except OSError:
            pass
        return result
