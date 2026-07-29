"""Phase 1 voice seam: never execute a tool from partial speech."""
from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from jarvis.agent import router as agent_router
from jarvis.agent.router import Route, Tier
from jarvis.agent.voice_gate import VoiceToolGate


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
