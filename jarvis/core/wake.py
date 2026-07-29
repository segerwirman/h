"""Wake Trigger (Modul 10) — reliable double-clap detection.

Architecture (Mark L hardening):
    PyAudio callback (light: bytes → bounded queue)
        → analyzer thread (ClapAnalyzer: pure DSP, no hardware)
        → BUS.publish("wake.triggered") exactly once per double clap.

ClapAnalyzer is a pure function of sample blocks + timestamps, so unit tests
run against synthetic numpy arrays without a microphone.

Detection heuristics (a clap must satisfy ALL):
  * peak amplitude above max(adaptive noise floor × multiplier, absolute min)
  * high crest factor (short transient, not sustained speech/music)
  * broadband spectrum (high-frequency energy vs low-frequency thud)
Double clap: two claps separated by [min_interval, max_interval]; a trigger
starts a cooldown; while suppressed (JARVIS speaking) events are rejected.

Configuration: ``wake:`` section in config.yaml, overridden by env vars
CLAP_ENABLED, CLAP_INPUT_DEVICE, CLAP_SAMPLE_RATE, CLAP_THRESHOLD_MULTIPLIER,
CLAP_MIN_INTERVAL_MS, CLAP_MAX_INTERVAL_MS, CLAP_COOLDOWN_MS,
CLAP_CALIBRATION_SECONDS.

Diagnostics: ``python -m jarvis.core.wake`` prints live levels, the noise
floor, and the accept/reject reason for every candidate event.
"""
from __future__ import annotations

import os
import queue
import random
import threading
import time
from dataclasses import dataclass, field

from jarvis.core import config as _cfg
from jarvis.core import log
from jarvis.core.bus import BUS

_logger = log.get("wake")


def _env(name: str, default, cast):
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    try:
        if cast is bool:
            return raw.strip().lower() in ("1", "true", "yes", "on")
        return cast(raw)
    except (TypeError, ValueError):
        _logger.warning("wake.bad_env", var=name, value=raw[:40])
        return default


@dataclass
class ClapConfig:
    enabled: bool = True
    input_device: int | None = None      # None → system default
    sample_rate: int = 16000
    chunk: int = 1024
    threshold_multiplier: float = 6.0    # peak ≥ noise_floor × this
    min_abs_peak: float = 0.12           # absolute floor (0..1) in silence
    crest_factor: float = 3.5            # block peak / block rms (transient)
    max_active_fraction: float = 0.12    # samples above 0.3×peak; claps are brief
    spectral_ratio: float = 0.35         # high-band energy ≥ low-band × this
    min_interval_ms: int = 120           # two claps closer = one clap (debounce)
    max_interval_ms: int = 900           # two claps farther = unrelated
    cooldown_ms: int = 2500              # after a successful trigger
    calibration_s: float = 1.5           # startup ambient-noise sampling
    noise_alpha: float = 0.05            # EMA weight for adaptive noise floor

    @classmethod
    def load(cls) -> "ClapConfig":
        w = _cfg.section("wake")
        c = cls(
            enabled=bool(w.get("enabled", True)),
            input_device=w.get("input_device"),
            sample_rate=int(w.get("sample_rate", 16000)),
            chunk=int(w.get("chunk", 1024)),
            threshold_multiplier=float(w.get("threshold_multiplier", 6.0)),
            min_abs_peak=float(w.get("min_abs_peak", 0.12)),
            crest_factor=float(w.get("crest_factor", 3.5)),
            max_active_fraction=float(w.get("max_active_fraction", 0.12)),
            spectral_ratio=float(w.get("spectral_ratio", 0.35)),
            min_interval_ms=int(w.get("min_interval_ms", 120)),
            max_interval_ms=int(w.get("max_interval_ms", 900)),
            cooldown_ms=int(w.get("cooldown_ms", 2500)),
            calibration_s=float(w.get("calibration_seconds", 1.5)),
            noise_alpha=float(w.get("noise_alpha", 0.05)),
        )
        c.enabled = _env("CLAP_ENABLED", c.enabled, bool)
        dev = _env("CLAP_INPUT_DEVICE", c.input_device, int)
        c.input_device = dev
        c.sample_rate = _env("CLAP_SAMPLE_RATE", c.sample_rate, int)
        c.threshold_multiplier = _env("CLAP_THRESHOLD_MULTIPLIER",
                                      c.threshold_multiplier, float)
        c.min_interval_ms = _env("CLAP_MIN_INTERVAL_MS", c.min_interval_ms, int)
        c.max_interval_ms = _env("CLAP_MAX_INTERVAL_MS", c.max_interval_ms, int)
        c.cooldown_ms = _env("CLAP_COOLDOWN_MS", c.cooldown_ms, int)
        c.calibration_s = _env("CLAP_CALIBRATION_SECONDS", c.calibration_s, float)
        return c


@dataclass
class BlockVerdict:
    """Diagnostic record for one analyzed block."""
    rms: float
    peak: float
    noise_floor: float
    event: str            # "" | "clap" | "double_clap"
    reason: str           # why accepted/rejected


