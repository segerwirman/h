"""RED-first characterization of voice L1 late and audio lifecycle edges."""
from __future__ import annotations

import asyncio
import threading
import time
import types

import pytest

from jarvis.core.action_registry import Action
from jarvis.core.resolver import FallthroughToLLM
from jarvis.integrations import voice_l1


class _Live:
    def __init__(self):
        self._is_speaking = False
        self.audio_in_queue = asyncio.Queue()
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
        self._is_speaking = bool(value)


class _Turn:
    def __init__(self, text: str):
        self.text = text
        self.reset_count = 0

    def reset(self):
        self.reset_count += 1


def _action() -> Action:
    return Action("app", "spotify", "open", {"app": "Spotify"})


def _new_loop():
    return asyncio.new_event_loop()


@pytest.fixture()
def event_capture(monkeypatch):
    events: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        voice_l1,
        "_event",
        lambda name, **data: events.append((name, data)),
    )
    return events


def test_late_resolver_returns_fail_open_without_late_local_side_effects():
    release = threading.Event()
    finished = threading.Event()

    def slow_resolver(_text, *, source):
        assert source == "voice"
        release.wait(timeout=2)
        finished.set()
        return _action()

    submitted: list[Action] = []

    async def submit(action, _live):
        submitted.append(action)
        return "tidak boleh terucap"

    live = _Live()
    turn = _Turn("buka spotify")
    hook = voice_l1.VoiceL1Hook(
        resolver=slow_resolver,
        submit=submit,
        timeout_s=0.01,
    )
    loop = _new_loop()
    try:
        started = time.monotonic()
        handled = loop.run_until_complete(hook(live, turn))
        elapsed = time.monotonic() - started

        assert handled is False
        assert elapsed < 0.09
        assert submitted == []
        assert live.interrupts == 0
        assert live.spoken == []
        assert turn.reset_count == 0
        assert live._voice_l1_pending_audio.keys() == {"L2"}

        release.set()
        assert finished.wait(timeout=1)
        loop.run_until_complete(asyncio.sleep(0))
        assert submitted == []
        assert live.interrupts == 0
        assert live.spoken == []
    finally:
        release.set()
        finished.wait(timeout=1)
        loop.close()


def test_late_resolver_exception_stays_fail_open_after_timeout():
    release = threading.Event()
    finished = threading.Event()

    def slow_failure(_text, *, source):
        assert source == "voice"
        release.wait(timeout=2)
        finished.set()
        raise RuntimeError("resolver completed too late")

    live = _Live()
    hook = voice_l1.VoiceL1Hook(resolver=slow_failure, timeout_s=0.01)
    loop = _new_loop()
    try:
        handled = loop.run_until_complete(hook(live, _Turn("buka spotify")))
        assert handled is False
        assert live.interrupts == 0
        assert live.spoken == []
        release.set()
        assert finished.wait(timeout=1)
        loop.run_until_complete(asyncio.sleep(0))
        assert live.interrupts == 0
        assert live.spoken == []
    finally:
        release.set()
        finished.wait(timeout=1)
        loop.close()


def test_bounded_blocked_resolver_burst_fails_open_without_dispatch():
    release = threading.Event()
    lock = threading.Lock()
    started = 0
    finished = 0
    total = 4

    def slow_resolver(_text, *, source):
        nonlocal started, finished
        assert source == "voice"
        with lock:
            started += 1
        release.wait(timeout=2)
        with lock:
            finished += 1
        return _action()

    submitted: list[Action] = []

    async def submit(action, _live):
        submitted.append(action)
        return "tidak boleh terucap"

    hooks = [
        voice_l1.VoiceL1Hook(
            resolver=slow_resolver,
            submit=submit,
            timeout_s=0.01,
        )
        for _ in range(total)
    ]
    lives = [_Live() for _ in range(total)]
    turns = [_Turn(f"buka spotify {index}") for index in range(total)]
    loop = _new_loop()
    async def scenario():
        return await asyncio.gather(*(
            hook(live, turn)
            for hook, live, turn in zip(hooks, lives, turns)
        ))

    try:
        handled = loop.run_until_complete(scenario())
        assert handled == [False] * total
        assert submitted == []
        assert all(live.spoken == [] for live in lives)
        assert all(live.interrupts == 0 for live in lives)
        assert all(
            getattr(live, "_voice_l1_pending_audio", {}).keys() == {"L2"}
            for live in lives
        )

        release.set()
        deadline = time.monotonic() + 1
        while time.monotonic() < deadline:
            with lock:
                if finished == started:
                    break
            time.sleep(0.001)
        with lock:
            assert finished == started
            assert started <= total
        loop.run_until_complete(asyncio.sleep(0))
        assert submitted == []
    finally:
        release.set()
        loop.close()


def test_first_audio_consumes_pending_lane_once_and_measures_fresh_lane(
    event_capture,
):
    class MeterLive(_Live):
        pass

    legacy = types.SimpleNamespace(JarvisLive=MeterLive)
    voice_l1._install_meter(legacy)
    live = legacy.JarvisLive()

    voice_l1._mark_pending(live, "L1", time.monotonic() - 0.01)
    live.set_speaking(False)
    assert list(live._voice_l1_pending_audio) == ["L1"]
    live.set_speaking(True)
    live.set_speaking(True)

    first_audio = [data for name, data in event_capture
                   if name == "voice.first_audio"]
    assert len(first_audio) == 1
    assert first_audio[0]["lane"] == "L1"
    assert first_audio[0]["metric"] == "first_audio_ms"
    assert live._voice_l1_pending_audio == {}

    live.set_speaking(False)
    voice_l1._mark_pending(live, "L2", time.monotonic() - 0.01)
    live.set_speaking(True)

    first_audio = [data for name, data in event_capture
                   if name == "voice.first_audio"]
    assert len(first_audio) == 2
    assert first_audio[-1]["lane"] == "L2"
    assert live._voice_l1_pending_audio == {}


def test_first_audio_without_pending_lane_emits_nothing(event_capture):
    class MeterLive(_Live):
        pass

    legacy = types.SimpleNamespace(JarvisLive=MeterLive)
    voice_l1._install_meter(legacy)
    live = legacy.JarvisLive()

    live.set_speaking(True)
    live.set_speaking(False)
    live.set_speaking(True)

    assert [name for name, _data in event_capture] == []


def test_newer_l1_pending_turn_wins_over_older_l2_pending_turn(event_capture):
    class MeterLive(_Live):
        pass

    legacy = types.SimpleNamespace(JarvisLive=MeterLive)
    voice_l1._install_meter(legacy)
    live = legacy.JarvisLive()

    voice_l1._mark_pending(live, "L2", time.monotonic() - 0.20)
    voice_l1._mark_pending(live, "L1", time.monotonic() - 0.01)
    live.set_speaking(True)

    first_audio = [data for name, data in event_capture
                   if name == "voice.first_audio"]
    assert len(first_audio) == 1
    assert first_audio[0]["lane"] == "L1"
