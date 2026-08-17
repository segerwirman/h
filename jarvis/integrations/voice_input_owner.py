"""Single physical PC microphone owner for the legacy Gemini Live seam."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import queue
import threading
import time

from jarvis.core import config, log
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


@dataclass(frozen=True)
class InputRecoveryPolicy:
    poll_s: float
    startup_grace_s: float
    stale_s: float
    max_attempts: int
    deadline_s: float
    stable_s: float

    @classmethod
    def from_config(cls) -> "InputRecoveryPolicy":
        return cls(
            poll_s=_coerce_float(
                config.get("voice.audio.heartbeat_poll_s", 0.1),
                0.1,
                0.01,
                5.0,
            ),
            startup_grace_s=_coerce_float(
                config.get("voice.audio.callback_startup_grace_s", 2.0),
                2.0,
                0.1,
                30.0,
            ),
            stale_s=_coerce_float(
                config.get("voice.audio.callback_stale_s", 1.0),
                1.0,
                0.1,
                30.0,
            ),
            max_attempts=_coerce_int(
                config.get("voice.audio.recovery_max_attempts", 3),
                3,
                0,
                20,
            ),
            deadline_s=_coerce_float(
                config.get("voice.audio.recovery_deadline_s", 120.0),
                120.0,
                1.0,
                3600.0,
            ),
            stable_s=_coerce_float(
                config.get("voice.audio.recovery_stable_s", 10.0),
                10.0,
                0.1,
                300.0,
            ),
        )


class InputFailure(RuntimeError):
    """Typed local failure consumed by the existing reconnect owner."""


class InputOpenFailure(InputFailure):
    pass


class InputCallbackStale(InputFailure):
    pass


class InputRecoveryExhausted(InputFailure):
    pass


class InputRecoveryBudget:
    def __init__(self):
        self.failures = 0
        self.failure_started_at: float | None = None
        self._healthy_since: float | None = None

    def register_failure(
        self, now: float, policy: InputRecoveryPolicy
    ) -> bool:
        now = float(now)
        if self.failure_started_at is None:
            self.failure_started_at = now
        self.failures += 1
        self._healthy_since = None
        return (
            self.failures > policy.max_attempts
            or now >= self.failure_started_at + policy.deadline_s
        )

    def observe_healthy(
        self,
        now: float,
        policy: InputRecoveryPolicy,
        *,
        callback_at: float | None = None,
    ) -> None:
        now = float(now)
        progress_at = now if callback_at is None else float(callback_at)
        if self._healthy_since is None:
            self._healthy_since = progress_at
            return
        if progress_at >= self._healthy_since + policy.stable_s:
            self.failures = 0
            self.failure_started_at = None
            self._healthy_since = progress_at

    def observe_unhealthy(self) -> None:
        self._healthy_since = None


def _coerce_float(
    raw, default: float, minimum: float, maximum: float
) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _coerce_int(raw, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def callback_failure(
    snapshot: InputHeartbeatSnapshot,
    now: float,
    policy: InputRecoveryPolicy,
) -> InputCallbackStale | None:
    if snapshot.stream_opened_at is None:
        return InputCallbackStale("voice input stream heartbeat unavailable")
    if snapshot.callback_at is None:
        if now >= snapshot.stream_opened_at + policy.startup_grace_s:
            return InputCallbackStale("voice input callback did not start")
        return None
    if now >= snapshot.callback_at + policy.stale_s:
        return InputCallbackStale("voice input callback became stale")
    return None


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


def input_recovery_budget(live) -> InputRecoveryBudget:
    budget = getattr(live, "_voice_input_recovery", None)
    if not isinstance(budget, InputRecoveryBudget):
        budget = InputRecoveryBudget()
        live._voice_input_recovery = budget
    return budget


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
        stop_requested = getattr(self, "_stop_requested", None)
        if stop_requested is not None and stop_requested.is_set():
            return
        loop = asyncio.get_running_loop()
        window = _window(self.ui)
        hub = frame_hub(window)
        heartbeat = input_heartbeat(self)
        policy = InputRecoveryPolicy.from_config()
        budget = input_recovery_budget(self)
        generation = int(
            getattr(window, "_voice_capture_generation", 0) or 0
        ) + 1
        window._voice_capture_generation = generation
        hub.begin_generation(generation)
        heartbeat.begin_generation(generation)

        try:
            input_device, _input_info = (
                voice_audio_devices.resolve_configured_device(sd, "input")
            )
            if input_device is not None:
                sd.check_input_settings(
                    device=input_device,
                    samplerate=samplerate,
                    channels=channels,
                    dtype="int16",
                )
        except Exception as exc:
            failure = InputOpenFailure("voice input device unavailable")
            if budget.register_failure(time.monotonic(), policy):
                self.request_stop()
                raise InputRecoveryExhausted(
                    "voice input recovery exhausted"
                ) from exc
            raise failure from exc

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

        stream_options = dict(
            device=input_device,
            samplerate=samplerate,
            channels=channels,
            dtype="int16",
            blocksize=blocksize,
            callback=callback,
        )
        try:
            with sd.InputStream(**stream_options):
                _logger.info(
                    "voice.input_owner.started",
                    generation=generation,
                    input_device=input_device,
                )
                while True:
                    if stop_requested is not None and stop_requested.is_set():
                        return
                    await asyncio.sleep(policy.poll_s)
                    now = time.monotonic()
                    snapshot = heartbeat.snapshot()
                    failure = callback_failure(snapshot, now, policy)
                    if failure is not None:
                        budget.observe_unhealthy()
                        if budget.register_failure(now, policy):
                            self.request_stop()
                            raise InputRecoveryExhausted(
                                "voice input recovery exhausted"
                            ) from failure
                        raise failure
                    if snapshot.callback_count:
                        budget.observe_healthy(
                            now, policy, callback_at=snapshot.callback_at
                        )
        except (InputCallbackStale, InputRecoveryExhausted):
            raise
        except Exception as exc:
            failure = InputOpenFailure("voice input stream unavailable")
            if budget.register_failure(time.monotonic(), policy):
                self.request_stop()
                raise InputRecoveryExhausted(
                    "voice input recovery exhausted"
                ) from exc
            raise failure from exc

    live_cls._listen_audio = listen_audio
    setattr(live_cls, _PATCH_MARKER, True)
    _logger.info("voice.input_owner.installed")
    return True


__all__ = [
    "FrameHub",
    "InputCallbackStale",
    "InputFailure",
    "InputHeartbeat",
    "InputHeartbeatSnapshot",
    "InputOpenFailure",
    "InputRecoveryBudget",
    "InputRecoveryExhausted",
    "InputRecoveryPolicy",
    "VoiceInputFrame",
    "VoiceInputMessage",
    "callback_failure",
    "frame_hub",
    "heartbeat_snapshot",
    "input_heartbeat",
    "input_recovery_budget",
    "install",
    "mark_sent",
]
