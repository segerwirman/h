"""Deprecated Hermes dispatch: ACK callback failures stay observable."""
from __future__ import annotations

import time

from jarvis.core import quiet
from jarvis.integrations.hermes import async_dispatch


def test_ack_callback_failure_records_event_and_dispatch_stays_fail_open(
    monkeypatch,
):
    events = []

    class Bridge:
        def available(self):
            return True

        def run_task(self, _task, timeout_s=None):
            return {"ok": True, "stdout": "done", "stderr": ""}

    def ack_failure(_message):
        raise OSError("ack unavailable")

    monkeypatch.setattr(async_dispatch, "is_enabled", lambda: True)
    monkeypatch.setattr(async_dispatch.HermesBridge, "get", lambda: Bridge())
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )
    monkeypatch.setattr(async_dispatch.BUS, "publish", lambda *_args, **_kwargs: None)

    assert async_dispatch.dispatch_async("offline task", on_ack=ack_failure)
    deadline = time.time() + 2
    while time.time() < deadline and async_dispatch.active_count():
        time.sleep(0.01)

    assert async_dispatch.active_count() == 0
    assert len(events) == 1
    assert events[0][0] == "integrations.hermes.async_dispatch.ack_callback_failed"
    assert isinstance(events[0][1], OSError)
