"""Fase 46C contracts for bounded microphone recovery."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
import threading

import pytest

from jarvis.integrations import voice_input_owner


class _Clock:
    def __init__(self, now: float = 0.0):
        self.now = now

    def __call__(self) -> float:
        return self.now


def _policy(**overrides):
    values = {
        "poll_s": 0.1,
        "startup_grace_s": 0.2,
        "stale_s": 0.3,
        "max_attempts": 2,
        "deadline_s": 2.0,
        "stable_s": 0.5,
    }
    values.update(overrides)
    return voice_input_owner.InputRecoveryPolicy(**values)


def test_watchdog_distinguishes_startup_grace_live_and_stale_callback():
    snapshot = voice_input_owner.InputHeartbeatSnapshot(
        generation=1,
        stream_opened_at=10.0,
    )
    policy = _policy()

    assert voice_input_owner.callback_failure(snapshot, 10.19, policy) is None
    assert isinstance(
        voice_input_owner.callback_failure(snapshot, 10.2, policy),
        voice_input_owner.InputCallbackStale,
    )

    live = voice_input_owner.InputHeartbeatSnapshot(
        generation=1,
        stream_opened_at=10.0,
        callback_at=11.0,
        callback_count=4,
    )
    assert voice_input_owner.callback_failure(live, 11.29, policy) is None
    assert isinstance(
        voice_input_owner.callback_failure(live, 11.3, policy),
        voice_input_owner.InputCallbackStale,
    )


def test_recovery_budget_is_bounded_by_attempts_and_deadline():
    budget = voice_input_owner.InputRecoveryBudget()
    policy = _policy(max_attempts=2, deadline_s=10.0)

    assert budget.register_failure(1.0, policy) is False
    assert budget.register_failure(2.0, policy) is False
    assert budget.register_failure(3.0, policy) is True

    deadline_budget = voice_input_owner.InputRecoveryBudget()
    assert deadline_budget.register_failure(5.0, policy) is False
    assert deadline_budget.register_failure(15.0, policy) is True


def test_only_a_stable_healthy_window_resets_recovery_budget():
    budget = voice_input_owner.InputRecoveryBudget()
    policy = _policy(stable_s=1.0)
    assert budget.register_failure(1.0, policy) is False

    budget.observe_healthy(2.0, policy)
    budget.observe_unhealthy()
    budget.observe_healthy(2.9, policy)
    assert budget.failures == 1

    budget.observe_healthy(4.0, policy, callback_at=2.9)
    assert budget.failures == 1

    budget.observe_healthy(4.0, policy, callback_at=3.9)
    assert budget.failures == 0
    assert budget.failure_started_at is None


class _Stream:
    def __init__(self, sd, **kwargs):
        self._sd = sd
        self.callback = kwargs["callback"]

    def __enter__(self):
        self._sd.opens += 1
        self._sd.callbacks.append(self.callback)
        return self

    def __exit__(self, *_args):
        self._sd.closes += 1
        return False


class _SoundDevice:
    def __init__(self):
        self.resolutions = 0
        self.opens = 0
        self.closes = 0
        self.callbacks = []

    def query_devices(self, device=None, kind=None):
        self.resolutions += 1
        info = {
            "name": "fake mic",
            "max_input_channels": 1,
            "max_output_channels": 0,
            "hostapi": 0,
        }
        if device is not None or kind == "input":
            return info
        return [info]

    def check_input_settings(self, **_kwargs):
        return None

    def InputStream(self, **kwargs):
        return _Stream(self, **kwargs)


def _legacy(sd):
    class Live:
        def __init__(self):
            self.ui = SimpleNamespace(
                _win=SimpleNamespace(_voice_capture_generation=0),
                muted=False,
            )
            self.out_queue = asyncio.Queue(maxsize=2)
            self._speaking_lock = threading.Lock()
            self._is_speaking = False
            self._phone_active = False
            self._stop_requested = threading.Event()
            self.stop_calls = 0

        def request_stop(self):
            self.stop_calls += 1
            self._stop_requested.set()

        async def run(self):
            return None

        async def _listen_audio(self):
            raise AssertionError("input owner was not installed")

    return SimpleNamespace(
        JarvisLive=Live,
        sd=sd,
        SEND_SAMPLE_RATE=16000,
        CHANNELS=1,
        CHUNK_SIZE=1024,
    )


def test_existing_reconnect_owner_reopens_resolves_and_stops_once(
    monkeypatch,
):
    from jarvis.core import config

    clock = _Clock()
    settings = {
        "voice.audio.input_device": None,
        "voice.audio.heartbeat_poll_s": 0.1,
        "voice.audio.callback_startup_grace_s": 0.2,
        "voice.audio.callback_stale_s": 0.3,
        "voice.audio.recovery_max_attempts": 2,
        "voice.audio.recovery_deadline_s": 5.0,
        "voice.audio.recovery_stable_s": 1.0,
    }
    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: settings.get(key, default),
    )
    monkeypatch.setattr(voice_input_owner.time, "monotonic", clock)
    original_sleep = asyncio.sleep

    async def fake_sleep(delay):
        clock.now += delay
        await original_sleep(0)

    monkeypatch.setattr(voice_input_owner.asyncio, "sleep", fake_sleep)
    sd = _SoundDevice()
    legacy = _legacy(sd)
    original_run = legacy.JarvisLive.run
    assert voice_input_owner.install(legacy) is True
    assert legacy.JarvisLive.run is original_run
    live = legacy.JarvisLive()

    async def reconnect_owner():
        failures = []
        for _ in range(3):
            try:
                await live._listen_audio()
            except voice_input_owner.InputRecoveryExhausted as exc:
                failures.append(type(exc))
                break
            except voice_input_owner.InputCallbackStale as exc:
                failures.append(type(exc))
        return failures

    failures = asyncio.run(reconnect_owner())

    assert failures == [
        voice_input_owner.InputCallbackStale,
        voice_input_owner.InputCallbackStale,
        voice_input_owner.InputRecoveryExhausted,
    ]
    assert sd.opens == sd.closes == 3
    assert sd.resolutions >= 3
    assert live.ui._win._voice_capture_generation == 3
    assert live.stop_calls == 1
    assert live._stop_requested.is_set()


def test_stop_requested_teardown_does_not_start_recovery(monkeypatch):
    from jarvis.core import config

    monkeypatch.setattr(config, "get", lambda _key, default=None: default)
    sd = _SoundDevice()
    legacy = _legacy(sd)
    voice_input_owner.install(legacy)
    live = legacy.JarvisLive()
    live._stop_requested.set()

    asyncio.run(live._listen_audio())

    assert sd.opens == 0
    assert live.stop_calls == 0
