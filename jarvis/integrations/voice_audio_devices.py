"""Explicit input/output device selection for the legacy Gemini Live seam."""

from __future__ import annotations

from jarvis.core import config, log

_logger = log.get("voice.audio_devices")


def _coerce(value, key: str):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        raise TypeError(f"{key} must be a device index or name")
    if isinstance(value, int):
        return value
    text = str(value).strip()
    return int(text) if text.isdigit() else text


def _resolve(sd, value, direction: str):
    if value is None:
        return None
    devices = list(sd.query_devices())
    if isinstance(value, int):
        if value < 0 or value >= len(devices):
            raise ValueError(f"{direction} device index {value} tidak ditemukan")
        info = devices[value]
        channels = info.get(
            "max_input_channels" if direction == "input" else "max_output_channels",
            0,
        )
        if int(channels or 0) <= 0:
            raise ValueError(f"device {value} bukan perangkat {direction}")
        return value

    host_name = None
    device_name = value
    if "::" in value:
        host_name, device_name = (part.strip() for part in value.split("::", 1))
        if not host_name or not device_name:
            raise ValueError(f"selector perangkat {direction} tidak valid")

    matches = []
    for index, info in enumerate(devices):
        channels = int(info.get(
            "max_input_channels" if direction == "input"
            else "max_output_channels", 0
        ) or 0)
        if channels <= 0:
            continue
        if str(info.get("name", "")).strip().casefold() != device_name.casefold():
            continue
        if host_name is not None:
            host_index = info.get("hostapi")
            actual_host = str(sd.query_hostapis(host_index).get("name", "")).strip()
            if actual_host.casefold() != host_name.casefold():
                continue
        matches.append(index)
    if len(matches) != 1:
        raise ValueError(
            f"{direction} device name tidak unik atau tidak ditemukan")
    return matches[0]


def resolve_configured_device(sd, direction: str):
    """Return the configured PortAudio index and its device metadata."""
    if direction not in {"input", "output"}:
        raise ValueError(f"arah perangkat tidak valid: {direction}")
    if direction == "input":
        key = "voice.audio.input_device"
        raw_value = config.get("voice.audio.input_device", None)
    else:
        key = "voice.audio.output_device"
        raw_value = config.get("voice.audio.output_device", None)
    value = _coerce(raw_value, key)
    device = _resolve(sd, value, direction)
    if device is None:
        return None, sd.query_devices(kind=direction)
    return device, list(sd.query_devices())[device]


def install(legacy_module) -> bool:
    """Validate configured devices without mutating global stream factories."""
    try:
        cls = legacy_module.JarvisLive
        sd = legacy_module.sd
        input_device, _input_info = resolve_configured_device(sd, "input")
        output_device, _output_info = resolve_configured_device(sd, "output")
        if input_device is not None:
            sd.check_input_settings(
                device=input_device,
                samplerate=int(getattr(legacy_module, "SEND_SAMPLE_RATE", 16000)),
                channels=1,
                dtype="int16",
            )
        if output_device is not None:
            sd.check_output_settings(
                device=output_device,
                samplerate=int(getattr(legacy_module, "RECEIVE_SAMPLE_RATE", 24000)),
                channels=1,
                dtype="int16",
            )
    except Exception as exc:                                # noqa: BLE001
        _logger.error("voice.audio_devices.invalid", error=str(exc)[:120])
        return False

    legacy_module._jarvis_voice_input_device = input_device
    legacy_module._jarvis_voice_output_device = output_device
    cls._jarvis_voice_audio_devices = True
    _logger.info(
        "voice.audio_devices.configured",
        input_device=input_device,
        output_device=output_device,
    )
    return True
