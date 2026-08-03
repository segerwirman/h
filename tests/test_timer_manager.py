"""WA1-lanjutan RED — timer manager (multi-timer, pause/resume).

Multi-timer bersamaan (bounded count, label unik), pause/resume dengan
deadline digeser (anti-drift), status list, due list untuk announcement
opsional, rentang 1 detik–7 hari. Murni lokal; tanpa provider/network.
"""
from __future__ import annotations

MAX_DURATION_S = 7 * 86400          # 7 hari
MAX_TIMERS = 8


def _manager(monkeypatch, *, now=1_000.0):
    import jarvis.core.timer_manager as tm

    state = {"now": now}
    monkeypatch.setattr(tm, "_now", lambda: state["now"])
    return tm, state


def test_add_timer_valid_and_bounded(monkeypatch):
    tm, state = _manager(monkeypatch)
    mgr = tm.TimerManager()
    assert mgr.add("kopi", 300) is True
    assert mgr.status_list()[0]["status"] == "running"
    assert mgr.status_list()[0]["remaining_s"] == 300
    # Rentang 1s – 7 hari
    assert mgr.add("seminggu", MAX_DURATION_S) is True
    assert mgr.add("nol", 0) is False
    assert mgr.add("negatif", -5) is False
    assert mgr.add("terlalu", MAX_DURATION_S + 1) is False


def test_duplicate_label_and_limit(monkeypatch):
    tm, _state = _manager(monkeypatch)
    mgr = tm.TimerManager()
    assert mgr.add("kopi", 60) is True
    assert mgr.add("kopi", 120) is False          # duplicate label
    for i in range(MAX_TIMERS):
        mgr.add(f"t{i}", 60)
    assert mgr.add("penuh", 60) is False          # limit tercapai


def test_pause_freezes_remaining_and_resume_shifts_deadline(monkeypatch):
    tm, state = _manager(monkeypatch)
    mgr = tm.TimerManager()
    mgr.add("kopi", 300)
    state["now"] += 100                            # 200s tersisa
    assert mgr.pause("kopi") is True
    assert mgr.status_list()[0]["status"] == "paused"
    assert mgr.status_list()[0]["remaining_s"] == 200
    state["now"] += 500                            # waktu berlalu saat pause
    assert mgr.status_list()[0]["remaining_s"] == 200   # dibekukan
    assert mgr.resume("kopi") is True
    assert mgr.status_list()[0]["status"] == "running"
    assert mgr.status_list()[0]["remaining_s"] == 200   # deadline digeser
    state["now"] += 200
    assert mgr.status_list()[0]["remaining_s"] == 0
    assert mgr.status_list()[0]["status"] == "done"


def test_done_is_lazy_and_due_list_reports_finished(monkeypatch):
    tm, state = _manager(monkeypatch)
    mgr = tm.TimerManager()
    mgr.add("telur", 10)
    mgr.add("roti", 60)
    state["now"] += 11
    assert mgr.due() == ["telur"]
    assert mgr.status_list()[0]["status"] == "done"
    assert mgr.status_list()[1]["status"] == "running"


def test_remove_timer(monkeypatch):
    tm, _state = _manager(monkeypatch)
    mgr = tm.TimerManager()
    mgr.add("kopi", 60)
    assert mgr.remove("kopi") is True
    assert mgr.remove("kopi") is False
    assert mgr.status_list() == []


def test_status_list_is_metadata_only(monkeypatch):
    tm, _state = _manager(monkeypatch)
    mgr = tm.TimerManager()
    mgr.add("kopi", 60)
    text = str(mgr.status_list())
    assert "kopi" in text
    for forbidden in ("password", "token=", "path", "payload"):
        assert forbidden not in text, forbidden


def test_announce_callback_is_optional_and_not_auto_invoked(monkeypatch):
    tm, state = _manager(monkeypatch)
    calls = []
    mgr = tm.TimerManager(announce=calls.append)
    mgr.add("kopi", 10)
    state["now"] += 11
    mgr.due()                                      # panggil manual
    assert calls == ["kopi"]


def test_no_live_authority_via_static_contract(monkeypatch):
    from pathlib import Path

    source = Path("jarvis/core/timer_manager.py").read_text(encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes"):
        assert forbidden not in source, forbidden
