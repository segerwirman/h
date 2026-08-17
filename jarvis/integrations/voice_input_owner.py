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
class InputHeartbeatSnapshot:
    generation: int = 0
    stream_opened_at: float | None = None
    callback_at: float | None = None
    callback_count: int = 0
    callback_bytes: int = 0
    queued_at: float | None = None
    queued_count: int = 0
    queued_bytes: int = 0
    sent_at: float | None = None
    sent_count: int = 0
    sent_bytes: int = 0


class InputHeartbeat:
    """Thread-safe metadata for the three outbound microphone stages."""

    def __init__(self, *, clock=None):
        self._clock = clock or time.monotonic
        self._lock = threading.Lock()
        self._snapshot = InputHeartbeatSnapshot()

    def begin_generation(self, generation: int) -> None:
        with self._lock:
            self._snapshot = InputHeartbeatSnapshot(
                generation=int(generation),
                stream_opened_at=float(self._clock()),
            )

    def _mark(self, generation: int, stage: str, frame_bytes: int) -> bool:
        with self._lock:
            current = self._snapshot
            if int(generation) != current.generation:
                return False
            values = dict(current.__dict__)
            values[f"{stage}_at"] = float(self._clock())
            values[f"{stage}_count"] = int(values[f"{stage}_count"]) + 1
            values[f"{stage}_bytes"] = max(0, int(frame_bytes))
            self._snapshot = InputHeartbeatSnapshot(**values)
            return True

    def mark_callback(self, generation: int, *, frame_bytes: int) -> bool:
        return self._mark(generation, "callback", frame_bytes)

    def mark_queued(
        self,
        generation: int,
        *,
        frame_bytes: int,
        at: float | None = None,
    ) -> bool:
        del at  # Keberhasilan put dicatat saat benar-benar terjadi.
        return self._mark(generation, "queued", frame_bytes)

    def mark_sent(self, generation: int, *, frame_bytes: int) -> bool:
        return self._mark(generation, "sent", frame_bytes)

    def snapshot(self) -> InputHeartbeatSnapshot:
        with self._lock:
            return self._snapshot


class VoiceInputMessage(dict):
    """Normal Live payload carrying local-only capture generation metadata."""

    def __init__(self, generation: int, pcm: bytes):
        super().__init__(data=pcm, mime_type=_PCM_MIME)
        self.generation = int(generation)


def input_heartbeat(live) -> InputHeartbeat:
    heartbeat = getattr(live, "_voice_input_heartbeat", None)
    if not isinstance(heartbeat, InputHeartbeat):
        heartbeat = InputHeartbeat()
        live._voice_input_heartbeat = heartbeat
    return heartbeat


def heartbeat_snapshot(live) -> InputHeartbeatSnapshot:
    return input_heartbeat(live).snapshot()


def mark_sent(live, message) -> bool:
    if not isinstance(message, VoiceInputMessage):
        return False
    heartbeat = input_heartbeat(live)
    snapshot = heartbeat.snapshot()
    generation = int(getattr(message, "generation", snapshot.generation))
    data = message.get("data", b"") if isinstance(message, dict) else b""
    size = len(data) if isinstance(data, (bytes, bytearray, memoryview)) else 0
    return heartbeat.mark_sent(generation, frame_bytes=size)


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
        heartbeat = input_heartbeat(self)
        generation = int(
            getattr(window, "_voice_capture_generation", 0) or 0
        ) + 1
        window._voice_capture_generation = generation
        hub.begin_generation(generation)
        heartbeat.begin_generation(generation)

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

        def safe_put(message: VoiceInputMessage) -> None:
            if not generation_is_current():
                return
            queued = False
            try:
                self.out_queue.put_nowait(message)
                queued = True
            except asyncio.QueueFull:
                try:
                    self.out_queue.get_nowait()
                    self.out_queue.put_nowait(message)
                    queued = True
                except (asyncio.QueueEmpty, asyncio.QueueFull):
                    return
            if queued:
                heartbeat.mark_queued(
                    generation, frame_bytes=len(message["data"])
                )

        def callback(indata, _frames, _time_info, _status) -> None:
            if not generation_is_current():
                return
            captured_at = time.monotonic()
            pcm = bytes(indata.tobytes())
            heartbeat.mark_callback(generation, frame_bytes=len(pcm))
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
                    VoiceInputMessage(generation, pcm),
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


__all__ = [
    "FrameHub",
    "InputHeartbeat",
    "InputHeartbeatSnapshot",
    "VoiceInputFrame",
    "VoiceInputMessage",
    "frame_hub",
    "heartbeat_snapshot",
    "input_heartbeat",
    "install",
    "mark_sent",
]
