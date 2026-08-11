"""Phase 1 voice seam: never execute a tool from partial speech."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from jarvis.agent import router as agent_router
from jarvis.agent.router import Route, Tier
from jarvis.agent.voice_gate import FunctionCallHistory, VoiceToolGate


def _route(tier: Tier) -> Route:
    lane = "heavy" if tier >= Tier.AGENT else "light"
    return Route(tier, lane, lane, "test", 1.0)


def test_partial_tool_call_waits_for_final_heavy_transcript():
    seen = []

    def classify(text, context):
        seen.append((text, context))
        return _route(Tier.AGENT)

    gate = VoiceToolGate(classify)
    call = SimpleNamespace(id="open-1", name="open_app")

    gate.add_transcription("buka")
    assert gate.queue_calls([call]) is None
    assert gate.pending_count == 1
    assert gate.claim_agent_task() is None

    batch = gate.add_transcription(
        "dan putar youtube deddy corbuzier terbaru",
        finished=True,
    )
    assert batch is not None
    assert batch.route.tier is Tier.AGENT
    assert batch.calls == (call,)
    assert gate.claim_agent_task() == (
        "buka dan putar youtube deddy corbuzier terbaru"
    )
    assert gate.claim_agent_task() is None
    assert seen == [(
        "buka dan putar youtube deddy corbuzier terbaru",
        {"source": "voice"},
    )]


def test_final_light_transcript_releases_legacy_tool_once():
    gate = VoiceToolGate(lambda _text, _ctx: _route(Tier.SINGLE))
    gate.add_transcription("bagaimana cuaca hari ini", finished=True)
    call = SimpleNamespace(id="weather-1", name="weather_report")

    batch = gate.queue_calls([call])
    assert batch is not None
    assert batch.route.tier is Tier.SINGLE
    assert batch.calls == (call,)
    assert gate.claim_agent_task() is None


def test_close_known_app_stays_out_of_native_agent_queue():
    gate = VoiceToolGate(agent_router.classify)
    call = SimpleNamespace(id="close-spotify", name="close_app")

    gate.add_transcription("tutup spotify", finished=True)
    batch = gate.queue_calls([call])

    assert batch is not None
    assert batch.route.tier is Tier.REFLEX
    assert batch.calls == (call,)
    assert gate.claim_agent_task() is None


def test_missing_final_marker_uses_complete_light_transcript():
    gate = VoiceToolGate(agent_router.classify)
    call = SimpleNamespace(id="app-1", name="open_app")
    gate.add_transcription("Jarvis, coba buka WhatsApp")
    gate.queue_calls([call])

    batch = gate.timeout()
    assert batch is not None
    assert batch.timed_out is True
    assert batch.route.tier is Tier.REFLEX
    assert gate.claim_agent_task() is None


def test_cancellation_discards_buffered_call_without_action():
    gate = VoiceToolGate(lambda _text, _ctx: _route(Tier.SINGLE))
    gate.add_transcription("buka")
    gate.queue_calls([
        SimpleNamespace(id="cancel-me", name="open_app"),
        SimpleNamespace(id="keep-me", name="weather_report"),
    ])

    assert gate.cancel(["cancel-me"]) == 1
    batch = gate.add_transcription("cuaca hari ini", finished=True)
    assert batch is not None
    assert [call.id for call in batch.calls] == ["keep-me"]


def test_heavy_final_without_tool_call_still_claims_native_agent():
    gate = VoiceToolGate(lambda _text, _ctx: _route(Tier.AGENT))
    assert gate.add_transcription("riset topik ini", finished=True) is None
    assert gate.claim_agent_task() == "riset topik ini"


def test_missing_final_without_tool_call_uses_available_transcript():
    gate = VoiceToolGate(lambda *_args: _route(Tier.SINGLE))
    gate.add_transcription("urus ini")
    assert gate.timeout() is None
    assert gate.route is not None
    assert gate.route.tier is Tier.SINGLE
    assert gate.claim_agent_task() is None


def test_late_final_marker_cannot_change_timeout_decision():
    gate = VoiceToolGate(lambda _text, _ctx: _route(Tier.SINGLE))
    gate.add_transcription("buka")
    gate.queue_calls([SimpleNamespace(id="late-1", name="open_app")])
    timed_out = gate.timeout()
    assert timed_out is not None
    assert timed_out.route.tier is Tier.SINGLE

    gate.add_transcription("spotify", finished=True)
    assert gate.route is not None
    assert gate.route.tier is Tier.SINGLE


def test_incomplete_action_still_fails_closed_to_agent():
    gate = VoiceToolGate(agent_router.classify)
    gate.add_transcription("buka")
    gate.queue_calls([SimpleNamespace(id="partial-1", name="open_app")])
    batch = gate.timeout()
    assert batch is not None
    assert batch.route.tier is Tier.AGENT
    assert gate.claim_agent_task() == "buka"


def test_released_call_is_recoverable_after_turn_reset():
    history = FunctionCallHistory(limit=8)
    gate = VoiceToolGate(
        lambda _text, _ctx: _route(Tier.SINGLE), history=history
    )
    call = SimpleNamespace(id="weather-released", name="weather_report")

    gate.add_transcription("bagaimana cuaca hari ini", finished=True)
    assert gate.queue_calls([call]) is not None

    gate.reset()
    gate.add_transcription("ulangi cuaca", finished=True)
    replay = gate.queue_calls([call])
    assert replay is not None
    assert replay.calls == (call,)


def test_released_call_is_recoverable_by_new_gate_after_reconnect():
    history = FunctionCallHistory(limit=8)
    first = VoiceToolGate(
        lambda _text, _ctx: _route(Tier.SINGLE), history=history
    )
    duplicate = SimpleNamespace(id="shared-call", name="weather_report")
    first.add_transcription("cuaca", finished=True)
    assert first.queue_calls([duplicate]) is not None

    reconnected = VoiceToolGate(
        lambda _text, _ctx: _route(Tier.SINGLE), history=history
    )
    reconnected.add_transcription("cuaca lagi", finished=True)
    replay = reconnected.queue_calls([duplicate])
    assert replay is not None
    assert replay.calls == (duplicate,)


def test_duplicate_pending_id_is_buffered_only_once():
    gate = VoiceToolGate(lambda _text, _ctx: _route(Tier.SINGLE))
    duplicate = SimpleNamespace(id="pending-once", name="weather_report")

    assert gate.queue_calls([duplicate, duplicate]) is None
    assert gate.pending_count == 1
    batch = gate.add_transcription("cuaca", finished=True)

    assert batch is not None
    assert batch.calls == (duplicate,)


def test_cancellation_after_release_prevents_late_replay():
    history = FunctionCallHistory(limit=8)
    gate = VoiceToolGate(
        lambda _text, _ctx: _route(Tier.SINGLE), history=history
    )
    call = SimpleNamespace(id="cancel-after-release", name="open_app")

    gate.add_transcription("buka spotify", finished=True)
    assert gate.queue_calls([call]) is not None
    assert gate.cancel([call.id]) == 0

    gate.reset()
    gate.add_transcription("buka spotify", finished=True)
    assert gate.queue_calls([call]) is None
    assert history.state(call.id) == "cancelled"



def test_cancelled_call_id_is_not_replayed_after_reset():
    history = FunctionCallHistory(limit=8)
    gate = VoiceToolGate(
        lambda _text, _ctx: _route(Tier.SINGLE), history=history
    )
    call = SimpleNamespace(id="cancel-final", name="open_app")
    gate.queue_calls([call])

    assert gate.cancel(["cancel-final"]) == 1
    gate.reset()
    assert gate.queue_calls([call]) is None
    assert gate.pending_count == 0


def test_unprocessed_buffered_call_can_be_recovered_after_reconnect():
    history = FunctionCallHistory(limit=8)
    first = VoiceToolGate(
        lambda _text, _ctx: _route(Tier.SINGLE), history=history
    )
    call = SimpleNamespace(id="recover-me", name="weather_report")
    first.queue_calls([call])

    reconnected = VoiceToolGate(
        lambda _text, _ctx: _route(Tier.SINGLE), history=history
    )
    reconnected.add_transcription("cuaca", finished=True)
    batch = reconnected.queue_calls([call])

    assert batch is not None
    assert batch.calls == (call,)


def test_call_history_is_bounded_and_evicts_oldest_id():
    history = FunctionCallHistory(limit=2)

    for call_id in ("one", "two", "three"):
        history.start(call_id)
        result = f"result-{call_id}"
        history.store_result(call_id, result)
        history.mark_delivered(call_id, result=result)

    assert list(history) == ["two", "three"]
    assert history.state("one") == "new"
    assert history.state("two") == "delivered"
    assert history.result("three") == "result-three"


def test_in_flight_replay_has_unknown_outcome_and_is_not_reexecuted():
    history = FunctionCallHistory(limit=8)

    assert history.start("side-effect") is True
    assert history.start("side-effect") is False
    assert history.state("side-effect") == "in_flight"
    history.mark_unknown("side-effect")
    assert history.state("side-effect") == "unknown"
    assert history.result("side-effect") is None


def test_stored_result_is_replayed_until_delivery():
    history = FunctionCallHistory(limit=8)
    response = SimpleNamespace(id="cached", status="done")

    assert history.start("cached") is True
    history.store_result("cached", response)

    assert history.state("cached") == "result_cached"
    assert history.result("cached") is response
    history.mark_delivered("cached", result=response)
    assert history.state("cached") == "delivered"
    assert history.result("cached") is response


def test_cancellation_cannot_erase_started_or_completed_call():
    history = FunctionCallHistory(limit=8)
    response = SimpleNamespace(id="done", status="done")

    assert history.start("started") is True
    history.cancel("started")
    assert history.state("started") == "in_flight"

    assert history.start("done") is True
    history.store_result("done", response)
    history.cancel("done")
    assert history.state("done") == "result_cached"
    assert history.result("done") is response


def test_unknown_outcome_response_is_cached_only_after_delivery():
    history = FunctionCallHistory(limit=8)
    response = SimpleNamespace(id="unknown", status="unknown")

    assert history.start("unknown") is True
    assert history.start("unknown") is False
    history.mark_unknown("unknown")
    assert history.state("unknown") == "unknown"
    assert history.result("unknown") is None

    history.mark_delivered("unknown", result=response)
    assert history.state("unknown") == "delivered"
    assert history.result("unknown") is response



def test_calls_without_id_are_never_silently_deduplicated():
    history = FunctionCallHistory(limit=2)
    gate = VoiceToolGate(
        lambda _text, _ctx: _route(Tier.SINGLE), history=history
    )
    call = SimpleNamespace(id="", name="weather_report")

    gate.add_transcription("cuaca", finished=True)
    batch = gate.queue_calls([call, call])
    assert batch is not None
    assert batch.calls == (call, call)

    gate.reset()
    gate.add_transcription("cuaca lagi", finished=True)
    assert gate.queue_calls([call]) is not None


def test_default_live_tool_schema_no_longer_exposes_hermes():
    tree = ast.parse(Path("main.py").read_text(encoding="utf-8"))
    declaration = next(
        node for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name)
            and target.id == "TOOL_DECLARATIONS"
            for target in node.targets
        )
    )
    tools = ast.literal_eval(declaration.value)
    assert "hermes_agent" not in {tool.get("name") for tool in tools}
