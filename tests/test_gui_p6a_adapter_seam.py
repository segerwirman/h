"""P6-A — Presentation adapter seam characterization (RED-first).

First slice of P6 (GUI_EVOLUTION_PLAN GUI-1 / roadmap P6): the smallest
presentation boundary between the semantic owners and the shell. This phase
introduces NO source behavior change: the adapter is a pure-Python, Qt-free
pass-through recorder around the legacy facade. The legacy shell remains the
only deployed shell and looks unchanged.

Everything here is offline: fake facade, no Qt widgets, no provider/network/
audio/camera/browser calls.

Contracts under test:
- PresentationAdapter module imports without PyQt (pure Python)
- SemanticViewPort applies state/content/log with the SAME bounds the legacy
  facade already applies (title[:64], text[:6000])
- FacadeShim delegates each call to the wrapped facade EXACTLY once and
  mirrors the semantic value into the viewport (no duplicate owner)
- IntentRecorder records one intent per delegated user action and clears
- Adapter never mutates facade arguments before delegation

Evidence label: focused-tested. No runtime-wired, endpoint-reachable, or
live-proven claim; the legacy shell remains the only deployed shell.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")


class _FakeFacade:
    """Stand-in for JarvisUI recording every delegated call."""

    def __init__(self):
        self.calls: list[tuple[str, tuple]] = []

    def set_state(self, state: str):
        self.calls.append(("set_state", (state,)))

    def write_log(self, text: str):
        self.calls.append(("write_log", (text,)))

    def show_content(self, title: str, text: str):
        self.calls.append(("show_content", (title, text)))


# ── Purity contract — the adapter must not import Qt ─────────────────────────


def test_presentation_adapter_is_pure_python_without_qt():
    """The adapter layer may not depend on PyQt: it is the seam both legacy
    and future modern shells consume, so it stays headless-importable."""
    import ast
    import pathlib

    import jarvis.ui.presentation_adapter as mod

    src = pathlib.Path(mod.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(a.name.split(".")[0] for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert "PyQt6" not in imported
    assert "PyQt5" not in imported
    assert "PySide6" not in imported


# ── SemanticViewPort — bounded semantic model ────────────────────────────────


def test_viewport_applies_state_content_and_log_with_facade_bounds():
    """Viewport mirrors the facade's own bounds: title[:64], text[:6000]."""
    from jarvis.ui.presentation_adapter import SemanticViewPort

    vp = SemanticViewPort()
    vp.apply_state("LISTENING")
    assert vp.state == "LISTENING"

    vp.apply_content("J" * 200, "X" * 9000)
    assert vp.title == "J" * 64            # same bound as facade emit
    assert vp.text == "X" * 6000

    vp.append_log("baris-1")
    vp.append_log("baris-2")
    assert tuple(vp.log) == ("baris-1", "baris-2")


def test_viewport_log_is_bounded_and_order_preserving():
    """Log buffer never grows unbounded; oldest entries drop first."""
    from jarvis.ui.presentation_adapter import SemanticViewPort

    vp = SemanticViewPort(max_log=4)
    for i in range(10):
        vp.append_log(f"e{i}")

    log = tuple(vp.log)
    assert len(log) == 4
    assert log == ("e6", "e7", "e8", "e9")


# ── FacadeShim — one delegation per call, no second owner ────────────────────


def test_shim_delegates_each_call_exactly_once_and_mirrors_semantics():
    """set_state/write_log/show_content reach the wrapped facade exactly once
    with UNMUTATED arguments, while the viewport gets the bounded copy."""
    from jarvis.ui.presentation_adapter import FacadeShim, SemanticViewPort

    facade = _FakeFacade()
    vp = SemanticViewPort()
    shim = FacadeShim(facade, viewport=vp)

    shim.set_state("THINKING")
    shim.write_log("siap")
    shim.show_content("T" * 100, "B" * 7000)

    assert facade.calls == [
        ("set_state", ("THINKING",)),
        ("write_log", ("siap",)),
        ("show_content", ("T" * 100, "B" * 7000)),   # unmuted passthrough
    ]
    assert vp.state == "THINKING"
    assert vp.title == "T" * 64
    assert vp.text == "B" * 6000
    assert tuple(vp.log) == ("siap",)


def test_shim_never_calls_facade_more_than_once_per_call():
    """No duplicate delegation: one shim call == exactly one facade call."""
    from jarvis.ui.presentation_adapter import FacadeShim

    facade = _FakeFacade()
    shim = FacadeShim(facade)

    for _ in range(3):
        shim.show_content("judul", "isi")

    assert len(facade.calls) == 3
    assert all(name == "show_content" for name, _ in facade.calls)


# ── IntentRecorder — one intent per user action ──────────────────────────────


def test_intent_recorder_records_one_entry_per_action_and_clears():
    """Recorder captures intent name + meta once per call; clear() empties it
    without touching the facade (recorder is read-side only)."""
    from jarvis.ui.presentation_adapter import IntentRecorder

    rec = IntentRecorder()
    rec.record("submit_text", text="buka spotify")
    rec.record("interrupt")

    intents = rec.intents
    assert len(intents) == 2
    assert intents[0]["intent"] == "submit_text"
    assert intents[0]["meta"] == {"text": "buka spotify"}
    assert intents[1]["intent"] == "interrupt"

    rec.clear()
    assert rec.intents == ()


def test_shim_submit_text_records_intent_and_delegates_once():
    """A user submission through the shim records exactly one intent and
    forwards the text to the facade's text-command callback exactly once."""
    from jarvis.ui.presentation_adapter import FacadeShim

    got: list[str] = []
    facade = _FakeFacade()
    facade.on_text_command = got.append      # legacy callback seam
    shim = FacadeShim(facade)

    shim.submit_text("putar musik")

    assert got == ["putar musik"]
    assert len(shim.recorder.intents) == 1
    assert shim.recorder.intents[0]["intent"] == "submit_text"
    assert shim.recorder.intents[0]["meta"] == {"text": "putar musik"}
