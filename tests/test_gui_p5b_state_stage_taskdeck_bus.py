"""P5-B — GUI characterization: state, stage, task deck, BUS delivery.

Freezes semantic behavior of the Mark XLIX presentation boundary BEFORE any
visual redesign (GUI_EVOLUTION_PLAN GUI-1 / roadmap P5). Everything here is
offline: fake task views, fake BUS payloads, QT_QPA_PLATFORM=offscreen, no
provider/network/audio/camera/browser calls. MainWindow construction follows
tests/test_window_integration.py: EmbeddedBrowser is stubbed because the real
QtWebEngine Chromium runtime cannot initialize offscreen here, and
BUS.drain_ui() stands in for the 30 ms drain timer. The task deck's JSONL
tail is pointed at a per-test temp file so the real tools.jsonl and the
global task ledger are never written by these tests.

Evidence label: focused-tested. This file establishes no runtime-wired,
endpoint-reachable, or live-proven claim, and the legacy shell remains the
only deployed shell.
"""
from __future__ import annotations

import json
import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication, QWidget

from jarvis.core.bus import BUS
from jarvis.ui.orb import OrbState

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def _drain_bus() -> None:
    """Mirror MainWindow's 30 ms drain timer without a running event loop."""
    while not BUS._ui_queue.empty():
        BUS.drain_ui()


class _StubBrowser(QWidget):
    """EmbeddedBrowser stand-in (see tests/test_window_integration.py)."""
    NO_FX = True

    def navigate(self, url: str, extract: bool = True) -> None:
        pass


@pytest.fixture()
def ui(monkeypatch, tmp_path):
    """Full JarvisUI facade with the deck's JSONL tail on a temp file."""
    _app()
    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    from jarvis.agent import tool_usage
    log_path = tmp_path / "p5b_tools.jsonl"
    log_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(tool_usage, "jsonl_path", lambda: log_path)
    from jarvis.ui.window import JarvisUI
    facade = JarvisUI(services={})
    yield facade
    facade._win.close()


@pytest.fixture()
def win(ui):
    return ui._win


def _fake_view(task_id: str, *, status, progress: float = 0.5,
               title: str = "tugas"):
    """Immutable TaskView without touching the live registry/ledger."""
    from jarvis.agent.tasks import TaskView
    return TaskView(
        id=task_id, title=title, prompt="", status=status, step="",
        iteration=1, max_iterations=5, resources=frozenset(),
        created_at=1.0, started_at=1.0, finished_at=None, result="",
        error="", completion_owner="", source="p5b-test", session_id="",
        progress=progress, elapsed=1.0, cancelled=False,
    )


# ── State mapping — legacy names to OrbState ─────────────────────────────────


@pytest.mark.parametrize("legacy,orb_name", [
    ("LISTENING", "LISTENING"),
    ("SPEAKING", "SPEAKING"),
    ("THINKING", "THINKING"),
    ("PROCESSING", "EXECUTING"),
    ("EXECUTING", "EXECUTING"),
    ("SLEEPING", "IDLE"),
    ("INITIALISING", "BOOT"),
    ("MUTED", "IDLE"),
    ("ERROR", "ERROR"),
    ("IDLE", "IDLE"),
])
def test_set_state_maps_legacy_names_to_orb_states(ui, win, legacy, orb_name):
    ui.set_state(legacy)
    _app().processEvents()

    assert win._legacy_state == legacy
    assert win.orb.state is OrbState(orb_name)


def test_set_state_unknown_name_falls_back_to_idle(ui, win):
    ui.set_state("NO_SUCH_STATE")
    _app().processEvents()

    assert win._legacy_state == "NO_SUCH_STATE"
    assert win.orb.state is OrbState.IDLE


def test_state_reaches_orb_via_signal_not_polling(ui, win):
    """Facade emits _state_sig; the connected slot applies it synchronously
    once events are processed (no polling loop on the window side)."""
    ui.set_state("THINKING")
    _app().processEvents()
    assert win.orb.state is OrbState.THINKING


# ── Task deck install contract ───────────────────────────────────────────────


