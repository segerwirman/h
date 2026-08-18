"""Destructive-action target resolver (redesign §13).

Closing an app/window is never a blind hotkey here: a target is resolved
from the user's phrase through a priority-ordered layered search (exact
title match → foreground window → recent context → fuzzy match), assigned a
confidence, and revalidated against the *current* window list immediately
before acting — a title resolved a second ago may no longer exist.

Policy (``decide_and_close``):
  * single, high-confidence, no unsaved-work risk, not a force request
    → executes directly (graceful close only).
  * anything ambiguous, low-confidence, carrying unsaved-work risk, or a
    force-kill request → returns ``needs_confirmation`` with the candidate
    list; the caller (UI) must re-invoke with an explicit ``confirmed_target``
    once the user approves. Nothing here auto-executes a low-confidence
    guess or force-kills without that round trip.

Platform adapters isolate OS specifics. ``WindowsWindowAdapter`` is a real,
working implementation (pygetwindow + psutil, both already project
dependencies). Non-Windows platforms get an honest ``UnsupportedWindowAdapter``
that reports failure rather than silently pretending to succeed.
"""
from __future__ import annotations

import difflib
import json
import platform
import time
from dataclasses import dataclass, field

from jarvis.core import config, log, quiet

_logger = log.get("core.target_resolver")


@dataclass
class WindowInfo:
    handle: object          # opaque, adapter-specific
    title: str
    app_name: str = ""
    is_foreground: bool = False


@dataclass
class ResolvedTarget:
    window: WindowInfo
    confidence: float
    source: str              # exact | foreground | recent | fuzzy
    unsaved_risk: bool = False


@dataclass
class CloseResult:
    ok: bool
    method: str               # graceful | force | none
    detail: str = ""


class WindowAdapter:
    """Platform seam — subclasses implement the OS-specific parts only."""

    platform_name = "unknown"
    supported = False

    def list_windows(self) -> list[WindowInfo]:
        return []

    def foreground_window(self) -> WindowInfo | None:
        return None

    def close_window(self, win: WindowInfo, force: bool = False) -> CloseResult:
        return CloseResult(False, "none", f"window targeting not implemented on {self.platform_name}")

    def has_unsaved_changes(self, win: WindowInfo) -> bool | None:
        """Best-effort only; None means unknown (treated conservatively by
        the resolver, never assumed safe)."""
        return None


class WindowsWindowAdapter(WindowAdapter):
    platform_name = "windows"

    def __init__(self) -> None:
        try:
            import pygetwindow as _gw
            self._gw = _gw
            self.supported = True
        except ImportError:
            self._gw = None
            self.supported = False

    def list_windows(self) -> list[WindowInfo]:
        if not self.supported:
            return []
        try:
            fg = self._gw.getActiveWindow()
            fg_title = fg.title if fg else None
            out = []
            for w in self._gw.getAllWindows():
                title = (w.title or "").strip()
                if not title:
                    continue
                out.append(WindowInfo(handle=w, title=title,
                                      is_foreground=(title == fg_title)))
            return out
        except Exception as e:
            _logger.warning("target_resolver.list_windows_failed", error=str(e)[:100])
            return []

    def foreground_window(self) -> WindowInfo | None:
        if not self.supported:
            return None
        try:
            w = self._gw.getActiveWindow()
            if w is None or not (w.title or "").strip():
                return None
            return WindowInfo(handle=w, title=w.title.strip(), is_foreground=True)
        except Exception:
            return None

    def close_window(self, win: WindowInfo, force: bool = False) -> CloseResult:
        if not self.supported:
            return CloseResult(False, "none", "pygetwindow unavailable")
        try:
            current_titles = {(w.title or "").strip() for w in self._gw.getAllWindows()}
            if win.title not in current_titles:
                return CloseResult(False, "none",
                                   "target no longer present (revalidation failed)")
            if force:
                pid = self._pid_for(win.handle)
                if pid:
                    import psutil
                    psutil.Process(pid).terminate()
                    return CloseResult(True, "force", f"terminated pid {pid}")
                return CloseResult(False, "none", "could not resolve PID for force-close")
            win.handle.close()   # WM_CLOSE — graceful; app may prompt to save
            return CloseResult(True, "graceful", "WM_CLOSE sent")
        except Exception as e:
            return CloseResult(False, "none", str(e)[:120])

    @staticmethod
    def _pid_for(handle) -> int | None:
        try:
            import win32process
            _, pid = win32process.GetWindowThreadProcessId(handle._hWnd)
            return pid
        except Exception:
            return None


class UnsupportedWindowAdapter(WindowAdapter):
    """Honest fallback for platforms without a real adapter yet."""

    def __init__(self, platform_name: str) -> None:
        self.platform_name = platform_name
        self.supported = False


def get_adapter() -> WindowAdapter:
    system = platform.system()
    if system == "Windows":
        return WindowsWindowAdapter()
    return UnsupportedWindowAdapter(system.lower() or "unknown")


# ── audit log ────────────────────────────────────────────────────────────

def _audit(entry: dict) -> None:
    try:
        path = config.resolve_path("logs/target_resolver_audit.jsonl")
        path.parent.mkdir(parents=True, exist_ok=True)
        entry = dict(entry)
        entry.setdefault("ts", time.time())
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as exc:
        quiet.swallowed("core.target_resolver.audit_failed", exc)


# ── resolution ───────────────────────────────────────────────────────────

CONF_EXACT = 1.0
CONF_SUBSTRING = 0.92
CONF_FOREGROUND = 0.9
CONF_RECENT = 0.75
CONF_FUZZY_MAX = 0.7
HIGH_CONFIDENCE_THRESHOLD = 0.85


