"""Offline tests for bounded background social-comment runtime ownership."""
from __future__ import annotations

import threading

from jarvis.integrations.comments.base import (
    CommentEvent,
    CommentManager,
    PlatformAdapter,
    PlatformCapabilities,
    ReplyResult,
    RetryPolicy,
)
from jarvis.integrations.comments.runtime import CommentRuntime


class _Adapter(PlatformAdapter):
    name = "fake"

    def __init__(self, results: list[ReplyResult] | None = None) -> None:
        self.results = list(results or [ReplyResult(True, "sent")])
        self.poll_calls = 0
        self.send_threads: list[int] = []

    def capabilities(self) -> PlatformCapabilities:
        return PlatformCapabilities(True, True, False, "offline fake")

    def poll_comments(self) -> list[CommentEvent]:
        self.poll_calls += 1
        return []

    def send_reply(self, comment: CommentEvent, text: str) -> ReplyResult:
        self.send_threads.append(threading.get_ident())
        if self.results:
            return self.results.pop(0)
        return ReplyResult(False, "empty fake results")


class _OneCycleSleeper:
    def __init__(self) -> None:
        self.runtime: CommentRuntime | None = None
        self.delays: list[float] = []

    def __call__(self, delay: float) -> None:
        self.delays.append(delay)
        assert self.runtime is not None
        self.runtime.stop()


def _comment() -> CommentEvent:
    return CommentEvent("fake", "c-1", "u-1", "Offline", "halo", 1.0)


def test_retry_policy_waits_real_injected_delays_off_main_thread():
    adapter = _Adapter(
        [
            ReplyResult(False, "first"),
            ReplyResult(False, "second"),
            ReplyResult(True, "sent"),
        ]
    )
    delays: list[float] = []
    manager = CommentManager(
        [adapter],
        sleeper=delays.append,
        retry_policy=RetryPolicy(3, 1.0, 10.0),
    )
    main_thread = threading.get_ident()
    box: dict[str, ReplyResult] = {}

    worker = threading.Thread(
        target=lambda: box.setdefault(
            "result",
            manager.reply(_comment(), "Halo!", confirmed=True),
        )
    )
    worker.start()
    worker.join(timeout=1.0)

    assert worker.is_alive() is False
    assert box["result"].ok is True
    assert delays == [1.0, 2.0]
    assert all(thread_id != main_thread for thread_id in adapter.send_threads)


def test_runtime_thread_is_daemon_bounded_idempotent_and_stops_cleanly():
    adapter = _Adapter()
    manager = CommentManager([adapter])
    sleeper = _OneCycleSleeper()
    runtime = CommentRuntime(
        manager,
        poll_interval_s=0.01,
        sleeper=sleeper,
    )
    sleeper.runtime = runtime

    first = runtime.start()
    second = runtime.start()
    assert first is True
    assert second is False
    assert runtime.daemon is True

    assert runtime.join(timeout=1.0) is True
    assert runtime.running is False
    assert adapter.poll_calls == 1
    assert sleeper.delays == [0.01]
    assert runtime.start() is False, "runtime owner tidak boleh restart setelah terminal"


def test_runtime_drains_accepted_events_through_injected_handler():
    comment = _comment()

    class _PollingManager:
        def __init__(self) -> None:
            self.calls = 0

        def poll_once(self):
            self.calls += 1
            return [comment]

    manager = _PollingManager()
    handled: list[CommentEvent] = []
    sleeper = _OneCycleSleeper()
    runtime = CommentRuntime(
        manager,
        poll_interval_s=0.01,
        sleeper=sleeper,
        handler=handled.append,
    )
    sleeper.runtime = runtime

    assert runtime.start() is True
    assert runtime.join(timeout=1.0) is True
    assert manager.calls == 1
    assert handled == [comment]


def test_runtime_handler_failure_is_bounded_and_does_not_kill_cycle():
    comments = [_comment(), _comment()]

    class _PollingManager:
        def poll_once(self):
            return comments

    handled: list[str] = []

    def handler(comment):
        handled.append(comment.comment_id)
        if len(handled) == 1:
            raise RuntimeError("offline handler failure")

    sleeper = _OneCycleSleeper()
    runtime = CommentRuntime(
        _PollingManager(),
        poll_interval_s=0.01,
        sleeper=sleeper,
        handler=handler,
    )
    sleeper.runtime = runtime

    assert runtime.start() is True
    assert runtime.join(timeout=1.0) is True
    assert handled == ["c-1", "c-1"]


def test_runtime_refuses_invalid_interval_and_stops_before_polling():
    adapter = _Adapter()
    manager = CommentManager([adapter])

    for interval in (0, -1, float("inf"), float("nan"), 3601):
        runtime = CommentRuntime(manager, poll_interval_s=interval)
        assert runtime.start() is False

    runtime = CommentRuntime(manager, poll_interval_s=1.0)
    runtime.stop()
    assert runtime.start() is False
    assert adapter.poll_calls == 0
