"""PROMPT M — hook L1 voice harus fail-open dan tidak menyentuh audio loop."""
from __future__ import annotations

import asyncio
import json
import statistics
import time
import types

import pytest

from jarvis.core import app_registry as apps
from jarvis.core.action_registry import Action
from jarvis.core.resolver import ClarifyNeeded, FallthroughToLLM, resolve
from jarvis.integrations import voice_l1


class _FakeLive:
    def __init__(self, *, speaking: bool = False):
        self._is_speaking = speaking
        self.interrupts = 0
        self.spoken: list[str] = []
        self.state_events: list[bool] = []

    def interrupt(self):
        self.interrupts += 1
        self._is_speaking = False

    def speak(self, text: str):
        self.spoken.append(text)

    def set_speaking(self, value: bool):
        self.state_events.append(bool(value))


def _app_action() -> Action:
    return Action("app", "spotify", "open", {"app": "Spotify"})


def test_disabled_install_is_true_noop(monkeypatch):
    legacy = types.SimpleNamespace(JarvisLive=_FakeLive, VOICE_L1_HOOK=None)
    monkeypatch.setattr(voice_l1.config, "get", lambda _path, default=None: False)

    assert voice_l1.install(legacy) is False
    assert legacy.VOICE_L1_HOOK is None
    assert legacy.JarvisLive.set_speaking is _FakeLive.set_speaking


class _QueuedAudio:
    def empty(self):
        return False


class _FinalTurn:
    def __init__(self, text: str):
        self.text = text
        self.reset_count = 0

    def reset(self):
        self.reset_count += 1


def test_l1_interrupts_prior_output_then_schedules_and_confirms(monkeypatch):
    submitted: list[Action] = []

    async def submit(action, _live):
        submitted.append(action)
        return "Membuka Spotify."

    hook = voice_l1.VoiceL1Hook(
        resolver=lambda *_args, **_kw: _app_action(),
        submit=submit,
        timeout_s=0.05,
    )
    live = _FakeLive(speaking=False)
    live.audio_in_queue = _QueuedAudio()
    turn = _FinalTurn("buka spotify")

    assert asyncio.run(hook(live, turn)) is True
    assert live.interrupts == 1
    assert turn.reset_count == 1
    assert submitted == [_app_action()]
    assert live.spoken == ["Membuka Spotify."]
    assert "L1" in getattr(live, "_voice_l1_pending_audio")


def test_non_l1_falls_open_and_marks_l2_audio_measurement():
    hook = voice_l1.VoiceL1Hook(
        resolver=lambda *_args, **_kw: FallthroughToLLM("conversation_marker"),
        timeout_s=0.05,
    )
    live = _FakeLive()

    assert asyncio.run(hook(live, "gimana cara buka spotify")) is False
    assert live.interrupts == 0
    assert live.spoken == []
    assert "L2" in getattr(live, "_voice_l1_pending_audio")


