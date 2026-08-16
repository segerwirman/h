"""Fase 45 contracts for microphone-originated interrupt ownership."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.integrations import voice_playback_level


@pytest.fixture(autouse=True)
def _reset_playback_state():
    voice_playback_level.reset()
    voice_playback_level.mark_uninstalled()
    yield
    voice_playback_level.reset()
    voice_playback_level.mark_uninstalled()


def _verdict():
    return SimpleNamespace(
        interrupt=True,
        rms=0.18,
        threshold=0.08,
        noise_floor=0.01,
    )


class _Stage:
    current = "info"


class _Window:
    def __init__(self):
        self._legacy_state = "LISTENING"
        self._voice_capture_generation = 4
        self._last_voice_interrupt_token = ""
        self.stage = _Stage()
        self.closed = 0
        self.interrupted = 0
        self.logs: list[str] = []
        self.on_interrupt = self._interrupt

    def _interrupt(self):
        self.interrupted += 1

    def _close_stage_panels(self):
        self.closed += 1

    def write_log(self, text: str):
        self.logs.append(text)


def _event(monkeypatch, *, now: float = 100.0):
    from jarvis.integrations import voice_interrupt

    monkeypatch.setattr(voice_interrupt.time, "monotonic", lambda: now)
    voice_playback_level.mark_installed()
    generation = voice_playback_level.mark_started(epoch=7, now=now - 0.2)
    event, reason = voice_interrupt.build_microphone_event(
        _Window(), _verdict(), detected_at=now
    )
    assert reason == "voice_interrupt_candidate"
    assert event is not None
    assert event.playback_generation == generation
    assert event.playback_epoch == 7
    return event


def test_voice_interrupt_bypasses_escape_panel_semantics(monkeypatch):
    from jarvis.ui.window_voice import WindowVoiceMixin

    event = _event(monkeypatch)
    win = _Window()

    WindowVoiceMixin._do_voice_interrupt(win, event)

    assert win.interrupted == 1
    assert win.closed == 0


def test_valid_event_survives_ui_state_change_after_detection(monkeypatch):
    from jarvis.integrations import voice_interrupt
    from jarvis.ui.window_voice import WindowVoiceMixin

    event = _event(monkeypatch)
    voice_playback_level.mark_drained(epoch=7, now=100.05)
    monkeypatch.setattr(voice_interrupt.time, "monotonic", lambda: 100.1)
    win = _Window()
    win._legacy_state = "IDLE"

    WindowVoiceMixin._do_voice_interrupt(win, event)

    assert win.interrupted == 1
    assert win.closed == 0


def test_old_playback_generation_cannot_interrupt_new_turn(monkeypatch):
    from jarvis.integrations import voice_interrupt
    from jarvis.ui.window_voice import WindowVoiceMixin

    event = _event(monkeypatch)
    voice_playback_level.mark_drained(epoch=7, now=100.05)
    voice_playback_level.mark_started(epoch=8, now=100.06)
    monkeypatch.setattr(voice_interrupt.time, "monotonic", lambda: 100.1)
    win = _Window()

    WindowVoiceMixin._do_voice_interrupt(win, event)

    assert win.interrupted == 0
    assert win.closed == 0


def test_same_voice_event_is_handled_exactly_once(monkeypatch):
    from jarvis.ui.window_voice import WindowVoiceMixin

    event = _event(monkeypatch)
    win = _Window()

    WindowVoiceMixin._do_voice_interrupt(win, event)
    WindowVoiceMixin._do_voice_interrupt(win, event)

    assert win.interrupted == 1
    assert win.closed == 0


def test_post_drain_detection_is_suppressed(monkeypatch):
    from jarvis.integrations import voice_interrupt

    monkeypatch.setattr(voice_interrupt.time, "monotonic", lambda: 50.1)
    voice_playback_level.mark_installed()
    voice_playback_level.mark_started(epoch=2, now=49.0)
    voice_playback_level.mark_drained(epoch=2, now=50.0)

    event, reason = voice_interrupt.build_microphone_event(
        _Window(), _verdict(), detected_at=50.1
    )

    assert event is None
    assert reason == "voice_interrupt_post_drain"


def test_mic_meter_emits_event_without_calling_escape_handler(monkeypatch):
    from jarvis.integrations import voice_interrupt
    from jarvis.ui.mic_meter import MicMeterController

    monkeypatch.setattr(voice_interrupt.time, "monotonic", lambda: 20.0)
    voice_playback_level.mark_installed()
    voice_playback_level.mark_started(epoch=3, now=19.5)
    emitted = []

    class _Signal:
        def emit(self, event):
            emitted.append(event)

    win = _Window()
    win._voice_interrupt_sig = _Signal()
    win._do_interrupt = lambda: pytest.fail("mic callback used ESC semantics")
    controller = MicMeterController(win, SimpleNamespace())

    controller._publish_interrupt(_verdict(), detected_at=20.0)

    assert len(emitted) == 1
    assert emitted[0].source == "microphone"


def test_playback_snapshot_tracks_authoritative_drain():
    voice_playback_level.mark_installed()
    generation = voice_playback_level.mark_started(epoch=9, now=1.0)
    active = voice_playback_level.snapshot(now=1.1)
    assert active.active is True
    assert active.generation == generation
    assert active.epoch == 9

    assert voice_playback_level.mark_drained(epoch=9, now=1.2) is True
    drained = voice_playback_level.snapshot(now=1.3)
    assert drained.active is False
    assert drained.generation == generation
    assert drained.drained_at == 1.2
