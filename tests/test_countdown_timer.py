"""Phase WA1 RED — native countdown timer core + orb driver.

Durasi terbatas (bounded int), cancel, selesai tepat waktu (deadline
monotonic — anti-drift), sinyal ringan ke bus, transisi status jelas
(running → done/cancelled). Tanpa remote/network/write.
"""
from __future__ import annotations

import time

from jarvis.core.bus import BUS


def _fresh_timer(monkeypatch, *, now=1000.0):
    """Timer dengan clock injectable deterministik."""
    from jarvis.core import countdown_timer as module
    import jarvis.core.countdown_timer as ct

    state = {"now": now}
    monkeypatch.setattr(ct, "_now", lambda: state["now"])
    timer = ct.CountdownTimer()
    return timer, state


def test_admit_duration_is_bounded_finite_int():
    from jarvis.core.countdown_timer import admit_duration

    assert admit_duration(1)["ok"] is True
    assert admit_duration(60)["ok"] is True
    assert admit_duration(3600)["ok"] is True
    assert admit_duration(True)["ok"] is False
    assert admit_duration(5.0)["ok"] is False
    assert admit_duration(0)["ok"] is False
    assert admit_duration(-3)["ok"] is False
    assert admit_duration(3601)["ok"] is False
    assert admit_duration("30")["ok"] is False
    assert admit_duration(float("nan"))["ok"] is False


def test_start_rejects_invalid_and_stays_idle(monkeypatch):
    timer, _state = _fresh_timer(monkeypatch)
    assert timer.start(-5) is False
    assert timer.start(0) is False
    assert timer.start(99999) is False
    assert timer.status() == "idle"
    assert timer.remaining_s() == 0


def test_start_runs_and_remaining_decreases_with_clock(monkeypatch):
    timer, state = _fresh_timer(monkeypatch, now=1000.0)
    assert timer.start(30) is True
    assert timer.status() == "running"
    assert timer.remaining_s() == 30

    state["now"] = 1003.4
    assert 26 <= timer.remaining_s() <= 27
    assert 0.0 < timer.progress() < 1.0


def test_finish_is_deadline_based_not_tick_based(monkeypatch):
    # Anti-drift: selesai tepat waktu walau tidak ada tick tepat di batas.
    timer, state = _fresh_timer(monkeypatch, now=1000.0)
    timer.start(10)
    state["now"] = 1009.9
    assert timer.status() == "running"          # belum lewat deadline
    state["now"] = 1010.1
    assert timer.status() == "done"             # lewat deadline → done
    assert timer.remaining_s() == 0
    assert timer.progress() == 1.0


def test_finish_publishes_light_bus_signal_once(monkeypatch):
    timer, state = _fresh_timer(monkeypatch, now=1000.0)
    events = []
    BUS.subscribe("timer.finished", lambda data: events.append(data))
    timer.start(5)
    state["now"] = 1005.5
    assert timer.status() == "done"
    assert timer.status() == "done"             # lazy check kedua
    assert len(events) == 1                     # publish sekali saja
    assert events[0]["duration_s"] == 5


def test_cancel_transitions_and_publishes_once(monkeypatch):
    timer, state = _fresh_timer(monkeypatch, now=1000.0)
    events = []
    BUS.subscribe("timer.cancelled", lambda data: events.append(data))
    timer.start(60)
    state["now"] = 1010.0
    assert timer.cancel() is True
    assert timer.status() == "cancelled"
    assert timer.cancel() is False              # idempotent
    assert len(events) == 1
    assert events[0]["duration_s"] == 60


def test_cancel_after_done_keeps_done(monkeypatch):
    timer, state = _fresh_timer(monkeypatch, now=1000.0)
    timer.start(3)
    state["now"] = 1004.0
    assert timer.status() == "done"
    assert timer.cancel() is False
    assert timer.status() == "done"


def test_cancel_idle_is_noop():
    from jarvis.core.countdown_timer import CountdownTimer

    timer = CountdownTimer()
    assert timer.cancel() is False
    assert timer.status() == "idle"


def test_driver_ticks_orb_progress_and_stops_on_done(monkeypatch):
    from jarvis.ui.countdown_driver import CountdownDriver

    timer, state = _fresh_timer(monkeypatch, now=1000.0)
    orb = {"progress": None, "shown": 0}
    ticker = {"active": True, "started": 0, "stopped": 0}

    def fake_set_progress(fraction):
        orb["progress"] = fraction
        orb["shown"] += 1

    def fake_start():
        ticker["started"] += 1
        ticker["active"] = True

    def fake_stop():
        ticker["stopped"] += 1
        ticker["active"] = False

    driver = CountdownDriver(timer=timer, orb=orb, set_progress=fake_set_progress,
                             ticker_start=fake_start, ticker_stop=fake_stop)
    timer.start(10)
    driver.attach()
    assert ticker["started"] == 1

    state["now"] = 1005.0
    driver.tick()
    assert orb["progress"] == 0.5
    assert ticker["active"] is True

    state["now"] = 1010.0
    driver.tick()
    assert orb["progress"] == 1.0
    assert ticker["stopped"] == 1              # ticker berhenti saat done
    assert ticker["active"] is False


def test_driver_attach_is_safe_and_detach_stops(monkeypatch):
    from jarvis.ui.countdown_driver import CountdownDriver

    timer, _state = _fresh_timer(monkeypatch, now=1000.0)
    ticker = {"active": True, "stopped": 0}

    def fake_stop():
        ticker["stopped"] += 1
        ticker["active"] = False

    driver = CountdownDriver(timer=timer, orb={}, set_progress=lambda f: None,
                             ticker_start=lambda: None, ticker_stop=fake_stop)
    driver.attach()
    driver.attach()                            # idempotent
    driver.detach()
    assert ticker["stopped"] == 1
    assert ticker["active"] is False


def test_window_start_countdown_validates_and_runs(monkeypatch):
    import os

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

    from PyQt6.QtWidgets import QApplication, QWidget
    from PyQt6.QtCore import pyqtSignal

    _app_ref = QApplication.instance() or QApplication([])
    import jarvis.browser.embed as embed_mod
    from jarvis.ui.window import MainWindow

    class _StubBrowser(QWidget):
        content_ready = pyqtSignal(str, str)
        display_ready = pyqtSignal(bool)
        NO_FX = True

        def __init__(self, *a, **k):
            super().__init__(*a, **k)

    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)

    win = MainWindow(services={})
    # RED: start_countdown belum ada di window
    assert win.start_countdown(0) is False
    assert win.start_countdown(-5) is False
    assert win.start_countdown(99999) is False
    assert win.start_countdown(10) is True
    assert win.cancel_countdown() is True