@pytest.fixture()
def active_registry(monkeypatch, tmp_path):
    from jarvis.core import action_registry

    monkeypatch.setattr(apps, "_index", {
        "spotify": apps.AppMatch("spotify", "Spotify", "Spotify.lnk", "start_menu"),
        "instagram": apps.AppMatch("instagram", "Instagram", "Instagram.lnk", "start_menu"),
    })
    monkeypatch.setattr(apps, "_index_built_at", 9e9)
    monkeypatch.setattr(apps.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(apps, "_store_path", lambda: tmp_path / "aliases.json")
    return action_registry.ActionRegistry().refresh()


@pytest.mark.parametrize("text,outcome_type", [
    ("gimana cara buka spotify", FallthroughToLLM),
    ("buka instagram", ClarifyNeeded),
    ("cari berita hari ini", FallthroughToLLM),
    ("apa cuaca hari ini", FallthroughToLLM),
])
def test_enabled_hook_negative_cases_fall_open_without_side_effects(active_registry, text, outcome_type):
    submitted: list[Action] = []

    async def submit(action, _live):
        submitted.append(action)
        return "tidak boleh terucap"

    def resolver(command, *, source):
        outcome = resolve(command, source=source, registry=active_registry)
        assert isinstance(outcome, outcome_type)
        return outcome

    live = _FakeLive()
    hook = voice_l1.VoiceL1Hook(resolver=resolver, submit=submit, timeout_s=0.05)

    assert asyncio.run(hook(live, text)) is False
    assert submitted == []
    assert live.interrupts == 0
    assert live.spoken == []
    assert "L2" in getattr(live, "_voice_l1_pending_audio")


def test_enabled_hook_boundary_benchmark_20_transcripts(active_registry, monkeypatch):
    original_get = voice_l1.config.get
    monkeypatch.setattr(
        voice_l1.config,
        "get",
        lambda path, default=None: True if path == "routing.voice_l1_hook.enabled"
        else original_get(path, default),
    )
    assert voice_l1._enabled(), "benchmark must only run with voice_l1_hook enabled"
    cases = (
        ("L1", "buka spotify"), ("L1", "tutup spotify"),
        ("L1", "naikkan volume"), ("L1", "turunkan volume"),
        ("L1", "matikan suara"), ("L1", "buka spotify"),
        ("L1", "tutup spotify"), ("L1", "naikkan volume"),
        ("L2", "gimana cara buka spotify"), ("L2", "buka instagram"),
        ("L2", "cari berita hari ini"), ("L2", "apa cuaca hari ini"),
        ("L2", "putar lagu favorit"), ("L2", "jelaskan quantum computing"),
        ("L2", "buka kamera"), ("L2", "tutup semua"),
        ("L2", "spotify bagus nggak sih?"), ("L2", "nyalakan wifi"),
        ("L2", "screenshot layar sekarang"), ("L2", "kapan hujan turun?"),
    )
    dispatched: list[Action] = []

    async def submit(action, _live):
        dispatched.append(action)
        return "aksi tersubmit"

    hook = voice_l1.VoiceL1Hook(
        resolver=lambda text, *, source: resolve(text, source=source, registry=active_registry),
        submit=submit,
        timeout_s=0.05,
    )

    async def run_cases():
        samples = {"L1": [], "L2": []}
        for expected_lane, transcript in cases:
            live = _FakeLive()
            started = time.perf_counter_ns()
            handled = await hook(live, transcript)
            elapsed_ms = (time.perf_counter_ns() - started) / 1_000_000
            lane = "L1" if handled else "L2"
            assert lane == expected_lane, transcript
            samples[lane].append(elapsed_ms)
        return samples

    samples = asyncio.run(run_cases())
    assert len(dispatched) == 8
    assert {lane: len(values) for lane, values in samples.items()} == {"L1": 8, "L2": 12}
    summary = {
        lane: {
            "n": len(values),
            "median_ms": round(statistics.median(values), 3),
            "p95_ms": round(statistics.quantiles(values, n=100, method="inclusive")[94], 3),
        }
        for lane, values in samples.items()
    }
    print("VOICE_HOOK_BOUNDARY_BENCHMARK=" + json.dumps(summary, sort_keys=True))


def test_resolver_timeout_falls_open_within_budget():
    def slow_resolver(*_args, **_kwargs):
        time.sleep(0.12)
        return _app_action()

    hook = voice_l1.VoiceL1Hook(resolver=slow_resolver, timeout_s=0.01)
    live = _FakeLive()
    async def scenario():
        start = time.monotonic()
        handled = await hook(live, "buka spotify")
        return handled, time.monotonic() - start

    # asyncio.run() waits for its default executor at loop shutdown. Production
    # keeps the Gemini loop alive, so assert latency before that shutdown phase.
    loop = asyncio.new_event_loop()
    try:
        handled, elapsed = loop.run_until_complete(scenario())
    finally:
        loop.close()
    assert handled is False
    assert elapsed < 0.09
    assert live.spoken == []
    assert "L2" in getattr(live, "_voice_l1_pending_audio")


def test_frozen_hook_guard_is_default_noop_shape():
    from pathlib import Path

    source = Path("main.py").read_text(encoding="utf-8-sig").replace("\r\n", "\n")
    expected = (
        "VOICE_L1_HOOK = None  # optional; None preserves the legacy voice path\n"
        "VOICE_NOTICE = None  # optional; None preserves legacy notice delivery\n"
        "VOICE_TEXT_ONLY_HOOK = None  # optional; None preserves legacy voice path\n"
        "\n\nclass _VoiceStopRequested"
    )
    boundary = (
        "if finished:\n"
        "                                final_voice_text = voice_gate.text\n"
        "                                l1_handled = bool(\n"
        "                                    VOICE_L1_HOOK\n"
        "                                    and await VOICE_L1_HOOK(self, voice_gate)\n"
        "                                )\n"
        "                                if l1_handled and voice_gate.route is None:\n"
        "                                    voice_gate.add_transcription(\n"
        "                                        final_voice_text,\n"
        "                                        finished=True,\n"
        "                                    )\n"
        "                                if not l1_handled:\n"
        "                                    _claim_heavy_route()\n"
        "                                batch_sent = await _flush_tool_batch(batch)"
    )
    text_only_boundary = (
        "if VOICE_TEXT_ONLY_HOOK and full_out:\n"
        "                                await VOICE_TEXT_ONLY_HOOK(\n"
        "                                    self, full_out, had_audio=turn_had_audio)"
    )
    assert expected in source
    assert boundary in source
    assert text_only_boundary in source


def test_disabled_guard_preserves_legacy_body_for_ten_voice_commands():
    async def guarded(hook, text, calls):
        if hook and await hook(None, text):
            return "handled"
        calls.append(text)
        return "legacy"

    commands = (
        "buka spotify", "tutup chrome", "naikkan volume", "cari berita hari ini",
        "gimana cara buka spotify", "putar lagu", "buka kamera", "apa cuaca hari ini",
        "buka instagram", "matikan suara",
    )
    legacy_calls: list[str] = []
    assert [asyncio.run(guarded(None, command, legacy_calls)) for command in commands] == ["legacy"] * 10
    assert legacy_calls == list(commands)


def test_meter_records_first_audio_only_after_pending_turn(monkeypatch):
    events: list[dict] = []
    legacy = types.SimpleNamespace(JarvisLive=_FakeLive, VOICE_L1_HOOK=None)
    monkeypatch.setattr(voice_l1.config, "get", lambda path, default=None: {
        "routing.voice_l1_hook.enabled": True,
        "routing.voice_l1_hook.timeout_ms": 50,
    }.get(path, default))
    monkeypatch.setattr(voice_l1, "_event", lambda _name, **data: events.append(data))

    assert voice_l1.install(legacy) is True
    live = legacy.JarvisLive()
    live._voice_l1_pending_audio = {"L1": time.monotonic() - 0.01}
    live.set_speaking(True)
    live.set_speaking(True)

    assert len(events) == 1
    assert events[0]["lane"] == "L1"
    assert events[0]["metric"] == "first_audio_ms"