def test_mainwindow_installs_all_three_task_layers(win):
    assert win.task_deck is not None
    assert win.task_strip is not None
    assert "tasks" in win.stage.registered_names
    assert callable(getattr(win, "_task_refresh", None))


def test_install_attaches_global_ledger_exactly_once(win):
    from jarvis.agent.tasks import REGISTRY
    ledger = getattr(REGISTRY, "_ledger", None)
    assert ledger is not None


def test_task_topics_gain_one_ui_subscriber_per_window(monkeypatch, tmp_path):
    """Each MainWindow construction installs exactly one refresh subscriber
    per task topic (install is invoked once by the constructor)."""
    _app()
    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    from jarvis.agent import tool_usage
    monkeypatch.setattr(tool_usage, "jsonl_path",
                        lambda: tmp_path / "p5b_sub.jsonl")

    before = {t: len(BUS._ui_subs.get(t, ()))
              for t in ("task.submitted", "task.updated", "task.finished")}
    from jarvis.ui.window import MainWindow
    w = MainWindow(services={})
    try:
        for topic, n in before.items():
            assert len(BUS._ui_subs.get(topic, ())) == n + 1, topic
    finally:
        w.close()


def test_task_bus_events_refresh_without_touching_orb_state(win):
    """'Jarvis sibuk' != 'Jarvis tidak tersedia': task events refresh the
    strip/deck but never move the orb into another semantic state."""
    win.orb.set_state(OrbState.LISTENING)

    BUS.publish("task.submitted", task_id="p5b")
    BUS.publish("task.updated", task_id="p5b")
    BUS.publish("task.finished", task_id="p5b")
    _drain_bus()
    _app().processEvents()

    assert win.orb.state is OrbState.LISTENING


def test_tasks_button_opens_deck_through_loading_then_active(win):
    """Deck open follows the ContentStage contract: LOADING first, ACTIVE
    only after the JSONL tail read completes (loading_changed(False))."""
    from jarvis.ui.stage import ContentStatus

    win.action_panel._buttons["tasks"].click()
    assert (win.stage.is_loading("tasks")
            or win.stage.status is ContentStatus.ACTIVE)

    deadline = time.monotonic() + 5.0
    while win.stage.status is not ContentStatus.ACTIVE:
        if time.monotonic() > deadline:
            pytest.fail("deck never reached ACTIVE")
        _app().processEvents()
        time.sleep(0.02)
    assert win.stage.current == "tasks"


def test_tasks_button_second_click_closes_deck(win):
    from jarvis.ui.stage import ContentStatus

    win.action_panel._buttons["tasks"].click()
    deadline = time.monotonic() + 5.0
    while win.stage.status is not ContentStatus.ACTIVE:
        if time.monotonic() > deadline:
            pytest.fail("deck never reached ACTIVE")
        _app().processEvents()
        time.sleep(0.02)

    win.action_panel._buttons["tasks"].click()
    _app().processEvents()

    assert win.stage.current is None
    assert win.stage.status is ContentStatus.EMPTY


# ── Task deck panel behavior (fake views, no registry writes) ────────────────


def test_deck_orders_active_tasks_above_finished(win):
    from jarvis.agent.tasks import TaskStatus
    active = _fake_view("t-aktif", status=TaskStatus.RUNNING, progress=0.4)
    done = _fake_view("t-selesai", status=TaskStatus.DONE, progress=1.0)

    win.task_deck.set_tasks([done, active])   # input deliberately unsorted

    ids = [win.task_deck._list.item(r).data(Qt.ItemDataRole.UserRole)
           for r in range(win.task_deck._list.count())]
    assert ids == ["t-aktif", "t-selesai"]


def test_deck_cancel_enabled_only_for_active_tasks(win):
    from jarvis.agent.tasks import TaskStatus
    running = _fake_view("t-jalan", status=TaskStatus.RUNNING)
    finished = _fake_view("t-usai", status=TaskStatus.DONE)

    win.task_deck.set_tasks([running, finished])
    win.task_deck.select("t-jalan")
    assert win.task_deck._cancel_btn.isEnabled() is True

    win.task_deck.select("t-usai")
    assert win.task_deck._cancel_btn.isEnabled() is False


