"""Integration tests for the root Gemini Live intent-to-action seam."""
from __future__ import annotations

import ast
import asyncio
import contextlib
import time
import traceback
from pathlib import Path
from types import SimpleNamespace


def _receive_method(*, timeout_s: float = 2.5, text_only_hook=None):
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
        "VOICE_L1_HOOK": None,
        "VOICE_NOTICE": None,
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
    def __init__(self, responses):
        self.responses = list(responses)
        self.sent = []
        self.sent_event = asyncio.Event()
        self._hold = asyncio.Event()

    async def receive(self):
        for response in self.responses:
            yield response
        await self._hold.wait()

    async def send_tool_response(self, *, function_responses):
        self.sent.append(function_responses)
        self.sent_event.set()


class _Harness:
    def __init__(self, responses, *, dispatch_result=(True, "native started")):
        self.session = _Session(responses)
        self.ui = SimpleNamespace(
            write_log=lambda _line: None,
            set_state=lambda _state: None,
            muted=False,
        )
        self.audio_in_queue = asyncio.Queue()
        self._turn_done_event = None
        self._interrupted = False
        self._sm = None
        self._turn_id = ""
        self._awaiting_since = None
        self._last_user_speech = 0.0
        self._dashboard = None
        self._pending_vision = None
        self._vision_close_pending = False
        self.native_tasks = []
        self.legacy_calls = []
        self.spoken = []
        self.spoken_event = asyncio.Event()
        self.dispatch_result = dispatch_result

    def _sm_to(self, _state):
        return None

    def _trace(self, _event, **_kwargs):
        return None

    def _dispatch_native_agent(self, task):
        self.native_tasks.append(task)
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
