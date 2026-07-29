"""ClapAnalyzer unit tests — synthetic int16 blocks, no microphone needed."""
import numpy as np
import pytest

from jarvis.core.wake import ClapAnalyzer, ClapConfig

RATE = 16000
CHUNK = 1024


def cfg(**kw) -> ClapConfig:
    base = dict(enabled=True, input_device=None, sample_rate=RATE, chunk=CHUNK,
                threshold_multiplier=6.0, min_abs_peak=0.12, crest_factor=3.5,
                max_active_fraction=0.12, spectral_ratio=0.35,
                min_interval_ms=120, max_interval_ms=900,
                cooldown_ms=2500, calibration_s=0.0, noise_alpha=0.05)
    base.update(kw)
    return ClapConfig(**base)


def silence(level=0.005) -> np.ndarray:
    rng = np.random.default_rng(42)
    return (rng.normal(0, level, CHUNK) * 32768).astype(np.int16)


def clap_block(amplitude=0.8) -> np.ndarray:
    """Short broadband transient: ~4 ms burst of white noise in a quiet block."""
    rng = np.random.default_rng(7)
    x = np.zeros(CHUNK, dtype=np.float32)
    burst = int(0.004 * RATE)
    x[100:100 + burst] = rng.uniform(-1, 1, burst) * amplitude
    return (x * 32767).astype(np.int16)


def speech_block(amplitude=0.4) -> np.ndarray:
    """Sustained low-frequency tone ≈ voice — full-block energy, low crest."""
    t = np.arange(CHUNK) / RATE
    x = amplitude * np.sin(2 * np.pi * 180 * t)
    return (x * 32767).astype(np.int16)


def make_analyzer(**kw) -> ClapAnalyzer:
    a = ClapAnalyzer(cfg(**kw))
    a.noise_floor = 0.005
    return a


def feed(a, block, t):
    return a.process_block(block, t)


def test_two_valid_claps_trigger():
    a = make_analyzer()
    assert feed(a, clap_block(), 1.0).event == "clap"
    assert feed(a, silence(), 1.2).event == ""
    assert feed(a, clap_block(), 1.4).event == "double_clap"


def test_single_clap_no_trigger():
    a = make_analyzer()
    assert feed(a, clap_block(), 1.0).event == "clap"
    for i in range(20):
        v = feed(a, silence(), 1.1 + i * 0.064)
        assert v.event == ""


def test_claps_too_close_debounced():
    a = make_analyzer()
    assert feed(a, clap_block(), 1.0).event == "clap"
    v = feed(a, clap_block(), 1.05)          # 50 ms < min_interval 120 ms
    assert v.event == ""
    assert "too_soon" in v.reason


def test_claps_too_far_apart():
    a = make_analyzer()
    assert feed(a, clap_block(), 1.0).event == "clap"
    v = feed(a, clap_block(), 2.5)           # 1500 ms > max_interval 900 ms
    assert v.event == "clap"                 # counts as a NEW first clap
    assert feed(a, clap_block(), 2.8).event == "double_clap"


def test_continuous_noise_no_trigger():
    a = make_analyzer()
    rng = np.random.default_rng(3)
    for i in range(50):
        block = (rng.normal(0, 0.2, CHUNK) * 32768).clip(-32768, 32767).astype(np.int16)
        v = feed(a, block, 1.0 + i * 0.064)
        assert v.event != "double_clap"


def test_speech_rejected_low_crest():
    a = make_analyzer()
    for i in range(30):
        v = feed(a, speech_block(), 1.0 + i * 0.064)
        assert v.event == ""


def test_cooldown_blocks_immediate_retrigger():
    a = make_analyzer()
    feed(a, clap_block(), 1.0)
    assert feed(a, clap_block(), 1.4).event == "double_clap"
    # within 2.5 s cooldown → rejected
    v = feed(a, clap_block(), 2.0)
    assert v.event == ""
    assert v.reason == "cooldown"
    # after cooldown → detection works again
    assert feed(a, clap_block(), 4.5).event == "clap"
    assert feed(a, clap_block(), 4.9).event == "double_clap"


def test_suppressed_while_tts_speaking():
    a = make_analyzer()
    a.suppressed = True
    v = feed(a, clap_block(), 1.0)
    assert v.event == ""
    assert v.reason == "suppressed_tts"
    a.suppressed = False
    assert feed(a, clap_block(), 5.0).event == "clap"


def test_adaptive_noise_floor_rises_with_ambient():
    a = make_analyzer()
    start = a.noise_floor
    loud_ambient = (np.random.default_rng(1).normal(0, 0.05, CHUNK) * 32768
                    ).astype(np.int16)
    for i in range(100):
        feed(a, loud_ambient, 1.0 + i * 0.064)
    assert a.noise_floor > start * 3


def test_calibration_sets_floor():
    a = ClapAnalyzer(cfg(calibration_s=0.5))
    a.start_calibration(0.0)
    for i in range(5):
        v = feed(a, silence(0.01), i * 0.064)
        assert v.reason == "calibrating"
    feed(a, silence(0.01), 0.6)              # past window → floor set
    assert a.noise_floor >= 0.002


def test_empty_block_safe():
    a = make_analyzer()
    v = a.process_block(np.array([], dtype=np.int16), 1.0)
    assert v.event == ""


def test_trigger_when_session_active_is_ignored(monkeypatch):
    """WakeTrigger._fire respects session_active_fn (idempotent session start)."""
    from jarvis.core.wake import WakeTrigger
    from jarvis.core.bus import BUS
    fired = []
    BUS.subscribe("wake.triggered", lambda d: fired.append(1))
    t = WakeTrigger(cfg(), session_active_fn=lambda: True)
    t._fire()
    assert fired == []
    t2 = WakeTrigger(cfg(), session_active_fn=lambda: False)
    t2._fire()
    assert fired == [1]
    # immediate second fire deduped by cooldown
    t2._fire()
    assert fired == [1]
