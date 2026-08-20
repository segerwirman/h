"""P1-C acceptance contracts for typed native-task lifecycle ownership."""
from __future__ import annotations

import asyncio
import threading
import time
from types import SimpleNamespace

import pytest

from jarvis.agent import dispatch
from jarvis.agent.loop import RunResult
from jarvis.agent.tasks import REGISTRY, TaskStatus


class _Signal:
    def __init__(self) -> None:
        self.values: list[tuple] = []

    def emit(self, *values) -> None:
        self.values.append(values)


class _Orb:
    def __init__(self) -> None:
        self.states: list[object] = []

    def set_state(self, state) -> None:
        self.states.append(state)


class _Store:
    def __init__(self) -> None:
        self.bound: list[tuple[str, str]] = []
        self.successes: list[tuple[str, str]] = []
        self.failures: list[tuple[str, str]] = []

    def last_artifact(self, _conversation_id: str):
        return "", ""

    def resolve(self, _conversation_id: str, _task: str):
        return SimpleNamespace(kind="none", candidates=[])

    def augment(self, _conversation_id: str, task: str) -> str:
        return task

    def begin_task(self, conversation_id: str, *, task_id: str,
                   task: str, source: str) -> None:
        self.bound.append((conversation_id, task_id))

    def remember_success(self, conversation_id: str, *, task_id: str,
                         task: str, delivery) -> None:
        self.successes.append((conversation_id, task_id))

    def fail_task(self, conversation_id: str, task_id: str) -> None:
        self.failures.append((conversation_id, task_id))


class _TypedHarness:
    def __init__(self, order: list[str] | None = None) -> None:
        self.orb = _Orb()
        self._content_sig = _Signal()
        self.logs: list[str] = []
        self.spoken: list[tuple[str, str, str]] = []
        self.task_results: list[tuple[str, str]] = []
        self.order = order if order is not None else []



    def write_log(self, text: str) -> None:
        self.logs.append(text)

    def _speak_line(self, text: str, *, kind: str = "info",
                    turn: str = "") -> None:
        self.order.append(kind)
        self.spoken.append((text, kind, turn))

    def _restore_orb(self) -> None:
        return None

    def _record_task_result(self, kind: str, text: str) -> None:
        self.task_results.append((kind, text))


def _isolate(monkeypatch):
    from jarvis.agent import conversation_context, response_composer

    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(
        response_composer, "compose", lambda delivery, _task, **_: delivery
    )
    monkeypatch.setattr(conversation_context, "STORE", _Store())
    monkeypatch.setattr(
        conversation_context, "is_artifact_reference", lambda _task: False
    )
    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()
    return conversation_context.STORE


def _capture_bus(monkeypatch, order: list[str] | None = None):
    events: list[tuple[str, dict]] = []

    def publish(topic: str, **data) -> None:
        events.append((topic, data))
        if order is not None and topic == "task.finished":
            order.append("finished")

    monkeypatch.setattr(REGISTRY._bus, "publish", publish)
    return events


def _wait_for(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.005)
    pytest.fail("timed out waiting for native task lifecycle")


def test_typed_native_lifecycle_has_one_task_ack_terminal_and_owner(
        monkeypatch):
    """Typed heavy input owns one registry lifecycle from ACK to terminal."""
    store = _isolate(monkeypatch)
    order: list[str] = []
    events = _capture_bus(monkeypatch, order)
    from jarvis.agent import loop as agent_loop
    from jarvis.ui.window import MainWindow

    async def fake_run(_task, **_kwargs):
        order.append("worker")
        return RunResult(ok=True, text="hasil P1-C", session_id="p1c")

    monkeypatch.setattr(agent_loop, "run", fake_run)
    harness = _TypedHarness(order)

    MainWindow._run_agent_native(harness, "cek lifecycle P1-C")

    _wait_for(lambda: any(topic == "task.finished" for topic, _ in events))
    # The worker's finally block (slot release, compatibility finish, active
    # handle removal) runs after ``task.finished``; drain it before asserting.
    _wait_for(lambda: dispatch.active_count() == 0)
    submitted = [data["task"] for topic, data in events
                 if topic == "task.submitted"]
    finished = [data["task"] for topic, data in events
                if topic == "task.finished"]

    assert len(submitted) == 1
    assert len(finished) == 1
    assert finished[0]["id"] == submitted[0]["id"]
    assert finished[0]["status"] == TaskStatus.DONE.value
    assert finished[0]["result"] == "hasil P1-C"
    assert finished[0]["completion_owner"] == "caller"
    assert [kind for _text, kind, _turn in harness.spoken] == [
        "ack", "final"
    ]
    assert harness.spoken[0][2] == harness.spoken[1][2]
    assert store.bound == [("typed-desktop", submitted[0]["id"])]
    assert order.index("ack") < order.index("worker")
    assert order.index("worker") < order.index("final")
    assert order.index("final") < order.index("finished")
    assert len([item for item in events if item[0] == "task.finished"]) == 1
    task_topics = [topic for topic, _ in events
                   if topic.startswith("task.")]
    assert task_topics[-1] == "task.finished"

    cleanup = REGISTRY.finish(
        submitted[0]["id"], result="cleanup overwrite", error="cleanup"
    )
    assert cleanup is not None
    assert cleanup.result == "hasil P1-C"
    assert cleanup.error == ""
    assert cleanup.completion_owner == "caller"
    assert len([item for item in events if item[0] == "task.finished"]) == 1

    assert REGISTRY.get(submitted[0]["id"]).result == "hasil P1-C"
    assert REGISTRY.get(submitted[0]["id"]).completion_owner == "caller"
    assert dispatch.active_count() == 0


def test_typed_duplicate_active_task_creates_no_second_worker_or_registry_task(
        monkeypatch):
    """A duplicate typed task is rejected while the first task remains active."""
    _isolate(monkeypatch)
    events = _capture_bus(monkeypatch)
    from jarvis.agent import loop as agent_loop
    from jarvis.ui.window import MainWindow

    release = threading.Event()
    workers: list[str] = []

    async def fake_run(task, **_kwargs):
        workers.append(task)
        await asyncio.to_thread(release.wait)
        return RunResult(ok=True, text="hasil duplicate test", session_id="p1c")

    monkeypatch.setattr(agent_loop, "run", fake_run)
    first = _TypedHarness()
    second = _TypedHarness()
    task = "jalankan lifecycle duplicate P1-C"

    MainWindow._run_agent_native(first, task)
    _wait_for(lambda: len(workers) == 1)
    MainWindow._run_agent_native(second, task)

    time.sleep(0.05)
    assert workers == [task]
    submitted = [data["task"] for topic, data in events
                 if topic == "task.submitted"]
    assert len(submitted) == 1
    assert not any(topic == "task.finished" for topic, _ in events)

    release.set()
    _wait_for(lambda: sum(topic == "task.finished" for topic, _ in events)
              == 1)
    _wait_for(lambda: dispatch.active_count() == 0)
    assert len([data for topic, data in events if topic == "task.finished"]) == 1
