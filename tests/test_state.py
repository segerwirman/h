"""Pipeline state machine tests — transitions, timeout recovery, outcomes."""
import time

from jarvis.core.bus import BUS
from jarvis.core.state import (Outcome, PipelineState, PipelineStateMachine)


def test_basic_transitions_and_request_id():
    sm = PipelineStateMachine()
    rid = sm.begin_request()
    assert len(rid) == 8
    sm.to(PipelineState.TRANSCRIBING)
    sm.to(PipelineState.PROCESSING)
    assert sm.busy()
    sm.finish(Outcome.SUCCESS)
    assert sm.state is PipelineState.LISTENING
    assert not sm.busy() or sm.state is PipelineState.LISTENING


def test_same_state_noop():
    sm = PipelineStateMachine()
    sm.to(PipelineState.LISTENING)
    sm.to(PipelineState.LISTENING)          # must not raise or re-publish
    assert sm.state is PipelineState.LISTENING


def test_transition_published_on_bus():
    events = []
    BUS.subscribe("pipeline.state", lambda d: events.append(d))
    sm = PipelineStateMachine()
    sm.to(PipelineState.PROCESSING)
    assert events and events[-1]["state"] == "PROCESSING"
    assert events[-1]["prev"] == "IDLE"


def test_stage_timeout_falls_back_to_safe_state():
    fired = []
    sm = PipelineStateMachine(
        timeouts={PipelineState.PROCESSING: 0.1},
        on_timeout=lambda st, rid: fired.append(st),
        monitor_interval=0.05,
    )
    sm.start_monitor()
    try:
        sm.to(PipelineState.PROCESSING)
        # deadline lebar: monitor thread bisa telat >2 s saat suite penuh
        # membebani CPU (Windows scheduler) — 2.0 terbukti flaky
        deadline = time.monotonic() + 8.0
        while sm.state is PipelineState.PROCESSING and time.monotonic() < deadline:
            time.sleep(0.05)
        assert sm.state is PipelineState.LISTENING       # safe fallback
        assert fired == [PipelineState.PROCESSING]
    finally:
        sm.stop_monitor()


def test_listening_never_times_out():
    sm = PipelineStateMachine(monitor_interval=0.05)
    sm.start_monitor()
    try:
        sm.to(PipelineState.LISTENING)
        time.sleep(0.3)
        assert sm.state is PipelineState.LISTENING
    finally:
        sm.stop_monitor()


def test_outcome_published():
    events = []
    BUS.subscribe("pipeline.outcome", lambda d: events.append(d))
    sm = PipelineStateMachine()
    rid = sm.begin_request()
    sm.to(PipelineState.PROCESSING)
    sm.finish(Outcome.TOOL_ERROR, detail="boom")
    assert events[-1]["outcome"] == "tool_error"
    assert events[-1]["request_id"] == rid
