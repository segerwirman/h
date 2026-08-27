"""Checkpoint B — resource-aware WAITING and process-local resume."""
from __future__ import annotations

import threading
import time


class _Bus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    def publish(self, topic: str, **data) -> None:
        self.events.append((topic, data))


class _Ledger:
    def __init__(self) -> None:
        self.records: dict[str, dict] = {}

    def create(self, task_id, *, title, source, conversation, incarnation):
        self.records[task_id] = {
            "title": title,
            "source": source,
            "owner_scope": conversation,
            "state": "queued",
            "step": "",
            "pending_tool": "",
        }

    def mark(self, task_id, *, state, step, incarnation):
        self.records[task_id]["state"] = state
        self.records[task_id]["step"] = step

    def finish(self, task_id, *, ok, result, incarnation):
        self.records[task_id]["state"] = "done" if ok else "failed"

    def mark_pending_tool(self, task_id, *, tool, read_only, incarnation):
        self.records[task_id]["pending_tool"] = tool


def _registry(*, max_concurrent=1, ledger=None):
    from jarvis.agent.tasks import TaskRegistry

    return TaskRegistry(
        bus=_Bus(),
        max_concurrent=max_concurrent,
        queue_max=8,
        poll_s=0.005,
        ledger=ledger,
    )


def _running(registry, prompt="task", resources=()):
    task = registry.submit(prompt, resources=resources)
    assert task is not None
    assert registry.acquire_slot(task) is True
    assert registry.mark_running(task.id) is not None
    return task


def _wait(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return False


def test_waiting_releases_slot_so_next_queued_task_proceeds():
    from jarvis.agent.tasks import TaskStatus

    registry = _registry(max_concurrent=1)
    first = _running(registry, "first", resources={"desktop"})
    token = object()
    assert registry.register_wait_continuation(first.id, token) is True

    second = registry.submit("second", resources={"desktop"})
    acquired = threading.Event()

    def acquire_second():
        if registry.acquire_slot(second):
            registry.mark_running(second.id)
            acquired.set()

    thread = threading.Thread(target=acquire_second, daemon=True)
    thread.start()
    time.sleep(0.03)
    assert acquired.is_set() is False

    assert registry.begin_wait(first.id, "captcha_handoff") is True
    assert acquired.wait(1)
    assert registry.get(first.id).status is TaskStatus.WAITING
    assert registry.get(second.id).status is TaskStatus.RUNNING

    registry.release_slot(second)
    registry.finish(second.id, result="ok")
    registry.cancel(first.id)
    thread.join(timeout=1)


def test_resume_reacquires_normal_slot_and_resources():
    from jarvis.agent.tasks import TaskStatus

    registry = _registry(max_concurrent=1)
    first = _running(registry, "first", resources={"desktop"})
    token = object()
    assert registry.register_wait_continuation(first.id, token)
    assert registry.begin_wait(first.id, "captcha_handoff")

    blocker = _running(registry, "blocker", resources={"desktop"})
    result: list[bool] = []
    resumed = threading.Event()

    def resume_first():
        result.append(registry.resume_wait(first.id, token))
        resumed.set()

    thread = threading.Thread(target=resume_first, daemon=True)
    thread.start()
    time.sleep(0.05)
    assert resumed.is_set() is False
    assert registry.get(first.id).status is TaskStatus.WAITING

    registry.release_slot(blocker)
    registry.finish(blocker.id, result="ok")
    assert resumed.wait(1)
    assert result == [True]
    assert registry.get(first.id).status is TaskStatus.RUNNING
    assert first._slot is True
    assert first._held == ("desktop",)

    registry.release_slot(first)
    registry.finish(first.id, result="ok")
    thread.join(timeout=1)


def test_resume_without_live_continuation_cancels_safely():
    from jarvis.agent.tasks import TaskStatus

    registry = _registry()
    task = _running(registry)
    token = object()
    assert registry.register_wait_continuation(task.id, token)
    assert registry.begin_wait(task.id, "human_input")
    assert registry.clear_wait_continuation(task.id, token)

    assert registry.resume_wait(task.id, token) is False
    view = registry.get(task.id)
    assert view.status is TaskStatus.CANCELLED
    assert view.cancelled is True
    assert task._slot is False
    assert task._held == ()


def test_mismatched_continuation_cancels_instead_of_resuming():
    from jarvis.agent.tasks import TaskStatus

    registry = _registry()
    task = _running(registry)
    assert registry.register_wait_continuation(task.id, object())
    assert registry.begin_wait(task.id, "human_input")

    assert registry.resume_wait(task.id, object()) is False
    assert registry.get(task.id).status is TaskStatus.CANCELLED


def test_begin_wait_requires_running_task_live_token_and_safe_reason():
    registry = _registry()
    queued = registry.submit("queued")
    assert registry.register_wait_continuation(queued.id, object()) is False
    assert registry.begin_wait(queued.id, "human_input") is False

    running = _running(registry, "running")
    assert registry.begin_wait(running.id, "human_input") is False
    assert registry.register_wait_continuation(running.id, object()) is True
    assert registry.begin_wait(running.id, "CAPTCHA selesai") is False
    assert registry.begin_wait(running.id, "captcha_content_123!") is False
    assert registry.begin_wait(running.id, "arbitrary_reason") is False
    assert registry.begin_wait(running.id, "captcha_handoff") is True

    registry.cancel(running.id)
    registry.cancel(queued.id)


def test_cancel_waiting_is_terminal_and_clears_continuation():
    from jarvis.agent.tasks import TaskStatus

    registry = _registry()
    task = _running(registry)
    token = object()
    assert registry.register_wait_continuation(task.id, token)
    assert registry.begin_wait(task.id, "human_input")

    assert registry.cancel(task.id) is True
    assert registry.get(task.id).status is TaskStatus.CANCELLED
    assert registry.clear_wait_continuation(task.id, token) is False


def test_task_ledger_sanitizes_waiting_step_even_if_called_directly(tmp_path):
    from jarvis.agent.task_ledger import TaskLedger

    ledger = TaskLedger(tmp_path / "wait-ledger.sqlite")
    row = ledger.create(
        "T-direct",
        title="safe title",
        incarnation="inc-safe",
    )
    updated = ledger.mark(
        row.task_id,
        state="waiting",
        step="CAPTCHA image with observation_id=obs-secret",
        incarnation=row.incarnation,
    )

    assert updated.step == "waiting"
    assert "obs-secret" not in repr(updated)


def test_waiting_ledger_stores_safe_metadata_only():
    ledger = _Ledger()
    registry = _registry(ledger=ledger)
    task = _running(
        registry,
        "title without sensitive payload",
        resources={"desktop"},
    )
    token = object()
    assert registry.register_wait_continuation(task.id, token)
    assert registry.begin_wait(task.id, "captcha_handoff")

    record = ledger.records[task.id]
    assert record == {
        "title": "title without sensitive payload",
        "source": "agent",
        "owner_scope": "",
        "state": "waiting",
        "step": "captcha_handoff",
        "pending_tool": "",
    }
    serialized = repr(record).casefold()
    for forbidden in (
        "passphrase", "password", "observation_id", "element_id",
        "raw_result", "captcha image", "tool_args",
    ):
        assert forbidden not in serialized

    registry.cancel(task.id)
