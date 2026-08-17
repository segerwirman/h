from __future__ import annotations

import sys
import types


class _InputStream:
    def __init__(self, **kwargs):
        self.kwargs = kwargs

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False


class _SoundDevice:
    def __init__(self):
        self.input_kwargs = None

    def query_devices(self, device=None, kind=None):
        devices = [
            {"name": "unused", "max_input_channels": 0,
             "max_output_channels": 2, "hostapi": 0},
            {"name": "physical mic", "max_input_channels": 2,
             "max_output_channels": 0, "hostapi": 0},
            {"name": "physical speaker", "max_input_channels": 0,
             "max_output_channels": 2, "hostapi": 0},
        ]
        if device is not None:
            return devices[device]
        if kind == "input":
            return {"name": "virtual default input"}
        if kind == "output":
            return {"name": "virtual default output"}
        return devices

    def query_hostapis(self, index):
        return {"name": "MME" if index == 0 else "Windows WASAPI"}

    def check_input_settings(self, **_kwargs):
        return None

    def check_output_settings(self, **_kwargs):
        return None

    def InputStream(self, **kwargs):
        self.input_kwargs = kwargs
        return _InputStream(**kwargs)


def test_install_binds_configured_input_and_output_devices(monkeypatch):
    from jarvis.core import config
    from jarvis.integrations import voice_audio_devices

    sd = _SoundDevice()

    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: {
            "voice.audio.input_device": 1,
            "voice.audio.output_device": 2,
        }.get(key, default),
    )

    class Live:
        async def _listen_audio(self):
            with self.sd.InputStream(samplerate=16000):
                return None

    legacy = types.SimpleNamespace(JarvisLive=Live, sd=sd)

    original_input_stream = sd.InputStream

    assert voice_audio_devices.install(legacy) is True
    assert legacy._jarvis_voice_input_device == 1
    assert legacy._jarvis_voice_output_device == 2
    assert sd.InputStream == original_input_stream
    assert sd.input_kwargs is None


def test_host_qualified_selector_survives_duplicate_device_names(monkeypatch):
    from jarvis.core import config
    from jarvis.integrations import voice_audio_devices

    sd = _SoundDevice()
    sd.query_devices = lambda: [
        {"name": "USB Mic", "max_input_channels": 1,
         "max_output_channels": 0, "hostapi": 0},
        {"name": "USB Mic", "max_input_channels": 1,
         "max_output_channels": 0, "hostapi": 1},
        {"name": "Monitor", "max_input_channels": 0,
         "max_output_channels": 2, "hostapi": 0},
        {"name": "Monitor", "max_input_channels": 0,
         "max_output_channels": 2, "hostapi": 1},
    ]
    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: {
            "voice.audio.input_device": "MME::USB Mic",
            "voice.audio.output_device": "MME::Monitor",
        }.get(key, default),
    )

    class Live:
        async def _listen_audio(self):
            return None

    legacy = types.SimpleNamespace(JarvisLive=Live, sd=sd)

    assert voice_audio_devices.install(legacy) is True
    assert legacy._jarvis_voice_input_device == 0
    assert legacy._jarvis_voice_output_device == 2


def test_boot_audio_status_reports_configured_live_devices(monkeypatch):
    from jarvis.core import boot, config

    sd = _SoundDevice()
    monkeypatch.setitem(sys.modules, "sounddevice", sd)
    monkeypatch.setattr(
        config,
        "get",
        lambda key, default=None: {
            "voice.audio.input_device": "MME::physical mic",
            "voice.audio.output_device": "MME::physical speaker",
        }.get(key, default),
    )

    stt = boot._check_stt()
    tts = boot._check_tts()

    assert stt.ok is True
    assert stt.detail == "physical mic"
    assert tts.ok is True
    assert tts.detail == "physical speaker"
