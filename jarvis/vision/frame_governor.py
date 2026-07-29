"""FrameGovernor — bounded latest-frame pacing (redesign §17).

"Remove the FPS limit on GPU" means: no artificial sleep-based inference
throttle when a GPU backend is active — but NOT an unbounded queue. This
governor enforces exactly that policy:

  * GPU active  → no inference sleep; keep at most ``max_inflight`` frames;
    always process the LATEST frame and drop stale ones (never grow memory).
  * CPU active  → honor ``cpu_fps_limit`` with a sleep so responsiveness and
    power draw stay bounded.

Capture, inference, and render FPS are separate concerns; this only paces
inference. Pure timing math with an injected clock, so it is deterministic
in tests (no real sleeping, no wall-clock flakiness).
"""
from __future__ import annotations

from collections import deque

from jarvis.core import config


class FrameGovernor:
    def __init__(self, gpu_active: bool, clock=None):
        y = config.section("vision.yolo")
        self.gpu_active = gpu_active
        self._clock = clock or __import__("time").monotonic
        self._max_inflight = max(1, int(y.get("max_inflight_frames", 1)))
        self._queue_policy = str(y.get("queue_policy", "latest_frame"))
        cpu_limit = y.get("cpu_fps_limit", 15)
        gpu_limit = y.get("gpu_fps_limit", None)
        # GPU: no artificial cap unless the user explicitly set a gpu_fps_limit
        self._min_dt = 0.0
        if gpu_active:
            self._min_dt = (1.0 / float(gpu_limit)) if gpu_limit else 0.0
        else:
            self._min_dt = (1.0 / float(cpu_limit)) if cpu_limit else 0.0
        self._buffer: deque = deque(maxlen=self._max_inflight)
        self._last_infer_t = -1e9
        self.dropped = 0

    def submit(self, frame) -> None:
        """Enqueue a captured frame. Bounded: once the buffer is full the
        OLDEST frame is dropped so only the freshest ``max_inflight`` frames
        survive — this is the backpressure that keeps memory flat."""
        if len(self._buffer) == self._buffer.maxlen:
            self.dropped += 1          # deque drops the oldest on append
        self._buffer.append(frame)

    def next_frame(self):
        """Return the frame to run inference on now, or None if the pacing
        window hasn't elapsed (CPU/limited GPU) or nothing is queued. Under
        latest_frame policy this returns the newest frame and discards any
        older queued frames as stale."""
        if not self._buffer:
            return None
        now = self._clock()
        if self._min_dt > 0.0 and (now - self._last_infer_t) < self._min_dt:
            return None
        self._last_infer_t = now
        if self._queue_policy == "latest_frame":
            frame = self._buffer[-1]
            stale = len(self._buffer) - 1
            if stale > 0:
                self.dropped += stale
            self._buffer.clear()
            return frame
        return self._buffer.popleft()

    @property
    def has_inference_cap(self) -> bool:
        """True when a sleep-based inference cap is in effect (CPU, or a GPU
        limit the user explicitly opted into)."""
        return self._min_dt > 0.0

    @property
    def queue_depth(self) -> int:
        return len(self._buffer)

    @property
    def max_inflight(self) -> int:
        return self._max_inflight