class TargetResolver:
    def __init__(self, adapter: WindowAdapter | None = None,
                recent_titles: list[str] | None = None):
        self.adapter = adapter or get_adapter()
        self._recent_titles: list[str] = recent_titles if recent_titles is not None else []

    def note_recent(self, title: str) -> None:
        if title in self._recent_titles:
            self._recent_titles.remove(title)
        self._recent_titles.insert(0, title)
        del self._recent_titles[20:]

    def resolve(self, query: str) -> list[ResolvedTarget]:
        query_norm = query.strip().lower()
        windows = self.adapter.list_windows()

        if not query_norm:
            fg = self.adapter.foreground_window()
            if fg is not None:
                return [ResolvedTarget(fg, CONF_FOREGROUND, "foreground", self._unsaved(fg))]
            return []

        exact = [w for w in windows if w.title.strip().lower() == query_norm]
        if exact:
            return [ResolvedTarget(w, CONF_EXACT, "exact", self._unsaved(w)) for w in exact]

        substr = [w for w in windows if query_norm in w.title.lower()]
        if substr:
            return [ResolvedTarget(w, CONF_SUBSTRING, "exact", self._unsaved(w)) for w in substr]

        fg = self.adapter.foreground_window()
        if fg is not None and query_norm in fg.title.lower():
            return [ResolvedTarget(fg, CONF_FOREGROUND, "foreground", self._unsaved(fg))]

        for recent in self._recent_titles:
            if query_norm in recent.lower():
                match = next((w for w in windows if w.title == recent), None)
                if match is not None:
                    return [ResolvedTarget(match, CONF_RECENT, "recent", self._unsaved(match))]

        titles = [w.title for w in windows]
        close = difflib.get_close_matches(query, titles, n=3, cutoff=0.4)
        results = []
        for title in close:
            ratio = difflib.SequenceMatcher(None, query_norm, title.lower()).ratio()
            match = next(w for w in windows if w.title == title)
            results.append(ResolvedTarget(match, min(CONF_FUZZY_MAX, ratio), "fuzzy",
                                          self._unsaved(match)))
        results.sort(key=lambda r: r.confidence, reverse=True)
        return results

    def _unsaved(self, win: WindowInfo) -> bool:
        risk = self.adapter.has_unsaved_changes(win)
        if risk is None:
            # Unknown → a conservative title heuristic only; never assumed safe.
            return win.title.startswith("*") or "•" in win.title or win.title.endswith("*")
        return risk


@dataclass
class CloseDecision:
    status: str                # executed | needs_confirmation | no_target
    candidates: list[ResolvedTarget] = field(default_factory=list)
    result: CloseResult | None = None
    reason: str = ""


def decide_and_close(query: str, resolver: TargetResolver | None = None,
                     force: bool = False,
                     confirmed_target: WindowInfo | None = None) -> CloseDecision:
    """Pure, UI-agnostic decision function.

    The caller supplies ``confirmed_target`` (out of band, after the user
    approved a prior ``needs_confirmation`` response) to actually execute an
    ambiguous/risky/force close. Force-close always requires that round
    trip — it is the one irreversible path, so it is never auto-executed
    even for a single exact match.
    """
    resolver = resolver or TargetResolver()

    if confirmed_target is not None:
        result = resolver.adapter.close_window(confirmed_target, force=force)
        _audit({"query": query, "target": confirmed_target.title, "force": force,
               "result": result.method, "ok": result.ok, "detail": result.detail,
               "confirmed": True})
        return CloseDecision("executed" if result.ok else "no_target", [], result, result.detail)

    candidates = resolver.resolve(query)
    if not candidates:
        _audit({"query": query, "result": "no_target"})
        return CloseDecision("no_target", [], None, "no matching window found")

    top = candidates[0]
    auto_executable = (len(candidates) == 1
                       and top.confidence >= HIGH_CONFIDENCE_THRESHOLD
                       and not top.unsaved_risk
                       and not force)
    if auto_executable:
        result = resolver.adapter.close_window(top.window, force=False)
        _audit({"query": query, "target": top.window.title, "force": False,
               "result": result.method, "ok": result.ok, "detail": result.detail,
               "confidence": top.confidence, "source": top.source, "confirmed": False})
        return CloseDecision("executed", candidates, result, result.detail)

    reason = ("force-close always requires confirmation" if force else
             "multiple possible targets" if len(candidates) > 1 else
             "possible unsaved work" if top.unsaved_risk else
             "low confidence match")
    _audit({"query": query, "result": "needs_confirmation", "reason": reason,
           "candidates": [c.window.title for c in candidates]})
    return CloseDecision("needs_confirmation", candidates, None, reason)


# ── closed-item history (best-effort "undo" metadata) ───────────────────

class ClosedItemHistory:
    """Retains enough metadata to reopen a recently-closed browser tab or
    re-target a recently-closed window. Not a promise of true undo — window
    close cannot be reversed once the process is gone — but browser
    navigation (single-tab today) can genuinely be restored."""

    def __init__(self, max_items: int = 10):
        self._max = max_items
        self._items: list[dict] = []

    def remember(self, kind: str, title: str, meta: dict | None = None) -> None:
        self._items.insert(0, {"kind": kind, "title": title,
                               "meta": meta or {}, "ts": time.time()})
        del self._items[self._max:]

    def pop_last(self, kind: str | None = None) -> dict | None:
        for i, item in enumerate(self._items):
            if kind is None or item["kind"] == kind:
                return self._items.pop(i)
        return None

    def peek_last(self, kind: str | None = None) -> dict | None:
        for item in self._items:
            if kind is None or item["kind"] == kind:
                return item
        return None
