"""RED-first contracts for task-scoped speech metadata and progress."""
from __future__ import annotations

import asyncio
import threading

from jarvis.agent import dispatch
from jarvis.agent.adapters import ui as ui_adapter
from jarvis.agent.loop import RunResult
from jarvis.agent.progress_narrator import ProgressNarrator, phrase_for


def _isolate_dispatch(monkeypatch) -> None:
    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(dispatch.BUS, "publish", lambda *_a, **_k: None)
    with dispatch._active_lock:
        dispatch._active.clear()


def test_dispatch_binds_task_metadata_before_ack(monkeypatch):
    _isolate_dispatch(monkeypatch)
    from jarvis.agent import loop as agent_loop

    events: list[tuple[str, str]] = []
    done = threading.Event()

    async def fake_run(_task, **_kwargs):
        return RunResult(ok=True, text="done", session_id="metadata")

    monkeypatch.setattr(agent_loop, "run", fake_run)

    started = dispatch.dispatch_async(
        "research this",
        on_task=lambda metadata: events.append(("task", metadata.id)),
        on_ack=lambda _ack: events.append(("ack", "")),
        on_done=lambda _result: done.set(),
    )

    assert started is True
    assert done.wait(2)
    assert [kind for kind, _value in events[:2]] == ["task", "ack"]
    assert events[0][1].startswith("T-")


def test_dispatch_task_callback_failure_does_not_break_ack(monkeypatch):
    _isolate_dispatch(monkeypatch)
    from jarvis.agent import loop as agent_loop

    acked = threading.Event()
    done = threading.Event()

    async def fake_run(_task, **_kwargs):
        return RunResult(ok=True, text="done", session_id="metadata")

    monkeypatch.setattr(agent_loop, "run", fake_run)

    assert dispatch.dispatch_async(
        "research this",
        on_task=lambda _metadata: (_ for _ in ()).throw(RuntimeError("ui gone")),
        on_ack=lambda _ack: acked.set(),
        on_done=lambda _result: done.set(),
    ) is True
    assert acked.wait(1)
    assert done.wait(2)


class _Window:
    def __init__(self):
        self.logs: list[str] = []
        self.spoken: list[tuple[str, str, str]] = []

    def write_log(self, text):
        self.logs.append(text)

    def _speak_line(self, text, *, kind="info", turn=""):
        self.spoken.append((text, kind, turn))


def test_ui_progress_is_visual_only_for_unknown_tool(monkeypatch):
    window = _Window()
    adapter = ui_adapter.UIAdapter(window, task_id="T-unknown", source="typed")
    monkeypatch.setattr(adapter._narrator, "should_speak", lambda _text: True)

    asyncio.run(adapter.progress("tool_yang_tidak_dikenal"))

    assert window.logs == ["SYS: tool_yang_tidak_dikenal"]
    assert window.spoken == []


def test_ui_progress_is_scoped_to_its_registry_task():
    window = _Window()
    adapter = ui_adapter.UIAdapter(window, task_id="T-42", source="typed")
    adapter._narrator = ProgressNarrator(min_interval_s=0, max_spoken=3)

    asyncio.run(adapter.progress("web_search"))

    assert window.spoken
    assert window.spoken[0][1:] == ("progress", "T-42")


def test_empty_progress_phrase_is_never_spoken():
    narrator = ProgressNarrator(min_interval_s=0, max_spoken=3)

    assert phrase_for("tool_yang_tidak_dikenal") == ""
    assert narrator.should_speak("") is False
