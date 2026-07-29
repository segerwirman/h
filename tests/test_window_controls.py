"""WindowControlRegistry — normalized window-management semantics (§9/§26)."""
from __future__ import annotations

from jarvis.core.target_resolver import (CloseResult, TargetResolver,
                                         WindowAdapter, WindowInfo)
from jarvis.core.window_controls import (ControlResult, QtOwnWindowAdapter,
                                         UnsupportedWindowControlAdapter,
                                         WindowControl, WindowControlAdapter,
                                         WindowControlRegistry, normalize)


class _FakeResolverAdapter(WindowAdapter):
    supported = True

    def __init__(self, titles):
        self._titles = titles
        self.closed = []

    def list_windows(self):
        return [WindowInfo(object(), t) for t in self._titles]

    def foreground_window(self):
        return None

    def close_window(self, win, force=False):
        self.closed.append(win.title)
        return CloseResult(True, "graceful", "ok")


class _FakeControlAdapter(WindowControlAdapter):
    platform_name = "fake"

    def __init__(self, vanish=False):
        self.calls = []
        self._vanish = vanish

    def capabilities(self):
        caps = {c: False for c in WindowControl}
        caps[WindowControl.MINIMIZE] = True
        caps[WindowControl.MAXIMIZE] = True
        return caps

    def execute(self, control, win):
        if self._vanish:
            return ControlResult(False, control,
                                 "target vanished before action (revalidation failed)")
        self.calls.append((control, win.title))
        return ControlResult(True, control, "fake")


class _FakeQtWindow:
    def __init__(self):
        self.calls = []

    def showMinimized(self): self.calls.append("min")
    def showMaximized(self): self.calls.append("max")
    def showNormal(self): self.calls.append("normal")
    def showFullScreen(self): self.calls.append("full")
    def close(self): self.calls.append("close")


def _registry(titles, adapter=None, own=None):
    resolver = TargetResolver(_FakeResolverAdapter(titles))
    return WindowControlRegistry(own_window=own, resolver=resolver,
                                 adapter=adapter or _FakeControlAdapter())


# ── semantics (§26 test 21) ───────────────────────────────────────────────

def test_minimize_maximize_restore_close_are_separate_semantic_controls():
    controls = {normalize(p) for p in ("minimize", "maximize", "restore", "close")}
    assert controls == {WindowControl.MINIMIZE, WindowControl.MAXIMIZE,
                        WindowControl.RESTORE, WindowControl.CLOSE}
    assert len(controls) == 4                     # genuinely distinct


def test_normalization_covers_english_variants_and_indonesian():
    assert normalize("maximise") is WindowControl.MAXIMIZE
    assert normalize("kecilkan") is WindowControl.MINIMIZE
    assert normalize("tutup") is WindowControl.CLOSE
    assert normalize("snap kiri") is WindowControl.SNAP_LEFT
    assert normalize("something else") is None


# ── Qt-own window: first-priority exact source ────────────────────────────

def test_own_window_uses_qt_adapter_directly():
    fake_win = _FakeQtWindow()
    reg = _registry(["Notepad"], own=fake_win)
    result = reg.execute(WindowControl.MINIMIZE, own_window=True)
    assert result.ok and fake_win.calls == ["min"]
    reg.execute(WindowControl.FULLSCREEN, own_window=True)
    assert "full" in fake_win.calls


def test_qt_own_adapter_reports_honest_capabilities():
    caps = QtOwnWindowAdapter(_FakeQtWindow()).capabilities()
    assert caps[WindowControl.MINIMIZE] is True
    assert caps[WindowControl.SNAP_LEFT] is False    # not claimed


# ── foreign windows ───────────────────────────────────────────────────────

def test_foreign_window_minimize_resolves_target_and_executes():
    adapter = _FakeControlAdapter()
    reg = _registry(["Notepad", "Chrome"], adapter=adapter)
    result = reg.execute(WindowControl.MINIMIZE, "Notepad")
    assert result.ok
    assert adapter.calls == [(WindowControl.MINIMIZE, "Notepad")]


def test_ambiguous_target_requires_clarification_not_action():
    adapter = _FakeControlAdapter()
    reg = _registry(["Report Draft", "Report Final"], adapter=adapter)
    result = reg.execute(WindowControl.MINIMIZE, "Report")
    assert result.ok is False
    assert result.needs_confirmation is True
    assert adapter.calls == []


def test_revalidation_failure_blocks_action():
    reg = _registry(["Notepad"], adapter=_FakeControlAdapter(vanish=True))
    result = reg.execute(WindowControl.MINIMIZE, "Notepad")
    assert result.ok is False
    assert "revalidation" in result.detail


# ── destructive close routes through the resolver policy (§26 test 26) ───

def test_close_control_follows_confirmation_policy():
    reg = _registry(["Report Draft", "Report Final"])
    result = reg.execute(WindowControl.CLOSE, "Report")
    assert result.ok is False
    assert result.needs_confirmation is True
    assert result.decision is not None
    assert result.decision.status == "needs_confirmation"


def test_close_single_high_confidence_target_executes_gracefully():
    resolver_adapter = _FakeResolverAdapter(["Notepad"])
    resolver = TargetResolver(resolver_adapter)
    reg = WindowControlRegistry(resolver=resolver, adapter=_FakeControlAdapter())
    result = reg.execute(WindowControl.CLOSE, "Notepad")
    assert result.ok is True
    assert resolver_adapter.closed == ["Notepad"]    # graceful, never force


# ── honest unsupported platforms ──────────────────────────────────────────

def test_unsupported_platform_reports_honestly():
    adapter = UnsupportedWindowControlAdapter("wayland")
    assert all(v is False for v in adapter.capabilities().values())
    result = adapter.execute(WindowControl.MINIMIZE,
                             WindowInfo(object(), "Anything"))
    assert result.ok is False
    assert "wayland" in result.detail


# ── embedded-browser tab semantics ────────────────────────────────────────

class _FakeTabHandler:
    def __init__(self):
        self.calls = []

    def switch_tab(self, delta): self.calls.append(("switch", delta))
    def close_current_tab(self): self.calls.append(("close",))
    def reopen_last_tab(self): self.calls.append(("reopen",))


def test_tab_controls_require_registered_browser_agent():
    reg = _registry(["Notepad"])
    assert reg.capabilities()[WindowControl.CLOSE_TAB] is False
    result = reg.execute(WindowControl.SWITCH_TAB)
    assert result.ok is False and "no embedded browser" in result.detail

    handler = _FakeTabHandler()
    reg.register_tab_handler(handler)
    assert reg.capabilities()[WindowControl.CLOSE_TAB] is True
    assert reg.execute(WindowControl.SWITCH_TAB).ok
    assert reg.execute(WindowControl.REOPEN_TAB).ok
    assert ("switch", 1) in handler.calls and ("reopen",) in handler.calls
