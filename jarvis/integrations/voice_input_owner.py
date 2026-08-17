"""Single physical PC microphone owner for the legacy Gemini Live seam."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import queue
import threading
import time

from jarvis.core import log
from jarvis.integrations import voice_audio_devices

_logger = log.get("voice.input_owner")
_PATCH_MARKER = "_jarvis_voice_input_owner"
_PCM_MIME = "audio/pcm;rate=16000"
_DEFAULT_FRAME_CAPACITY = 32


@dataclass(frozen=True)
class VoiceInputFrame:
    generation: int
    captured_at: float
    pcm: bytes


class FrameHub:
    """Bounded, thread-safe handoff from PortAudio to mic analysis."""

    def __init__(self, max_frames: int = _DEFAULT_FRAME_CAPACITY):
        self._frames = queue.Queue(maxsize=max(1, int(max_frames)))
        self._lock = threading.Lock()
        self._generation = 0

    @property
    def generation(self) -> int:
        with self._lock:
            return self._generation

    def begin_generation(self, generation: int) -> None:
        with self._lock:
            self._generation = int(generation)
            while True:
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    break

    def publish(self, frame: VoiceInputFrame) -> bool:
        with self._lock:
            if frame.generation != self._generation:
                return False
            try:
                self._frames.put_nowait(frame)
            except queue.Full:
                try:
                    self._frames.get_nowait()
                except queue.Empty:
                    pass
                try:
                    self._frames.put_nowait(frame)
                except queue.Full:
                    return False
            return True

    def get(self, timeout: float | None = None) -> VoiceInputFrame:
        return self._frames.get(timeout=timeout)

    def qsize(self) -> int:
        return self._frames.qsize()


def frame_hub(window) -> FrameHub:
    hub = getattr(window, "_voice_input_frames", None)
    if not isinstance(hub, FrameHub):
        hub = FrameHub()
        window._voice_input_frames = hub
    return hub


def _window(ui):
    return getattr(ui, "_win", ui)


def install(legacy_module) -> bool:
    """Replace only the frozen listener; its run/reconnect owner stays intact."""
    live_cls = legacy_module.JarvisLive
    if getattr(live_cls, _PATCH_MARKER, False):
        return False

    sd = legacy_module.sd
    samplerate = int(getattr(legacy_module, "SEND_SAMPLE_RATE", 16000))
    channels = int(getattr(legacy_module, "CHANNELS", 1))
    blocksize = int(getattr(legacy_module, "CHUNK_SIZE", 1024))

    async def listen_audio(self) -> None:
        loop = asyncio.get_running_loop()
        window = _window(self.ui)
        hub = frame_hub(window)
        generation = int(
            getattr(window, "_voice_capture_generation", 0) or 0
        ) + 1
        window._voice_capture_generation = generation
        hub.begin_generation(generation)

        input_device, _input_info = voice_audio_devices.resolve_configured_device(
            sd, "input"
        )
        if input_device is not None:
            sd.check_input_settings(
                device=input_device,
                samplerate=samplerate,
                channels=channels,
                dtype="int16",
            )

        def generation_is_current() -> bool:
            return (
                int(getattr(window, "_voice_capture_generation", 0) or 0)
                == generation
                and hub.generation == generation
            )

        def safe_put(message) -> None:
            if not generation_is_current():
                return
            try:
                self.out_queue.put_nowait(message)
            except asyncio.QueueFull:
                try:
                    self.out_queue.get_nowait()
                    self.out_queue.put_nowait(message)
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    return

        def callback(indata, _frames, _time_info, _status) -> None:
            if not generation_is_current():
                return
            captured_at = time.monotonic()
            pcm = bytes(indata.tobytes())
            hub.publish(VoiceInputFrame(generation, captured_at, pcm))
            with self._speaking_lock:
                jarvis_speaking = self._is_speaking
            if (
                not jarvis_speaking
                and not self.ui.muted
                and not self._phone_active
            ):
                loop.call_soon_threadsafe(
                    safe_put,
                    {"data": pcm, "mime_type": _PCM_MIME},
                )

        with sd.InputStream(
            device=input_device,
            samplerate=samplerate,
            channels=channels,
            dtype="int16",
            blocksize=blocksize,
            callback=callback,
        ):
            _logger.info(
                "voice.input_owner.started",
                generation=generation,
                input_device=input_device,
            )
            while True:
                await asyncio.sleep(0.1)

    live_cls._listen_audio = listen_audio
    setattr(live_cls, _PATCH_MARKER, True)
    _logger.info("voice.input_owner.installed")
    return True


__all__ = ["FrameHub", "VoiceInputFrame", "frame_hub", "install"]
