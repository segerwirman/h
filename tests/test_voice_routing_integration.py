"""Integration tests for the root Gemini Live intent-to-action seam."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import time
import traceback
from pathlib import Path
from types import SimpleNamespace


def _receive_method(
    *, timeout_s: float = 2.5, l1_hook=None, text_only_hook=None
):
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    jarvis_live = next(
        node for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "JarvisLive"
    )
    method = next(
        node for node in jarvis_live.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "_receive_audio"
    )
    module = ast.fix_missing_locations(ast.Module(body=[method], type_ignores=[]))
    namespace = {
        "asyncio": asyncio,
        "time": time,
        "traceback": traceback,
        "datetime": __import__("datetime").datetime,
        "_clean_transcript": lambda value: str(value or "").strip(),
        "VOICE_TOOL_FINAL_TIMEOUT_S": timeout_s,
        "VOICE_L1_HOOK": l1_hook,
        "_voice_notices": None,
        "VOICE_TEXT_ONLY_HOOK": text_only_hook,
        "Outcome": SimpleNamespace(SUCCESS="success"),
    }
    exec(compile(module, "main.py", "exec"), namespace)
    return namespace["_receive_audio"]


def _response(
    *,
    text=None,
    finished=False,
    calls=None,
    cancelled=None,
    turn_complete=False,
    output_text=None,
    data=None,
):
    server_content = None
    if text is not None or output_text is not None or finished or turn_complete:
        server_content = SimpleNamespace(
            output_transcription=(
                SimpleNamespace(text=output_text)
                if output_text is not None else None
            ),
            input_transcription=(
                SimpleNamespace(text=text, finished=finished)
                if text is not None or finished else None
            ),
            turn_complete=turn_complete,
        )
    tool_call = None
    if calls is not None:
        tool_call = SimpleNamespace(function_calls=calls)
    cancellation = None
    if cancelled is not None:
        cancellation = SimpleNamespace(ids=cancelled)
    return SimpleNamespace(
        data=data,
        server_content=server_content,
        tool_call=tool_call,
        tool_call_cancellation=cancellation,
    )


class _Session:
    def __init__(self, responses, *, pause_after_first_send=False):
        self.responses = list(responses)
        self.sent = []
        self.sent_event = asyncio.Event()
        self.resume_after_first_send = asyncio.Event()
        self.pause_after_first_send = pause_after_first_send
        self._hold = asyncio.Event()
        self.send_error = None

    async def receive(self):
        for response in self.responses:
            yield response
        await self._hold.wait()

    async def send_tool_response(self, *, function_responses):
        if self.send_error is not None:
            error, self.send_error = self.send_error, None
            raise error
        self.sent.append(function_responses)
        self.sent_event.set()
        if self.pause_after_first_send and len(self.sent) == 1:
            await self.resume_after_first_send.wait()


class _RequestSequence:
    def __init__(self, request_ids):
        self._request_ids = iter(request_ids)

    def begin_request(self):
        return next(self._request_ids)

    def finish(self, _outcome):
        return None


class _Harness:
    def __init__(
        self,
        responses,
        *,
        dispatch_result=(True, "native started"),
        request_ids=(),
        pause_after_first_send=False,
    ):
        self.session = _Session(
            responses,
            pause_after_first_send=pause_after_first_send,
        )
        self.ui = SimpleNamespace(
            write_log=lambda _line: None,
            set_state=lambda _state: None,
            muted=False,
        )
        self.audio_in_queue = asyncio.Queue()
        self._turn_done_event = None
        self._interrupted = False
        self._sm = _RequestSequence(request_ids) if request_ids else None
        self._turn_id = ""
        self._awaiting_since = None
        self._last_user_speech = 0.0
        self._dashboard = None
        self._pending_vision = None
        self._vision_close_pending = False
        self.native_tasks = []
        self.legacy_calls = []
        self.trace_events = []
        self.spoken = []
        self.spoken_event = asyncio.Event()
        self.dispatch_result = dispatch_result
        self.native_telemetry = []

    def _sm_to(self, _state):
        return None

    def _trace(self, event, **fields):
        self.trace_events.append((event, fields))

    def _dispatch_native_agent(self, task, *, telemetry=None):
        self.native_tasks.append(task)
        self.native_telemetry.append(telemetry)
        return self.dispatch_result

    def speak(self, text):
        self.spoken.append(text)
        self.spoken_event.set()

    @staticmethod
    def _native_agent_tool_responses(calls, status):
        return [
            SimpleNamespace(id=call.id, name=call.name, status=status)
            for call in calls
        ]

    async def _execute_tool(self, call):
        self.legacy_calls.append(call.name)
        return SimpleNamespace(id=call.id, name=call.name, status="legacy")


async def _cancel(task):
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _wait_for_sent(session, count):
    deadline = time.monotonic() + 1.0
    while len(session.sent) < count and time.monotonic() < deadline:
        await asyncio.sleep(0.01)
    assert len(session.sent) >= count


async def _exercise_with_history(harness, history):
    harness._voice_call_history = history
    task = asyncio.create_task(_receive_method()(harness))
    await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
    await _cancel(task)


def test_voice_partial_tool_is_suppressed_then_final_heavy_dispatches_once():
    call = SimpleNamespace(id="open-1", name="open_app", args={})
    harness = _Harness([
        _response(text="buka"),
        _response(calls=[call]),
        _response(
            text="dan putar youtube deddy corbuzier terbaru",
            finished=True,
        ),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method()(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == [
        "buka dan putar youtube deddy corbuzier terbaru"
    ]
    assert harness.legacy_calls == []
    assert harness.session.sent[0][0].name == "open_app"


def test_voice_legacy_youtube_tool_is_suppressed_for_latest_play_task():
    call = SimpleNamespace(id="youtube-1", name="youtube_video", args={})
    harness = _Harness([
        _response(text="buka dan putar youtube"),
        _response(calls=[call]),
        _response(text="deddy corbuzier terbaru", finished=True),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method()(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == [
        "buka dan putar youtube deddy corbuzier terbaru"
    ]
    assert harness.legacy_calls == []
    assert harness.session.sent[0][0].name == "youtube_video"


def test_voice_final_light_releases_existing_tool_path_once():
    call = SimpleNamespace(id="weather-1", name="weather_report", args={})
    harness = _Harness([
        _response(text="bagaimana cuaca hari ini?", finished=True),
        _response(calls=[call]),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method()(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == []
    assert harness.legacy_calls == ["weather_report"]
    assert harness.session.sent[0][0].status == "legacy"


def test_voice_missing_final_defaults_heavy_and_never_runs_partial_tool():
    call = SimpleNamespace(id="open-2", name="open_app", args={})
    harness = _Harness([
        _response(text="buka"),
        _response(calls=[call]),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method(timeout_s=0.01)(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == ["buka"]
    assert harness.legacy_calls == []


def test_voice_cancellation_discards_buffered_call():
    call = SimpleNamespace(id="cancel-1", name="open_app", args={})
    harness = _Harness([
        _response(text="buka"),
        _response(calls=[call]),
        _response(cancelled=["cancel-1"]),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method(timeout_s=0.01)(harness))
        await asyncio.sleep(0.2)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == []
    assert harness.legacy_calls == []
    assert harness.session.sent == []


def test_turn_complete_before_final_transcript_does_not_leak_turn_state():
    weather = SimpleNamespace(id="weather-2", name="weather_report", args={})
    harness = _Harness([
        _response(turn_complete=True),
        _response(text="riset topik ini", finished=True),
        _response(text="bagaimana cuaca hari ini?", finished=True),
        _response(calls=[weather]),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method()(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == ["riset topik ini"]
    assert harness.legacy_calls == ["weather_report"]


def test_turn_complete_keeps_empty_pending_call_until_safe_timeout():
    call = SimpleNamespace(id="early-1", name="open_app", args={})
    harness = _Harness([
        _response(calls=[call]),
        _response(turn_complete=True),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method(timeout_s=0.01)(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await asyncio.wait_for(harness.spoken_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == []
    assert harness.legacy_calls == []
    assert harness.session.sent[0][0].name == "open_app"
    assert "tidak lengkap" in harness.spoken[0].lower()


def test_duplicate_call_id_after_timeout_runs_and_traces_only_once():
    duplicate = SimpleNamespace(
        id="repeat-after-timeout", name="open_app", args={}
    )
    harness = _Harness([
        _response(text="buka"),
        _response(calls=[duplicate]),
        _response(text="buka"),
        _response(calls=[duplicate]),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method(timeout_s=0.01)(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await asyncio.sleep(0.2)
        await _cancel(task)

    asyncio.run(_run())

    assert len(harness.native_tasks) == 1
    assert harness.legacy_calls == []
    assert [event for event, _fields in harness.trace_events
            if event == "voice.route_timeout"] == ["voice.route_timeout"]


def test_delivered_call_id_replays_cached_response_after_reconnect():
    from jarvis.agent.voice_gate import FunctionCallHistory

    duplicate = SimpleNamespace(
        id="repeat-after-reconnect", name="weather_report", args={}
    )
    history = FunctionCallHistory(limit=8)

    async def _exercise(harness):
        harness._voice_call_history = history
        task = asyncio.create_task(_receive_method()(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await _cancel(task)

    first = _Harness([
        _response(text="cuaca", finished=True),
        _response(calls=[duplicate]),
    ])
    asyncio.run(_exercise(first))

    second = _Harness([
        _response(text="cuaca lagi", finished=True),
        _response(calls=[duplicate]),
    ])
    asyncio.run(_exercise(second))

    assert first.legacy_calls == ["weather_report"]
    assert second.legacy_calls == []
    assert second.session.sent[0][0] is first.session.sent[0][0]


def test_disconnect_after_execution_replays_cached_response_without_rerun():
    from jarvis.agent.voice_gate import FunctionCallHistory

    call = SimpleNamespace(id="executed-not-sent", name="weather_report", args={})
    history = FunctionCallHistory(limit=8)
    first = _Harness([
        _response(text="cuaca", finished=True),
        _response(calls=[call]),
    ])
    first._voice_call_history = history
    first.session.send_error = ConnectionError("disconnect after execution")

    async def _first_attempt():
        with contextlib.suppress(ConnectionError):
            await _receive_method()(first)

    asyncio.run(_first_attempt())
    assert first.legacy_calls == ["weather_report"]
    assert history.state(call.id) == "result_cached"

    replay = _Harness([
        _response(text="cuaca lagi", finished=True),
        _response(calls=[call]),
    ])
    asyncio.run(_exercise_with_history(replay, history))

    assert replay.legacy_calls == []
    assert replay.session.sent[0][0].status == "legacy"
    assert history.state(call.id) == "delivered"


def test_delivery_marks_original_call_id_when_response_id_is_missing():
    from jarvis.agent.voice_gate import FunctionCallHistory

    call = SimpleNamespace(id="original-id", name="weather_report", args={})
    history = FunctionCallHistory(limit=8)
    harness = _Harness([
        _response(text="cuaca", finished=True),
        _response(calls=[call]),
    ])

    async def execute_without_response_id(tool_call):
        harness.legacy_calls.append(tool_call.name)
        return SimpleNamespace(name=tool_call.name, status="legacy")

    harness._execute_tool = execute_without_response_id
    asyncio.run(_exercise_with_history(harness, history))

    assert history.state(call.id) == "delivered"


def test_reconnect_after_execution_started_reports_unknown_without_rerun():
    from jarvis.agent.voice_gate import FunctionCallHistory

    call = SimpleNamespace(id="unknown-side-effect", name="send_message", args={})
    history = FunctionCallHistory(limit=8)
    assert history.start(call.id) is True
    history.mark_unknown(call.id)
    replay = _Harness([
        _response(text="kirim pesan", finished=True),
        _response(calls=[call]),
    ])
    asyncio.run(_exercise_with_history(replay, history))

    assert replay.legacy_calls == []
    response = replay.session.sent[0][0]
    assert "tidak diketahui" in response.status
    assert history.state(call.id) == "delivered"


def test_failed_unknown_disposition_remains_unknown_for_next_reconnect():
    from jarvis.agent.voice_gate import FunctionCallHistory

    call = SimpleNamespace(id="unknown-not-sent", name="send_message", args={})
    history = FunctionCallHistory(limit=8)
    assert history.start(call.id) is True
    history.mark_unknown(call.id)
    first = _Harness([
        _response(text="kirim pesan", finished=True),
        _response(calls=[call]),
    ])
    first._voice_call_history = history
    first.session.send_error = ConnectionError("disconnect before disposition")

    async def _first_attempt():
        with contextlib.suppress(ConnectionError):
            await _receive_method()(first)

    asyncio.run(_first_attempt())
    assert first.legacy_calls == []
    assert history.state(call.id) == "unknown"
    assert history.result(call.id) is None

    replay = _Harness([
        _response(text="kirim pesan", finished=True),
        _response(calls=[call]),
    ])
    asyncio.run(_exercise_with_history(replay, history))
    assert replay.legacy_calls == []
    assert "tidak diketahui" in replay.session.sent[0][0].status


def test_l1_handled_transcript_sends_disposition_for_associated_batch():
    call = SimpleNamespace(id="l1-open", name="open_app", args={})

    async def l1_hook(_live, _gate):
        return True

    harness = _Harness([
        _response(calls=[call]),
        _response(text="buka spotify", finished=True),
    ])

    async def _run():
        task = asyncio.create_task(
            _receive_method(l1_hook=l1_hook)(harness)
        )
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == []
    assert harness.legacy_calls == []
    assert "jalur lokal L1" in harness.session.sent[0][0].status


def test_l1_handled_transcript_keeps_late_function_call_for_disposition():
    call = SimpleNamespace(id="l1-late", name="open_app", args={})

    async def l1_hook(_live, _gate):
        return True

    harness = _Harness([
        _response(text="buka spotify", finished=True),
        _response(calls=[call]),
    ])

    async def _run():
        task = asyncio.create_task(
            _receive_method(l1_hook=l1_hook)(harness)
        )
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == []
    assert harness.legacy_calls == []
    assert "jalur lokal L1" in harness.session.sent[0][0].status


def test_l1_disposition_does_not_suppress_next_non_l1_batch():
    l1_call = SimpleNamespace(id="l1-first", name="open_app", args={})
    weather = SimpleNamespace(id="l2-next", name="weather_report", args={})
    handled = False

    async def l1_hook(_live, _gate):
        nonlocal handled
        if not handled:
            handled = True
            return True
        return False

    harness = _Harness([
        _response(text="buka spotify", finished=True),
        _response(calls=[l1_call]),
        _response(turn_complete=True),
        _response(text="bagaimana cuaca", finished=True),
        _response(calls=[weather]),
    ])

    async def _run():
        task = asyncio.create_task(
            _receive_method(l1_hook=l1_hook)(harness)
        )

        async def wait_for_responses():
            while len(harness.session.sent) < 2:
                await asyncio.sleep(0)

        await asyncio.wait_for(wait_for_responses(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.legacy_calls == ["weather_report"]
    assert "jalur lokal L1" in harness.session.sent[0][0].status
    assert harness.session.sent[1][0].status == "legacy"


def test_heavy_native_handoff_does_not_arm_live_response_watchdog():
    call = SimpleNamespace(id="native-long", name="web_search", args={})
    harness = _Harness([
        _response(text="riset topik ini", finished=True),
        _response(calls=[call]),
    ])
    harness._awaiting_since = 123.0

    async def _run():
        task = asyncio.create_task(_receive_method()(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == ["riset topik ini"]
    assert harness._awaiting_since is None


def test_heavy_function_call_has_correlated_id_and_deferred_success_outcome():
    call = SimpleNamespace(id="status-live-1", name="system_reflex", args={})
    harness = _Harness([
        _response(text="jalankan fungsi status sistem", finished=True),
        _response(calls=[call]),
        _response(turn_complete=True),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method()(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        await asyncio.sleep(0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == ["jalankan fungsi status sistem"]
    assert harness.native_telemetry[0]["call_ids"] == ["status-live-1"]

    received = [
        fields for event, fields in harness.trace_events
        if event == "voice.function_call.received"
    ]
    assert received == [{
        "call_id": "status-live-1",
        "function": "system_reflex",
        "id_present": True,
    }]

    dispositions = [
        fields for event, fields in harness.trace_events
        if event == "voice.function_call.disposition"
    ]
    assert dispositions == [{
        "call_id": "status-live-1",
        "function": "system_reflex",
        "disposition": "routed_to_native",
        "state": "delivered",
    }]

    outcomes = [
        fields for event, fields in harness.trace_events
        if event == "turn.outcome"
    ]
    assert outcomes == [{
        "outcome": "success",
        "had_input": True,
        "had_output": False,
        "completion": "deferred_native_agent",
        "function_call_ids": ["status-live-1"],
    }]


def test_post_agent_outcome_call_is_suppressed_for_the_same_voice_request():
    first = SimpleNamespace(id="status-first", name="system_reflex", args={})
    followup = SimpleNamespace(id="status-followup", name="system_reflex", args={})
    harness = _Harness(
        [
            _response(text="jalankan fungsi status sistem", finished=True),
            _response(calls=[first]),
            _response(turn_complete=True),
            _response(calls=[followup]),
        ],
        request_ids=["voice-request-one"],
        pause_after_first_send=True,
    )

    async def _run():
        task = asyncio.create_task(_receive_method(timeout_s=0.01)(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        harness.native_telemetry[0]["terminal_outcome"] = "success"
        harness.session.resume_after_first_send.set()
        await _wait_for_sent(harness.session, 2)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == ["jalankan fungsi status sistem"]
    assert harness.legacy_calls == []
    assert harness.session.sent[1][0].id == "status-followup"
    assert "sudah selesai" in harness.session.sent[1][0].status.lower()
    suppressed = [
        fields for event, fields in harness.trace_events
        if event == "voice.function_call.suppressed"
        and fields.get("call_id") == "status-followup"
    ]
    assert suppressed == [{
        "call_id": "status-followup",
        "function": "system_reflex",
        "state": "new",
        "reason": "request_already_terminal",
        "agent_outcome": "success",
    }]


def test_post_agent_outcome_guard_does_not_block_a_new_voice_request():
    first = SimpleNamespace(id="request-one", name="system_reflex", args={})
    second = SimpleNamespace(id="request-two", name="system_reflex", args={})
    harness = _Harness(
        [
            _response(text="jalankan fungsi status sistem", finished=True),
            _response(calls=[first]),
            _response(turn_complete=True),
            _response(text="jalankan fungsi status sistem lagi", finished=True),
            _response(calls=[second]),
        ],
        request_ids=["voice-request-one", "voice-request-two"],
        pause_after_first_send=True,
    )

    async def _run():
        task = asyncio.create_task(_receive_method()(harness))
        await asyncio.wait_for(harness.session.sent_event.wait(), timeout=1.0)
        harness.native_telemetry[0]["terminal_outcome"] = "success"
        harness.session.resume_after_first_send.set()
        await _wait_for_sent(harness.session, 2)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == [
        "jalankan fungsi status sistem",
        "jalankan fungsi status sistem lagi",
    ]
    assert [item[0].id for item in harness.session.sent] == [
        "request-one",
        "request-two",
    ]
    assert not [
        fields for event, fields in harness.trace_events
        if event == "voice.function_call.suppressed"
        and fields.get("reason") == "request_already_terminal"
    ]


def test_voice_agent_unavailable_is_spoken_after_turn_boundary():
    harness = _Harness(
        [
            _response(text="riset topik ini", finished=True),
            _response(turn_complete=True),
        ],
        dispatch_result=(False, "Agent native belum dikonfigurasi."),
    )

    async def _run():
        task = asyncio.create_task(_receive_method()(harness))
        await asyncio.wait_for(harness.spoken_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == ["riset topik ini"]
    assert harness.legacy_calls == []
    assert harness.spoken == ["Agent native belum dikonfigurasi."]


def test_voice_agent_unavailable_has_bounded_audible_fallback_without_turn_end():
    harness = _Harness(
        [_response(text="riset topik ini", finished=True)],
        dispatch_result=(False, "Agent native belum dikonfigurasi."),
    )

    async def _run():
        task = asyncio.create_task(_receive_method(timeout_s=0.01)(harness))
        await asyncio.wait_for(harness.spoken_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.spoken == ["Agent native belum dikonfigurasi."]
    assert harness.legacy_calls == []


def test_cancellation_after_turn_complete_still_runs_zero_actions():
    call = SimpleNamespace(id="cancel-late", name="open_app", args={})
    harness = _Harness([
        _response(text="buka"),
        _response(calls=[call]),
        _response(turn_complete=True),
        _response(cancelled=["cancel-late"]),
    ])

    async def _run():
        task = asyncio.create_task(_receive_method(timeout_s=0.01)(harness))
        await asyncio.sleep(0.2)
        await _cancel(task)

    asyncio.run(_run())

    assert harness.native_tasks == []
    assert harness.legacy_calls == []
    assert harness.session.sent == []
    assert harness.spoken == []
    cancelled = [
        fields for event, fields in harness.trace_events
        if event == "voice.function_call.cancelled"
    ]
    assert cancelled == [{
        "call_id": "cancel-late",
        "accepted": True,
        "state": "cancelled",
    }]


def test_text_only_output_is_reported_at_the_turn_boundary():
    observed = []
    observed_event = asyncio.Event()

    async def hook(live, text, *, had_audio):
        observed.append((live, text, had_audio))
        observed_event.set()

    harness = _Harness([
        _response(output_text="Mesin diesel bekerja dengan kompresi.",
                  turn_complete=True),
    ])

    async def _run():
        task = asyncio.create_task(
            _receive_method(text_only_hook=hook)(harness))
        await asyncio.wait_for(observed_event.wait(), timeout=1.0)
        await _cancel(task)

    asyncio.run(_run())

    assert observed == [
        (harness, "Mesin diesel bekerja dengan kompresi.", False),
    ]
