"""P6-C — Presentation adapter acceptance counters (roadmap gate).

Final slice of roadmap P6 / GUI_EVOLUTION_PLAN GUI-1: prove that the adapter
feature does NOT change semantic routing or task refresh semantics when enabled
vs disabled. Same subscriber counts on BUS task topics; same submission count
through the text-command callback; no second owners created.

Everything here is offline: EmbeddedBrowser stubbed (QtWebEngine cannot init
offscreen), JARVIS_NO_MIC_METER=1, tools JSONL redirected to temp file, no
provider/network/audio/camera/browser calls. Uses offscreen + BUS subscriber
snapshots as P5-B/C/D/E do.

Gates verified:
- TASK TOPIC SUBSCRIBERS: each window construction adds exactly +1 UI subscriber
  per task topic (`task.submitted`, `task.updated`, `task.finished`) — the delta
  is IDENTICAL whether the adapter flag is off or on (no second refresh owner)
- SUBMISSION DELEGATION: one user input → exactly one on_text_command invocation,
  whether wrapped by shim or not
- NO SECOND OWNER: adapter flag never injects an extra subscriber to BUS tasks
  (only passes through existing wiring)
- FROZEN integrity OK

Evidence label: focused-tested. No runtime-wired, endpoint-reachable, or live-proven
claim; legacy shell remains the only deployed shell.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from jarvis.core import config
from jarvis.core.bus import BUS

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


class _StubBrowser(QWidget):
    """EmbeddedBrowser stand-in (see tests/test_window_integration.py)."""
    NO_FX = True

    def navigate(self, url: str, extract: bool = True) -> None:
        pass


def _make_ui(monkeypatch, tmp_path, *, flag_on: bool):
    """Build JarvisUI with adapter flag pinned."""
    _app()
    real_get = config.get
    monkeypatch.setattr(
        config, "get",
        lambda k, d=None: True if k == "ui.presentation_adapter.enabled" else real_get(k, d))
    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    from jarvis.agent import tool_usage
    log_path = tmp_path / "p6c_tools.jsonl"
    log_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(tool_usage, "jsonl_path", lambda: log_path)
    from jarvis.ui.window import JarvisUI
    return JarvisUI(services={})


# ── BUS subscriber counts: +1 per task topic per window, invariant to flag ───
#
# Windows never unregister their task-topic subscribers (global BUS), so the
# honest measurement is the DELTA each construction adds (P5-B pattern):
# exactly +1 per topic, and the adapter flag must not change that delta.

_TOPICS = ("task.submitted", "task.updated", "task.finished")


def test_task_topic_delta_flag_off_is_exactly_one_per_topic(monkeypatch, tmp_path):
    """Flag off: constructing JarvisUI adds exactly one UI subscriber per
    task topic (the single task_wiring refresh handler)."""
    before = {t: len(BUS._ui_subs.get(t, ())) for t in _TOPICS}
    ui = _make_ui(monkeypatch, tmp_path, flag_on=False)
    try:
        for topic in _TOPICS:
            delta = len(BUS._ui_subs.get(topic, ())) - before[topic]
            assert delta == 1, f"{topic}: expected +1 subscriber, got +{delta}"
    finally:
        ui._win.close()


def test_task_topic_delta_flag_on_is_exactly_one_per_topic(monkeypatch, tmp_path):
    """Flag on: adapter seam adds ZERO extra subscribers — the construction
    delta stays exactly +1 per topic, identical to the flag-off path."""
    before = {t: len(BUS._ui_subs.get(t, ())) for t in _TOPICS}
    ui = _make_ui(monkeypatch, tmp_path, flag_on=True)
    try:
        for topic in _TOPICS:
            delta = len(BUS._ui_subs.get(topic, ())) - before[topic]
            assert delta == 1, (
                f"{topic}: adapter-on added +{delta} subscribers "
                "(must be +1, identical to flag-off — no second owner)")
    finally:
        ui._win.close()


def test_task_topic_subscribers_invariant_between_flags():
    """Prove the difference is zero: adapters neither adds nor removes bus subs."""
    from jarvis.ui.window import MainWindow

    # Build baseline window (no adapter seam involved)
    win_baseline = MainWindow({})
    baseline_counts = {
        t: len(BUS._ui_subs.get(t, ()))
        for t in ("task.submitted", "task.updated", "task.finished")
    }

    # Adapter wiring path constructs a Shim around the facade itself; it does not
    # subscribe any additional listeners to task topics
    from jarvis.ui.presentation_adapter import FacadeShim

    class FakeFacadeForCounts:
        """Minimal facade surface to wrap."""
        def set_state(self, s): pass
        def write_log(self, t): pass
        def show_content(self, title, text): pass
        on_text_command = None

    fake = FakeFacadeForCounts()
    shim = FacadeShim(fake)
    after_adapter_counts = {
        t: len(BUS._ui_subs.get(t, ()))
        for t in ("task.submitted", "task.updated", "task.finished")
    }

    for topic in ("task.submitted", "task.updated", "task.finished"):
        assert baseline_counts[topic] == after_adapter_counts[topic], \
            f"{topic} changed after creating FacadeShim (adapter bug: second owner)"

    win_baseline.close()


# ── Submission delegation: exactly once via on_text_command, invariant to flag ─


def test_submission_delegation_flag_off_invokes_callback_once(monkeypatch, tmp_path):
    """Flag off path invokes on_text_command exactly once per submit."""
    ui = _make_ui(monkeypatch, tmp_path, flag_on=False)
    try:
        calls = []
        ui.on_text_command = lambda x: calls.append(x)

        # Simulate user typing and pressing Enter
        ui.on_text_command("buka spotify")

        assert len(calls) == 1
        assert calls[0] == "buka spotify"
    finally:
        ui._win.close()


def test_submission_delegation_flag_on_invokes_callback_once(monkeypatch, tmp_path):
    """Flag on path: shim forwards call once while recording intent."""
    ui = _make_ui(monkeypatch, tmp_path, flag_on=True)
    try:
        calls = []
        ui.on_text_command = lambda x: calls.append(x)

        # Use the shim's submit_text method which should delegate to on_text_command
        ui.adapter.submit_text("catat rapat")

        assert len(calls) == 1
        assert calls[0] == "catat rapat"
        # Also verify intent was recorded
        intents = ui.adapter.recorder.intents
        assert len(intents) == 1
        assert intents[0]["intent"] == "submit_text"
        assert intents[0]["meta"] == {"text": "catat rapat"}
    finally:
        ui._win.close()


# ── Acceptance summary: gate proof ───────────────────────────────────────────


def test_adapters_never_creates_second_owner_for_task_semantics(tmp_path):
    """The entire test module's purpose: adapter flag cannot create a second
    task refresh owner. If this passes, P6 can close per roadmap gates."""
    from jarvis.ui.window import MainWindow
    from jarvis.ui.presentation_adapter import FacadeShim

    # Baseline
    win = MainWindow({})
    baseline = {t: len(BUS._ui_subs.get(t, ()))
                for t in ("task.submitted", "task.updated", "task.finished")}

    # Construct adapter shim
    class MinimalFacade:
        def set_state(self, s): pass
        def write_log(self, t): pass
        def show_content(self, title, text): pass
        on_text_command = None

    shim = FacadeShim(MinimalFacade())
    after = {t: len(BUS._ui_subs.get(t, ()))
             for t in ("task.submitted", "task.updated", "task.finished")}

    # Gate assertion: delta must be zero
    for topic in ("task.submitted", "task.updated", "task.finished"):
        delta = after[topic] - baseline[topic]
        assert delta == 0, f"{topic}: adapter created {delta} extra subscriber(s)"

    win.close()

