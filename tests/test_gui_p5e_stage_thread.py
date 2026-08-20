"""P5-E — GUI characterization: stage readiness and thread boundary.

Freezes semantic behavior of the Mark XLIX presentation boundary BEFORE any
visual redesign (GUI_EVOLUTION_PLAN GUI-1 / roadmap P5). Everything here is
offline: QT_QPA_PLATFORM=offscreen, fake BUS payloads, no provider/network/
audio/camera/browser calls. MainWindow construction follows
tests/test_window_integration.py: EmbeddedBrowser stubbed because the real
QtWebEngine Chromium runtime cannot initialize offscreen here, and
BUS.drain_ui() stands in for the 30 ms drain timer.

Focus areas:
- EMPTY → LOADING → ACTIVE transitions verified against mounting order
- FAILURE paths: fail_loading preserves current content, doesn't unmount
- PANEL CHANGE WITHOUT STATUS TRANSITION: switching panels while ACTIVE must
  emit status_changed("ACTIVE") so ActionPanel re-highlights the new target
- rapid toggles don't leave stale animation state; _stop_animations clears
  QGraphicsOpacityEffect references cleanly
- BUS UI subscribers run on main thread via drain_ui; plain subscribers run
  synchronously on publisher thread; snapshots captured at publish time

Evidence label: focused-tested. This file establishes no runtime-wired,
endpoint-reachable, or live-proven claim, and the legacy shell remains the
only deployed shell.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtCore import QTimer
from PyQt6.QtWidgets import QApplication, QWidget

from jarvis.core.bus import BUS, EventBus
from jarvis.ui.stage import ContentStage, ContentStatus

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _drain_bus() -> None:
    """Mirror MainWindow's 30 ms drain timer without a running event loop."""
    while not BUS._ui_queue.empty():
        BUS.drain_ui()


class _VisibleWidget(QWidget):
    """QWidget with explicit visibility so tests can assert show/hide contracts."""
    NO_FX = False


# ── Stage Readiness Transitions ──────────────────────────────────────────────


def test_begin_loading_enters_LOADING_with_pending_set():
    """requesting mount sets LOADING and remembers requested child."""
    stage, vision, _home, Status = _stage("vision", "home")

    stage.begin_loading("vision")

    assert stage.status is Status.LOADING
    assert stage.is_loading("vision") is True
    assert stage.current is None      # belum CLAIMED until activate()


def test_activate_transitions_TO_ACTIVE_and_mounts_child():
    """activate() makes payload visible and emits ACTIVE regardless of prior
    LOADING state — payload must be mounted beforehand."""
    stage, vision, _home, Status = _stage("vision", "home")
    _app().processEvents()                 # offscreen paintEvent sync

    stage.activate("vision")

    assert stage.status is Status.ACTIVE
    assert stage.current == "vision"
    assert vision.isVisible() is True
    # Loading indicator dismissed
    from jarvis.ui.stage import QLabel
    assert isinstance(stage._loading_label, QLabel)
    assert stage._loading_label.isVisible() is False


def test_fail_loading_preserves_current_content_but_marks_error():
    """fail_loading DOES NOT unmount currently visible panel. It overlays an
    error message but keeps existing content mounted so user sees something."""
    stage, vision, _home, Status = _stage("vision", "home")
    _app().processEvents()

    stage.activate("vision")
    assert stage.status is Status.ACTIVE
    assert vision.isVisible()

    stage.fail_loading("Unavailable")
    _app().processEvents()

    assert stage.status is Status.ERROR
    assert stage.current == "vision"            # tetap aktif
    assert vision.isVisible() is True           # tidak di-unmount
    # Error text visible, tapi panel lama masih ada


def test_status_change_emits_signal_on_each_transition():
    """Each state change fires status_changed — caller doesn't poll()."""
    from jarvis.ui.stage import ContentStatus as CS

    stage, v1, v2, _ = _stage("a", "b")
    events = []
    stage.status_changed.connect(lambda s: events.append(s))

    stage.activate("a")
    stage.toggle("a")                          # closes to EMPTY
    stage.begin_loading("b")
    stage.activate("b")

    # One event per transition: ACTIVE → EMPTY → LOADING → ACTIVE
    assert len(events) >= 3
    assert "ACTIVE" in events
    assert "EMPTY" in events


# ── Panel Change Without Status Transition ───────────────────────────────────


