"""Fase 46A contracts for one physical PC microphone owner."""
from __future__ import annotations

import asyncio
from array import array
from contextlib import suppress
import sys
import threading
from types import SimpleNamespace


class _MutableInput:
    def __init__(self, data: bytes):
        self.data = bytearray(data)

    def tobytes(self):
        return bytes(self.data)


class _InputStream:
    def __init__(self, owner, **kwargs):
        self._owner = owner
        self.kwargs = kwargs

    def __enter__(self):
        self._owner.active += 1
        self._owner.max_active = max(self._owner.max_active, self._owner.active)
        block = _MutableInput(b"\x01\x02\x03\x04")
        self.kwargs["callback"](block, 2, None, None)
        block.data[:] = b"\xff\xff\xff\xff"
        return self

    def __exit__(self, *_args):
        self._owner.active -= 1
        self._owner.closes += 1
        return False


class _SoundDevice:
    def __init__(self):
        self.opens = 0
        self.closes = 0
        self.active = 0
        self.max_active = 0
        self.input_kwargs = None

    def query_devices(self, device=None, kind=None):
        devices = [
            {
                "name": "physical mic",
                "max_input_channels": 1,
                "max_output_channels": 0,
                "hostapi": 0,
            },
            {
                "name": "physical speaker",
                "max_input_channels": 0,
                "max_output_channels": 2,
                "hostapi": 0,
            },
        ]
        if device is not None:
            return devices[device]
        if kind == "input":
            return devices[0]
        if kind == "output":
            return devices[1]
        return devices

    def query_hostapis(self, _index):
        return {"name": "MME"}

    def check_input_settings(self, **_kwargs):
        return None

    def check_output_settings(self, **_kwargs):
        return None

    def InputStream(self, **kwargs):
        self.opens += 1
        self.input_kwargs = kwargs
        return _InputStream(self, **kwargs)


def _legacy(sd):
    class Live:
        def __init__(self, ui):
            self.ui = ui
            self.out_queue = asyncio.Queue(maxsize=2)
            self._speaking_lock = threading.Lock()
            self._is_speaking = False
            self._phone_active = False

        async def run(self):
            return None

        async def _listen_audio(self):
            raise AssertionError("legacy listener must be replaced")

    return SimpleNamespace(
        JarvisLive=Live,
        sd=sd,
        SEND_SAMPLE_RATE=16000,
        RECEIVE_SAMPLE_RATE=24000,
        CHANNELS=1,
        CHUNK_SIZE=1024,
    )


def test_owner_opens_one_configured_stream_and_fans_out_owned_pcm(monkeypatch):
    from jarvis.core import config
    from jarvis.integrations import voice_audio_devices, voice_input_owner

    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: {
            "voice.audio.input_device": 0,
            "voice.audio.output_device": 1,
        }.get(key, default),
    )
    sd = _SoundDevice()
    legacy = _legacy(sd)
    original_run = legacy.JarvisLive.run
    original_input_stream = sd.InputStream

    assert voice_audio_devices.install(legacy) is True
    assert sd.InputStream == original_input_stream
    assert voice_input_owner.install(legacy) is True
    assert legacy.JarvisLive.run is original_run

    win = SimpleNamespace(_voice_capture_generation=0)
    ui = SimpleNamespace(_win=win, muted=False)
    live = legacy.JarvisLive(ui)

    async def exercise():
        task = asyncio.create_task(live._listen_audio())
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        return await live.out_queue.get()

    uplink = asyncio.run(exercise())
    meter = win._voice_input_frames.get(timeout=0)

    assert sd.opens == 1
    assert sd.closes == 1
    assert sd.max_active == 1
    assert sd.input_kwargs["device"] == 0
    assert uplink["data"] == b"\x01\x02\x03\x04"
    assert meter.pcm == b"\x01\x02\x03\x04"
    assert meter.generation == win._voice_capture_generation == 1
    assert sd.InputStream == original_input_stream


def test_frame_hub_is_bounded_and_drops_oldest():
    from jarvis.integrations.voice_input_owner import FrameHub, VoiceInputFrame

    hub = FrameHub(max_frames=2)
    hub.begin_generation(4)
    for stamp in (1.0, 2.0, 3.0):
        hub.publish(VoiceInputFrame(4, stamp, bytes([int(stamp)])))

    assert hub.qsize() == 2
    assert hub.get(timeout=0).captured_at == 2.0
    assert hub.get(timeout=0).captured_at == 3.0


def test_mic_meter_consumes_current_generation_without_opening_device(monkeypatch):
    from jarvis.integrations.voice_input_owner import FrameHub, VoiceInputFrame
    from jarvis.ui.mic_meter import MicMeterController

    class _ForbiddenSoundDevice:
        def InputStream(self, **_kwargs):
            raise AssertionError("meter must not open a physical stream")

    monkeypatch.setitem(sys.modules, "sounddevice", _ForbiddenSoundDevice())
    hub = FrameHub(max_frames=3)
    hub.begin_generation(2)
    pcm = array("h", [1000] * 1024).tobytes()
    hub.publish(VoiceInputFrame(1, 1.0, pcm))
    hub.publish(VoiceInputFrame(2, 2.0, pcm))
    stop = threading.Event()
    levels = []

    class _LevelSignal:
        def emit(self, level):
            levels.append(level)
            stop.set()

    win = SimpleNamespace(
        _voice_input_frames=hub,
        _voice_capture_generation=2,
        _legacy_state="LISTENING",
        _muted=False,
        _speaking_since=0.0,
        _mic_level_sig=_LevelSignal(),
        _voice_interrupt_sig=SimpleNamespace(emit=lambda _event: None),
        orb=SimpleNamespace(
            feed_amplitude=lambda _level: (_ for _ in ()).throw(
                AssertionError("meter worker must not mutate the orb directly")
            )
        ),
        write_log=lambda _text: None,
    )

    MicMeterController(win, stop).run()

    assert len(levels) == 1
    assert levels[0] > 0


def test_old_generation_interrupt_is_rejected_after_stream_reopen(monkeypatch):
    from jarvis.integrations import voice_interrupt, voice_playback_level

    monkeypatch.setattr(voice_interrupt.time, "monotonic", lambda: 10.0)
    voice_playback_level.reset()
    voice_playback_level.mark_installed()
    voice_playback_level.mark_started(epoch=7, now=9.0)
    old_win = SimpleNamespace(_voice_capture_generation=1)
    verdict = SimpleNamespace(rms=0.2, threshold=0.1, noise_floor=0.01)
    event, reason = voice_interrupt.build_microphone_event(
        old_win, verdict, detected_at=10.0
    )
    assert reason == "voice_interrupt_candidate"

    reopened_win = SimpleNamespace(_voice_capture_generation=2)
    assert voice_interrupt.validate_event(
        reopened_win, event, now=10.1
    ) == "voice_interrupt_capture_stale"
    voice_playback_level.reset()
    voice_playback_level.mark_uninstalled()
