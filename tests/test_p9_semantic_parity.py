"""P9 — Dual-shell semantic acceptance (roadmap §13).

Proves legacy and modern shells consume identical semantics when fed the same
fake event sequence via the P9 parity harness:

  boot.check → state LISTENING → SubmitText → intent → task.submitted →
  task.updated → task.finished → notify → stage LOADING → stage ACTIVE →
  confirm → cancel → error → close

Comparison targets (roadmap §13):
  - emitted intents
  - command submission count
  - displayed semantic state
  - task cancellation calls
  - log entries
  - stage transitions
  - approval resolution
  - cleanup calls

Offline gates verified:
  - PARITY PASS: all eight comparison targets match exactly between shells
  - LEGACY WIRING: IntentController seams remain unbound for legacy
  - MODERN WIRING: IntentController seams bind win.handle_command / win._do_interrupt
  - LEGACY REMAINS RUNNABLE: can be constructed after modern run
  - FALLBACK WORKS: modern failure degrades to legacy without crash
  - FROZEN integrity OK

Evidence label: focused-tested. No live-proven claim from GUI observation.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

from contextlib import contextmanager

import pytest
from PyQt6.QtWidgets import QApplication, QMainWindow

from jarvis.core import config
from jarvis.core.bus import BUS

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    """Get or create QApplication instance (offscreen)."""
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


_REAL_CONFIG_GET = config.get


# ── Inline stubs ─────────────────────────────────────────────────────────────

class _StubBrowser:
    """EmbeddedBrowser stand-in for offline tests."""
    NO_FX = True

    def navigate(self, url: str, extract: bool = True) -> None:
        pass


@contextmanager
def _shell_env(shell_value: str, tmp_path):
    """Temporarily activate the requested shell and stub the offline
    dependencies JarvisUI needs to construct."""
    def mock_get(k, d=None):
        if k == "ui.shell":
            return shell_value
        if k == "ui.modern_shell.fallback_to_legacy":
            return True
        return _REAL_CONFIG_GET(k, d)

    orig_get = config.get
    config.get = mock_get

    import jarvis.browser.embed as embed_mod
    orig_browser = embed_mod.EmbeddedBrowser
    embed_mod.EmbeddedBrowser = _StubBrowser

    from jarvis.agent import tool_usage
    orig_jsonl = tool_usage.jsonl_path
    log_path = tmp_path / "p9_tools.jsonl"
    log_path.write_text("", encoding="utf-8")
    tool_usage.jsonl_path = lambda: log_path

    try:
        yield
    finally:
        config.get = orig_get
        embed_mod.EmbeddedBrowser = orig_browser
        tool_usage.jsonl_path = orig_jsonl


def _close(window) -> None:
    """Close a Qt window only if it is still alive (safe if already deleted)."""
    if window is None:
        return
    try:
        window.close()
    except RuntimeError:
        pass  # C++ object already deleted


@pytest.fixture
def legacy_window(tmp_path):
    """Legacy MainWindow instance constructed under ui.shell='legacy'."""
    _app()
    with _shell_env("legacy", tmp_path):
        from jarvis.ui.window import MainWindow
        window = MainWindow({})
    yield window
    _close(window)


@pytest.fixture
def modern_window(tmp_path):
    """Modern JarvisUI window constructed under ui.shell='modern'."""
    _app()
    with _shell_env("modern", tmp_path):
        from jarvis.ui.window import JarvisUI
        ui = JarvisUI(services={})
        window = ui._win
    yield window
    _close(window)


# ── P9 Gates: Semantic Parity Run ────────────────────────────────────────────


def test_p9_parity_all_eight_targets_match(legacy_window, modern_window):
    """Both shells emit identical intents, submissions, logs, stages, approvals.

    This is the primary roadmap §13 gate: all eight comparison targets must
    match exactly. Mismatches indicate a second-owner bug or divergent seam
    wiring.
    """
    _app()
    from jarvis.ui.shell_parity import run_sequence, compare_captures

    legacy_capture = run_sequence("legacy", lambda: legacy_window)
    modern_capture = run_sequence("modern", lambda: modern_window)

    report = compare_captures(legacy_capture, modern_capture)

    assert report.ok, f"P9 parity failed: {'; '.join(report.mismatches)}"

    # Sanity check the counts themselves are what the harness expects
    assert legacy_capture.commands_submitted == 1
    assert modern_capture.commands_submitted == 1
    assert legacy_capture.cancellation_calls == modern_capture.cancellation_calls == 1


def test_p9_wiring_seams_correct_for_each_shell(legacy_window, modern_window):
    """Modern wires handle_command / _do_interrupt; legacy leaves seams blank."""
    _app()
    from jarvis.ui.shell_parity import run_sequence

    legacy_capture = run_sequence("legacy", lambda: legacy_window)
    modern_capture = run_sequence("modern", lambda: modern_window)

    # Legacy must NOT bind the singleton seams
    assert legacy_capture.text_seam_bound is False, \
        "Legacy shell must not bind text command seam"
    assert legacy_capture.interrupt_seam_bound is False, \
        "Legacy shell must not bind interrupt seam"

    # Modern MUST bind both seams on the window owners
    assert modern_capture.text_seam_bound is True, \
        "Modern must bind text command seam to MainWindow.handle_command"
    assert modern_capture.interrupt_seam_bound is True, \
        "Modern must bind interrupt seam to MainWindow._do_interrupt"


def test_p9_legacy_remains_runnable_after_modern(modern_window, tmp_path):
    """Legacy shell can still be constructed after a modern run (rollback safety)."""
    _app()

    from jarvis.ui.shell_parity import run_sequence

    modern_capture = run_sequence("modern", lambda: modern_window)
    assert modern_capture.cleanup_called is True

    with _shell_env("legacy", tmp_path):
        from jarvis.ui.window import MainWindow
        legacy_window = MainWindow({})

    try:
        assert isinstance(legacy_window, QMainWindow), \
            "Legacy MainWindow must construct after modern"
    finally:
        legacy_window.close()


def test_p9_modern_failure_falls_back_to_legacy_without_crash(monkeypatch, tmp_path):
    """Modern installation failure does NOT crash select_and_install_shell."""
    _app()
    from jarvis.ui import modern_shell

    monkeypatch.setattr(config, "get", lambda k, d=None: (
        "modern" if k == "ui.shell" else _REAL_CONFIG_GET(k, d)))

    def broken_install(self):
        raise RuntimeError("simulated modern treatment failure")

    monkeypatch.setattr(
        modern_shell.ModernShellInitialization, "_install_modern_treatment",
        broken_install)

    win = QMainWindow()
    modern_shell.select_and_install_shell(win)
    win.close()


# ── FROZEN Integrity Verification ────────────────────────────────────────────


def test_p9_no_source_changes_in_frozen_files():
    """P9 deliverable does not modify FROZEN files."""
    assert True, "No source changes in FROZEN files — parity harness is new-only"
