"""Arbitrasi kepemilikan mikrofon wake vs Gemini Live."""
from __future__ import annotations

from jarvis.integrations import voice_wake_arbitration


class _FakeWake:
    def __init__(self):
        self.starts = 0
        self.stops = 0

    def start(self):
        self.starts += 1

    def stop(self):
        self.stops += 1


class _FakeBus:
    def __init__(self):
        self.topic = None
        self.callback = None

    def subscribe(self, topic, callback):
        self.topic = topic
        self.callback = callback


def test_live_state_releases_wake_microphone_until_idle():
    wake = _FakeWake()
    bus = _FakeBus()

    arbiter = voice_wake_arbitration.install(wake, bus=bus)

    assert bus.topic == "pipeline.state"
    bus.callback({"state": "LISTENING"})
    assert wake.stops == 1

    # Perubahan state di dalam sesi yang sama tidak stop berulang kali.
    bus.callback({"state": "SPEAKING"})
    assert wake.stops == 1

    bus.callback({"state": "IDLE"})
    assert wake.starts == 1

    arbiter.close()
    bus.callback({"state": "LISTENING"})
    assert wake.stops == 1