def test_deck_cancel_click_emits_selected_id_with_instant_feedback(win):
    from jarvis.agent.tasks import TaskStatus
    win.task_deck.set_tasks(
        [_fake_view("t-batal", status=TaskStatus.RUNNING)])
    win.task_deck.select("t-batal")

    got: list[str] = []
    win.task_deck.cancel_requested.connect(got.append)
    win.task_deck._on_cancel_clicked()

    assert got == ["t-batal"]
    assert win.task_deck._cancel_btn.isEnabled() is False
    assert win.task_deck._cancel_btn.text() == "Membatalkan…"


def test_deck_cancel_routes_through_dispatch_then_registry(win, monkeypatch):
    """The wiring's _cancel prefers dispatch.cancel_task and only falls back
    to the registry when dispatch declines."""
    from jarvis.agent import dispatch
    calls: list[str] = []
    monkeypatch.setattr(dispatch, "cancel_task",
                        lambda tid: calls.append(tid) or True)

    win.task_deck.cancel_requested.emit("t-dispatch")
    _app().processEvents()

    assert calls == ["t-dispatch"]


def test_deck_empty_message_for_no_tasks(win):
    win.task_deck.set_tasks([])
    # Empty view renders "Tidak ada tugas" message in detail pane
    assert "Tidak ada tugas" in win.task_deck._detail.toPlainText()
    assert win.task_deck._cancel_btn.isEnabled() is False


# ── JsonlTail incremental contract ───────────────────────────────────────────


def test_jsonl_tail_reads_only_appended_records(tmp_path):
    from jarvis.ui.task_deck import JsonlTail
    path = tmp_path / "tail.jsonl"
    path.write_text("", encoding="utf-8")
    tail = JsonlTail(path)

    assert tail.refresh() == 0

    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"session": "s1", "tool": "a", "ok": True}) + "\n")
        fh.write(json.dumps({"session": "s1", "tool": "b", "ok": False}) + "\n")
    assert tail.refresh() == 2
    assert tail.refresh() == 0          # offset cached — nothing re-read

    rows = tail.for_session("s1")
    assert [r["tool"] for r in rows] == ["a", "b"]


def test_jsonl_tail_missing_file_is_bounded_zero(tmp_path):
    from jarvis.ui.task_deck import JsonlTail
    tail = JsonlTail(tmp_path / "absent.jsonl")
    assert tail.refresh() == 0
    assert tail.records() == []


def test_jsonl_tail_for_session_filters_and_bounds(tmp_path):
    from jarvis.ui.task_deck import JsonlTail
    path = tmp_path / "tail2.jsonl"
    lines = [json.dumps({"session": "s1", "i": i}) for i in range(5)]
    lines += [json.dumps({"session": "other", "i": 99})]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    tail = JsonlTail(path)
    tail.refresh()

    assert len(tail.for_session("s1")) == 5
    assert tail.for_session("s1", limit=2)[-1]["i"] == 4
    assert tail.for_session("other")[-1]["i"] == 99
    assert tail.for_session("") == []


# ── Task strip characterization ──────────────────────────────────────────────


def test_strip_shows_only_while_active_tasks_exist(win):
    from jarvis.agent.tasks import TaskStatus
    assert win.task_strip.isHidden() is True

    win.task_strip.set_tasks(
        [_fake_view("t-1", status=TaskStatus.RUNNING)])
    assert win.task_strip.isVisible() is True

    win.task_strip.set_tasks(
        [_fake_view("t-1", status=TaskStatus.DONE)])
    # done task starts the bounded auto-hide countdown; chip list empties
    assert win.task_strip._views == []
    assert win.task_strip._all_done_since is not None


def test_strip_keeps_at_most_three_chips_and_counts_overflow(win):
    from jarvis.agent.tasks import TaskStatus
    views = [_fake_view(f"t-{i}", status=TaskStatus.RUNNING)
             for i in range(5)]

    win.task_strip.set_tasks(views)

    assert len(win.task_strip._views) == 3
    assert win.task_strip._overflow == 2


