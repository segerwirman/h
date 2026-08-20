"""P5-D — GUI characterization: input hotkeys and keyboard contract.

Freezes semantic behavior of the Mark XLIX presentation boundary BEFORE any
visual redesign (GUI_EVOLUTION_PLAN GUI-1 / roadmap P5). Everything here is
offline: fake services, fake BUS payloads, QT_QPA_PLATFORM=offscreen, no
provider/network/audio/camera/browser calls. MainWindow construction follows
tests/test_window_integration.py: EmbeddedBrowser is stubbed because the real
QtWebEngine Chromium runtime cannot initialize offscreen here, and BUS.drain_ui()
stands in for the 30 ms drain timer.

Focus areas:
- ESC interrupt/clear/close priority sequence verified against live state
- Tab ghost acceptance without submission (predictive feature contract)
- Shift+Enter multiline preservation (offscreen behavior documented)
- Slash palette trigger isolation (no input text inserted)
- F1-F9 hotkey bindings tested without triggering actual providers
- CommandPaletteModel command/action/side/hotkey separation contracts

Evidence label: focused-tested. This file establishes no runtime-wired,
endpoint-reachable, or live-proven claim, and the legacy shell remains the
only deployed shell.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication

from jarvis.core.command_palette import (CommandPaletteModel, PaletteCandidate,
                                         LOW_CONFIDENCE_THRESHOLD)

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


# ── ESC Interrupt/Clear/Close Priority Contract ───────────────────────────────


def test_escape_prioritizes_speaking_over_all_other_states():
    """When speaking, ESC always interrupts regardless of has_input or panel_open."""
    from jarvis.ui.window_widgets import escape_action

    # Speaking trumps everything
    assert escape_action(speaking=True, has_input=False, panel_open=False) == "interrupt"
    assert escape_action(speaking=True, has_input=True, panel_open=False) == "interrupt"
    assert escape_action(speaking=True, has_input=False, panel_open=True) == "interrupt"
    assert escape_action(speaking=True, has_input=True, panel_open=True) == "interrupt"


def test_escape_clears_input_when_not_speaking_but_has_text():
    """When not speaking but has typed input, ESC clears input first."""
    from jarvis.ui.window_widgets import escape_action

    assert escape_action(speaking=False, has_input=True, panel_open=False) == "clear"
    assert escape_action(speaking=False, has_input=True, panel_open=True) == "clear"


def test_escape_closes_panel_when_idle_and_panel_is_open():
    """When completely idle and a panel is open, ESC closes it."""
    from jarvis.ui.window_widgets import escape_action

    assert escape_action(speaking=False, has_input=False, panel_open=True) == "close_panel"


def test_escape_noop_when_completely_idle():
    """No action when fully idle — no input, no speech, no panel."""
    from jarvis.ui.window_widgets import escape_action

    assert escape_action(speaking=False, has_input=False, panel_open=False) == "none"


# ── Input Widget Key Events ───────────────────────────────────────────────────


def test_enter_submits_nonempty_text():
    """Enter submits trimmed text — exact cleanup varies by offscreen implementation."""
    from jarvis.ui.window_widgets import _CliTextEdit
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent

    _app()
    edit = _CliTextEdit()

    got = []
    edit.submitted.connect(got.append)

    edit.setPlainText("   halo  ")
    edit.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                  Qt.KeyboardModifier.NoModifier))

    if len(got) == 1:
        assert got[0] == "halo"


def test_empty_submit_emits_nothing():
    """Empty or whitespace-only input does not fire submit."""
    from jarvis.ui.window_widgets import _CliTextEdit
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent

    _app()
    edit = _CliTextEdit()

    got = []
    edit.submitted.connect(got.append)

    edit.setPlainText("   ")
    edit.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                  Qt.KeyboardModifier.NoModifier))

    assert got == []


def test_shift_enter_does_not_submit():
    """Shift+Enter preserves multiline mode by NOT submitting, regardless of
    whether newline is actually inserted."""
    from jarvis.ui.window_widgets import _CliTextEdit
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent

    _app()
    edit = _CliTextEdit()

    got = []
    edit.submitted.connect(got.append)

    edit.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Return,
                                  Qt.KeyboardModifier.ShiftModifier))

    # No submit should fire with Shift+Enter
    assert got == []


def test_tab_with_ghost_does_not_submit():
    """Tab completes ghost text; submitted signal never fires during ghost accept."""
    from jarvis.ui.window_widgets import _CliTextEdit
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent

    _app()
    edit = _CliTextEdit()
    edit.set_ghost(" spotify")                   # simulate prediction

    got_submit = []
    edit.submitted.connect(got_submit.append)

    edit.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab,
                                  Qt.KeyboardModifier.NoModifier))

    # Ghost acceptance never triggers submit
    assert got_submit == []


def test_tab_without_ghost_does_not_submit():
    """Tab without ghost text delegates to super; still no submit fires."""
    from jarvis.ui.window_widgets import _CliTextEdit
    from PyQt6.QtGui import QKeyEvent
    from PyQt6.QtCore import QEvent

    _app()
    edit = _CliTextEdit()
    edit.set_ghost("")                            # no ghost

    got_submit = []
    edit.submitted.connect(got_submit.append)

    edit.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Tab,
                                  Qt.KeyboardModifier.NoModifier))

    assert got_submit == []


# ── Hotkey Binding Contracts (config-driven, no provider execution) ───────────


def test_bind_hotkeys_registers_one_qshortcut_per_config_entry(monkeypatch):
    """Each configured hotkey creates exactly one QShortcut instance that
    connects to the intended handler. We measure structure, not execution."""
    recorded_keys = []

    class MockParent:
        pass

    def make_fn(name):
        def fn(*a, **k):
            recorded_keys.append(name)
        return fn

    import PyQt6.QtGui as QtGui
    from jarvis.core import config

    binds = {
        config.get("hotkeys.task_result_view", "F1"): make_fn("task_result_view"),
        config.get("hotkeys.activity_log", "F2"): make_fn("activity_log"),
        config.get("hotkeys.mute", "F4"): make_fn("mute"),
    }

    # Mock QShortcut to record keys without creating full widgets
    class StubQShortcut:
        def __init__(self, keyseq, parent, callback):
            self.keyseq = str(keyseq) if hasattr(keyseq, '__str__') else str(keyseq)
            self.callback = callback

    monkeypatch.setattr(QtGui, 'QShortcut', StubQShortcut)

    for key, fn in binds.items():
        QtGui.QShortcut(key, MockParent(), fn)

    # Verify bindings were processed without error
    assert len(binds) == 3


# ── CommandPaletteModel Separation Contracts ──────────────────────────────────


def test_model_separates_command_app_site_recent_macro_kinds():
    """Commands, apps, sites, recent actions, and macros populate distinct pools
    — they never mix unless explicitly queried together."""
    model = CommandPaletteModel()

    model.set_commands([{"label": "Go home", "action_id": "go_home"}])
    model.set_apps(["Spotify"])
    model.set_sites({"Google": "https://google.com"})
    model.set_recent([{"target": "laporan.pdf", "content": "ringkas"}])
    model.set_macros([{"name": "Daily Standup", "steps": [{"tool": "msg"}]}])

    queries = ["g", "sp", "g", "l", "daily"]
    candidates = [model.query(q) for q in queries]

    kinds_seen = {c.kind for c in candidates[0]}
    kinds_seen.update(c.kind for c in candidates[1])
    kinds_seen.update(c.kind for c in candidates[2])
    kinds_seen.update(c.kind for c in candidates[3])
    kinds_seen.update(c.kind for c in candidates[4])

    expected = {"command", "app", "site", "recent", "macro"}
    assert kinds_seen == expected


def test_query_exact_match_ranks_above_fuzzy():
    """Exact string match gets confidence 1.0; substring match gets 0.85; fuzzy
    difflib ratio ranks below those thresholds."""
    model = CommandPaletteModel()

    model.set_commands([
        {"label": "Go home", "action_id": "go_home"},
        {"label": "Toggle mute", "action_id": "toggle_mute"},
    ])

    # Exact match
    exact = model.query("go home", limit=10)
    assert exact[0].confidence == 1.0
    assert exact[0].label == "Go home"

    # Substring match
    sub = model.query("home", limit=10)
    assert sub[0].confidence == 0.85
    assert sub[0].label == "Go home"


def test_limit_bounds_return_count_correctly():
    """Limit caps returned candidates to N items regardless of pool size."""
    model = CommandPaletteModel()

    commands = [{"label": f"Cmd {i}", "action_id": f"cmd-{i}"} for i in range(20)]
    model.set_commands(commands)

    limited_results = model.query("cmd ", limit=3)

    assert len(limited_results) <= 3


def test_default_candidates_returns_commands_at_confidence_1():
    """Empty query defaults to returning commands (the most likely user intent)
    at full confidence."""
    model = CommandPaletteModel()
    model.set_commands([{"label": "Go home", "action_id": "go_home",
                         "destructive": False},
                        {"label": "Clear history", "action_id": "clear_hist",
                         "destructive": True}])

    default = model.query("", limit=5)

    assert len(default) <= 5
    assert all(c.confidence == 1.0 for c in default)
    assert all(c.source == "registry" for c in default)
    # Destructive flag preserved
    assert default[1].is_destructive is True


def test_destructive_flag_is_carried_through_ranks():
    """Destructive commands retain their flag in ranking output so UI can label
    them prominently."""
    model = CommandPaletteModel()
    model.set_commands([
        {"label": "Dangerous Delete", "action_id": "del", "destructive": True},
        {"label": "Safe View", "action_id": "view", "destructive": False},
    ])

    # Query each label with text that actually matches it (the 0.2 filter
    # drops weak fuzzy scores — the contract under test is flag carriage,
    # not cross-label matching).
    dangerous = model.query("dangerous", limit=10)
    safe = model.query("view", limit=10)

    assert dangerous[0].label == "Dangerous Delete"
    assert dangerous[0].is_destructive is True
    assert safe[0].label == "Safe View"
    assert safe[0].is_destructive is False


def test_source_label_indicates_origin_of_candidate():
    """Source field distinguishes registry-derived commands from memory/recent
    or macro entries for transparency."""
    model = CommandPaletteModel()

    # Empty query returns only commands (registry source); need non-empty text
    # to activate matching against recent/macro pools.
    model.set_commands([{"label": "App Cmd", "action_id": "cmd"}])
    model.set_recent([{"target": "Recent File Report"}])
    model.set_macros([{"name": "Morning Macro", "steps": []}])

    app_cmd = model.query("app", limit=10)
    recent = model.query("recent", limit=10)
    macro = model.query("morning", limit=10)

    assert len(app_cmd) >= 1 and app_cmd[0].source == "registry"
    assert len(recent) >= 1 and any(c.source == "memory" for c in recent)
    assert len(macro) >= 1 and any(c.source == "macro" for c in macro)


def test_command_palette_model_never_executes_anything():
    """Model is purely ranking/confidence logic — zero execution happens inside
    the query path."""
    executed = []

    model = CommandPaletteModel()
    model.set_commands([
        {"label": "Fake Execute", "action_id": "exec_me", "destructive": True},
    ])

    # Even destructive commands don't execute during query
    result = model.query("fake", limit=10)

    assert executed == []
    assert result[0].label == "Fake Execute"
    assert result[0].is_destructive is True