@dataclass
class ClapAnalyzer:
    """Pure double-clap detector. Feed int16 sample blocks + timestamps."""
    cfg: ClapConfig
    noise_floor: float = 0.0
    _calibrating_until: float | None = None
    _calib_samples: list = field(default_factory=list)
    _claps: list = field(default_factory=list)
    _last_clap_t: float = -1e9
    _cooldown_until: float = 0.0
    suppressed: bool = False              # True while JARVIS speaks (echo guard)

    def start_calibration(self, now: float) -> None:
        self._calibrating_until = now + self.cfg.calibration_s
        self._calib_samples = []

    # ── main entry ───────────────────────────────────────────────────────────
    def process_block(self, samples, now: float) -> BlockVerdict:
        import numpy as np
        x = np.asarray(samples, dtype=np.float32) / 32768.0
        if x.size == 0:
            return BlockVerdict(0, 0, self.noise_floor, "", "empty")
        rms = float(np.sqrt(np.mean(np.square(x))))
        peak = float(np.max(np.abs(x)))

        # startup calibration window: only collect ambient level
        if self._calibrating_until is not None:
            if now < self._calibrating_until:
                self._calib_samples.append(rms)
                return BlockVerdict(rms, peak, self.noise_floor, "", "calibrating")
            base = (sorted(self._calib_samples)[len(self._calib_samples) // 2]
                    if self._calib_samples else 0.005)
            self.noise_floor = max(base, 0.002)
            self._calibrating_until = None
            _logger.info("wake.calibrated", noise_floor=round(self.noise_floor, 4))

        threshold = max(self.noise_floor * self.cfg.threshold_multiplier,
                        self.cfg.min_abs_peak)

        if peak < threshold:
            self._learn(rms)
            self._expire_claps(now)
            return BlockVerdict(rms, peak, self.noise_floor, "", "below_threshold")

        if self.suppressed:
            return BlockVerdict(rms, peak, self.noise_floor, "", "suppressed_tts")
        if now < self._cooldown_until:
            return BlockVerdict(rms, peak, self.noise_floor, "", "cooldown")

        crest = peak / (rms + 1e-6)
        if crest < self.cfg.crest_factor:
            self._learn(rms)                 # sustained loud sound = ambient
            return BlockVerdict(rms, peak, self.noise_floor, "",
                                f"low_crest {crest:.1f}")

        # transient duration: a clap occupies only a small slice of the block;
        # continuous noise/music keeps many samples near the peak
        active = float(np.mean(np.abs(x) > 0.3 * peak))
        if active > self.cfg.max_active_fraction:
            self._learn(rms)
            return BlockVerdict(rms, peak, self.noise_floor, "",
                                f"sustained {active:.2f}")

        # spectral: claps are broadband; voice/thuds concentrate < ~300 Hz
        mag = np.abs(np.fft.rfft(x))
        cut = max(1, int(300 * x.size / self.cfg.sample_rate))
        low = float(np.sum(mag[:cut])) + 1e-6
        high = float(np.sum(mag[cut:]))
        if high < low * self.cfg.spectral_ratio:
            self._learn(rms)
            return BlockVerdict(rms, peak, self.noise_floor, "",
                                f"low_band {high / low:.2f}")

        # temporal logic
        dt_ms = (now - self._last_clap_t) * 1000.0
        if dt_ms < self.cfg.min_interval_ms:
            return BlockVerdict(rms, peak, self.noise_floor, "",
                                f"too_soon {dt_ms:.0f}ms")

        self._expire_claps(now)
        self._last_clap_t = now
        if self._claps and dt_ms <= self.cfg.max_interval_ms:
            self._claps.clear()
            self._cooldown_until = now + self.cfg.cooldown_ms / 1000.0
            return BlockVerdict(rms, peak, self.noise_floor, "double_clap",
                                f"pair {dt_ms:.0f}ms")
        self._claps = [now]
        return BlockVerdict(rms, peak, self.noise_floor, "clap", "first_clap")

    def _learn(self, rms: float) -> None:
        a = self.cfg.noise_alpha
        self.noise_floor = (1 - a) * self.noise_floor + a * max(rms, 1e-4)

    def _expire_claps(self, now: float) -> None:
        limit = self.cfg.max_interval_ms / 1000.0
        self._claps = [t for t in self._claps if now - t <= limit]


class WakeTrigger:
    """Owns the PyAudio stream + analyzer thread; restarts on failure.

    ``session_active_fn`` (optional) makes triggering idempotent: when it
    returns True the double clap is logged but not re-published, so an active
    session is never started twice.
    """

    def __init__(self, cfg: ClapConfig | None = None,
                 session_active_fn=None, diagnostics: bool = False):
        self.cfg = cfg or ClapConfig.load()
        self.analyzer = ClapAnalyzer(self.cfg)
        self._session_active_fn = session_active_fn
        self._diag = diagnostics or bool(_cfg.get("wake.diagnostics", False))
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._q: "queue.Queue[bytes]" = queue.Queue(maxsize=64)
        self._last_trigger = 0.0
        # echo guard: suppress detection while JARVIS itself is speaking
        BUS.subscribe("state", self._on_state)

    # ── lifecycle ────────────────────────────────────────────────────────────
    def start(self) -> None:
        if not self.cfg.enabled:
            _logger.info("wake.disabled_by_config")
            return
        if self._threads:
            return
        self._stop.clear()
        t1 = threading.Thread(target=self._capture_loop, daemon=True,
                              name="wake-capture")
        t2 = threading.Thread(target=self._analyze_loop, daemon=True,
                              name="wake-analyze")
        self._threads = [t1, t2]
        t1.start()
        t2.start()
        _logger.info("wake.started",
                     threshold_multiplier=self.cfg.threshold_multiplier,
                     cooldown_ms=self.cfg.cooldown_ms)

    def stop(self) -> None:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=2.0)
        self._threads = []
        _logger.info("wake.stopped")

    def _on_state(self, data: dict) -> None:
        state = str(data.get("state", "")).upper()
        self.analyzer.suppressed = state == "SPEAKING"

    # ── capture: light callback + supervised reopen with backoff ────────────
    def _capture_loop(self) -> None:
        try:
            import pyaudio
        except ImportError:
            _logger.warning("wake.disabled", detail="pyaudio not installed")
            BUS.publish("notify", title="Wake",
                        body="Deteksi tepuk nonaktif: pyaudio tidak terpasang.")
            return

        attempt = 0
        max_attempts = 5
        while not self._stop.is_set():
            pa = stream = None
            try:
                pa = pyaudio.PyAudio()
                kwargs = dict(format=pyaudio.paInt16, channels=1,
                              rate=self.cfg.sample_rate, input=True,
                              frames_per_buffer=self.cfg.chunk)
                if self.cfg.input_device is not None:
                    kwargs["input_device_index"] = int(self.cfg.input_device)
                stream = pa.open(**kwargs)
                attempt = 0
                _logger.info("wake.stream_open", rate=self.cfg.sample_rate,
                             device=self.cfg.input_device)
                while not self._stop.is_set():
                    data = stream.read(self.cfg.chunk,
                                       exception_on_overflow=False)
                    try:
                        self._q.put_nowait(data)
                    except queue.Full:
                        try:                       # drop oldest, keep newest
                            self._q.get_nowait()
                            self._q.put_nowait(data)
                        except queue.Empty:
                            pass
            except Exception as e:
                attempt += 1
                _logger.error("wake.stream_error", error=str(e)[:120],
                              attempt=attempt)
                if attempt >= max_attempts:
                    _logger.error("wake.gave_up", attempts=attempt)
                    BUS.publish("notify", title="Wake",
                                body="Mikrofon untuk deteksi tepuk tidak "
                                     "tersedia — fitur dinonaktifkan.")
                    return
                delay = min(2 ** attempt, 30) + random.uniform(0, 1)
                if self._stop.wait(delay):
                    return
            finally:
                try:
                    if stream is not None:
                        stream.stop_stream()
                        stream.close()
                    if pa is not None:
                        pa.terminate()
                except Exception:
                    pass

    # ── analysis thread ─────────────────────────────────────────────────────
    def _analyze_loop(self) -> None:
        try:
            import numpy as np
        except ImportError:
            _logger.warning("wake.disabled", detail="numpy not installed")
            return
        self.analyzer.start_calibration(time.monotonic())
        while not self._stop.is_set():
            try:
                data = self._q.get(timeout=0.5)
            except queue.Empty:
                continue
            samples = np.frombuffer(data, dtype=np.int16)
            v = self.analyzer.process_block(samples, time.monotonic())
            if self._diag and (v.event or v.reason not in
                               ("below_threshold", "calibrating")):
                _logger.info("wake.diag", rms=round(v.rms, 3),
                             peak=round(v.peak, 3),
                             floor=round(v.noise_floor, 4),
                             event=v.event or "-", reason=v.reason)
            if v.event == "double_clap":
                self._fire()

    def _fire(self) -> None:
        now = time.monotonic()
        if (now - self._last_trigger) * 1000.0 < self.cfg.cooldown_ms:
            _logger.info("wake.trigger_deduped")
            return
        self._last_trigger = now
        if self._session_active_fn is not None:
            try:
                if self._session_active_fn():
                    _logger.info("wake.ignored_session_active")
                    return
            except Exception:
                pass
        _logger.info("wake.double_clap_detected")
        BUS.publish("wake.triggered")


# ── diagnostics CLI: python -m jarvis.core.wake ──────────────────────────────
def _diagnose() -> int:
    print("Wake diagnostics — Ctrl+C untuk berhenti.")
    cfg = ClapConfig.load()
    print(f"config: {cfg}")
    trigger = WakeTrigger(cfg, diagnostics=True)

    def on_trig(_):
        print(">>> WAKE TRIGGERED (double clap) <<<")

    BUS.subscribe("wake.triggered", on_trig)
    trigger.start()
    try:
        while True:
            time.sleep(0.5)
    except KeyboardInterrupt:
        trigger.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(_diagnose())