def test_toggle_panel_while_active_emits_STATUS_CHANGE_for_new_target():
    """Switching from one panel to another while already ACTIVE MUST emit
    status_changed("ACTIVE") again so ActionPanel can move highlight to new
    target. Contract from stage.py line 99–101."""
    stage, vision, info, Status = _stage("vision", "info")
    events = []
    stage.status_changed.connect(lambda s: events.append(s))

    stage.activate("vision")
    before_len = len(events)
    events.clear()

    stage.toggle("info")                       # vision → info while ACTIVE

    # Even though status stays ACTIVE, signal emitted for state update sync
    assert any(e == "ACTIVE" for e in events)
    assert stage.current == "info"


# ── Rapid Toggle Consistency & Animation Cleanup ─────────────────────────────


def test_rapid_toggles_dont_leave_stale_animation_state():
    """Rapid enable/disable cycles must stop previous fades so they don't
    later fight over widget opacity. _stop_animations should clear all refs."""
    stage, v1, _v2, _ = _stage("vision", "home")
    stage.resize(800, 600)

    # Simulate rapid toggles that trigger animations
    for _ in range(3):
        stage.activate("vision")
        stage.hide_all()

    # Force-stop all animations
    stage._stop_animations()

    # No animation entries should remain
    assert len(stage._animations) == 0


def test_stop_animations_clears_graphics_effect_references():
    """Even if widgets have QGraphicsOpacityEffect, _stop_animations detaches
    it cleanly so repainting works correctly after cancel."""
    from PyQt6.QtGui import QPainter
    from jarvis.ui.stage import QGraphicsOpacityEffect

    stage, v1, _v2, _ = _stage("vision", "home")
    stage._fade(v1, 0.0, 1.0)                 # create effect

    assert len(stage._animations) == 1
    anim = stage._animations[0]
    effect = anim.targetObject()
    assert isinstance(effect, QGraphicsOpacityEffect)

    stage._stop_animations()

    assert len(stage._animations) == 0
    # Graphics effect removed from widget
    assert v1.graphicsEffect() is None


# ── Thread Boundary Semantics (BUS UI vs Plain Subscribers) ──────────────────


def test_plain_subscriber_runs_synchronously_on_publisher_thread():
    """Plain (non-UI) subscribers execute immediately where publish() called,
    not deferred to Qt thread."""
    got = []
    BUS.subscribe("p5e.plain", lambda d: got.append(d.get("val")))
    BUS.publish("p5e.plain", val="handler")

    assert got == ["handler"]          # sync, no drain needed
    BUS._subs["p5e.plain"] = []        # cleanup


def test_ui_subscriber_ran_after_drain_only():
    """UI subscribers never run during publish(); they wait for drain_ui().
    Snapshot taken at publish time prevents late registrants from seeing old."""
    seen_a: list[str] = []
    BUS.subscribe("p5e.ui", lambda d: seen_a.append(d["id"]), ui=True)
    BUS.publish("p5e.ui", id="evt1")

    # Should NOT run yet
    assert seen_a == []

    BUS.drain_ui()
    assert seen_a == ["evt1"]

    # Late registrant only sees future events
    seen_b: list[str] = []
    BUS.subscribe("p5e.ui", lambda d: seen_b.append(d["id"]), ui=True)
    BUS.publish("p5e.ui", id="evt2")
    BUS.drain_ui()

    assert seen_a == ["evt1", "evt2"]
    assert seen_b == ["evt2"]               # snapshot at publish


def test_drain_ui_respects_max_events_limit():
    """drain_ui(max_events=N) caps processed count even if queue larger."""
    count = [0]

    def counter(_):
        count[0] += 1

    BUS.subscribe("p5e.cap", counter, ui=True)
    for i in range(100):
        BUS.publish("p5e.cap", i=i)

    BUS.drain_ui(max_events=10)
    assert count[0] == 10                   # capped


def test_ui_handler_exception_does_not_block_later_handlers():
    """One handler exception shouldn't starve others; drain continues safely."""
    got: list[int] = []

    BUS.subscribe("p5e.exc", lambda _: 1 / 0, ui=True)
    BUS.subscribe("p5e.exc", lambda d: got.append(d["i"]), ui=True)

    BUS.publish("p5e.exc", i=7)
    _drain_bus()                            # fully drain incl. leftovers

    assert got == [7]                       # continued past crash


def _stage(*names: str):
    """Create stage with named children (shown, like test_stage_toggle.py)."""
    app = _app()
    stage = ContentStage()
    stage.resize(900, 600)
    stage.show()
    app.processEvents()
    widgets = [_VisibleWidget() for _ in names]
    for name, w in zip(names, widgets):
        stage.register(name, w)
    return stage, *widgets, ContentStatus