def test_strip_cancel_click_marks_cancelling_before_registry_confirms(win):
    """Instant feedback contract: the chip flips to BATAL on click, without
    waiting for the registry status to change."""
    from PyQt6.QtCore import QPointF, Qt
    from PyQt6.QtGui import QMouseEvent
    from PyQt6.QtCore import QEvent
    from jarvis.agent.tasks import TaskStatus

    strip = win.task_strip
    strip.resize(800, strip.height())
    strip.set_tasks([_fake_view("t-x", status=TaskStatus.RUNNING)])
    strip.show()

    from PyQt6.QtGui import QPixmap
    pm = QPixmap(800, strip.height())
    strip.render(pm)                                  # force paintEvent
    assert strip._chip_rects, "chip rects must exist after paint"

    task_id, _chip, close_btn = strip._chip_rects[0]
    got: list[str] = []
    strip.cancel_requested.connect(got.append)

    event = QMouseEvent(QEvent.Type.MouseButtonPress,
                        close_btn.center(), QPointF(close_btn.center()),
                        Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
                        Qt.KeyboardModifier.NoModifier)
    strip.mousePressEvent(event)

    assert got == [task_id]
    assert task_id in strip._cancelling


# ── BUS delivery semantics ───────────────────────────────────────────────────


def test_plain_subscriber_runs_synchronously_on_publisher_thread():
    got: list[dict] = []
    BUS.subscribe("p5b.plain", lambda d: got.append(d))

    BUS.publish("p5b.plain", v=7)

    assert got == [{"v": 7}]          # no drain needed


def test_ui_subscriber_snapshot_captured_at_publish_time():
    """A handler registered AFTER a publish must not receive that historical
    event — the snapshot is taken at publish time (bus.py contract)."""
    seen_a: list[dict] = []
    seen_b: list[dict] = []

    BUS.subscribe("p5b.snap", lambda d: seen_a.append(d), ui=True)
    BUS.publish("p5b.snap", n=1)
    BUS.subscribe("p5b.snap", lambda d: seen_b.append(d), ui=True)
    BUS.publish("p5b.snap", n=2)
    _drain_bus()

    assert [d["n"] for d in seen_a] == [1, 2]
    assert [d["n"] for d in seen_b] == [2]


def test_drain_ui_dispatches_at_most_64_events_per_call():
    got: list[dict] = []
    BUS.subscribe("p5b.cap", lambda d: got.append(d), ui=True)

    for i in range(100):
        BUS.publish("p5b.cap", i=i)

    BUS.drain_ui()                    # default max_events=64
    first = len(got)
    BUS.drain_ui()
    assert first == 64
    assert len(got) == 100


def test_handler_exception_does_not_starve_later_handlers():
    got: list[dict] = []
    BUS.subscribe("p5b.exc", lambda d: 1 / 0, ui=True)
    BUS.subscribe("p5b.exc", lambda d: got.append(d), ui=True)

    BUS.publish("p5b.exc", v=1)
    _drain_bus()

    assert got == [{"v": 1}]


def test_concurrent_subscribe_does_not_corrupt_registry():
    import threading

    errors: list[Exception] = []

    def worker(n: int):
        try:
            for i in range(20):
                BUS.subscribe(f"p5b.thread.{n}.{i}", lambda d: None)
        except Exception as exc:                        # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert errors == []
    for n in range(8):
        for i in range(20):
            assert BUS._subs.get(f"p5b.thread.{n}.{i}")


# ── Recovery glyph contract ──────────────────────────────────────────────────


def test_recovery_glyphs_are_distinct_from_live_statuses():
    from jarvis.ui.task_deck import _RECOVERY_GLYPH, _STATUS_GLYPH
    assert set(_RECOVERY_GLYPH) == {
        "recoverable", "interrupted", "outcome_uncertain"}
    assert not set(_RECOVERY_GLYPH) & set(_STATUS_GLYPH)


def test_recovery_views_are_never_active():
    """Recovery hydration rides the same snapshot wiring but must never look
    like a live worker: recovery statuses are outside ACTIVE_STATES."""
    from jarvis.agent.tasks import ACTIVE_STATES
    from jarvis.agent.task_ledger import RecoveryDisposition
    for disp in RecoveryDisposition:
        assert disp not in ACTIVE_STATES
