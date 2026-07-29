"""Camera canonical-coordinate fix, GPU device resolver, frame governor,
Tabbit installation resolver, and YouTube capability separation
(this-prompt §5, §13-§18, §20). All pure-Python / mock-driven — no camera,
no GPU, no Tabbit, no network.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.vision.camera_transform import CameraPolicy, CameraTransform, resolve_policy
from jarvis.vision.device_caps import DeviceCapabilities, DeviceCapabilityResolver
from jarvis.vision.frame_governor import FrameGovernor


# horizontal flip stand-in for tests: a frame is an (id, list-of-column-x)
def _flip(frame):
    width, cols = frame
    return (width, [width - x for x in cols])


# ── §13/§14 camera orientation ────────────────────────────────────────────

def test_optical_raw_needs_one_flip_to_reach_canonical():
    # driver delivers a true optical frame: user's physical-right (x=90 in a
    # 100-wide frame from the user's view) lands on the raw LEFT (x=10)
    policy = CameraPolicy(raw_is_mirrored=False, preview_mirror=False)
    tf = CameraTransform(policy, 100, 100, _flip)
    assert tf.policy.canonical_needs_flip is True
    raw = (100, [10])                     # object appears at raw x=10
    canonical = tf.to_canonical(raw)
    assert canonical == (100, [90])       # now on the right, matching physical


def test_pre_mirrored_driver_needs_no_flip_no_double_flip():
    policy = CameraPolicy(raw_is_mirrored=True, preview_mirror=False)
    tf = CameraTransform(policy, 100, 100, _flip)
    assert tf.policy.canonical_needs_flip is False
    raw = (100, [90])
    assert tf.to_canonical(raw) == (100, [90])     # untouched — no double flip


def test_left_stays_left_right_stays_right_default():
    # canonical, non-mirrored preview: LEFT object at x=20, RIGHT at x=80
    policy = CameraPolicy(raw_is_mirrored=True, preview_mirror=False)
    tf = CameraTransform(policy, 100, 100, _flip)
    left = tf.to_canonical((100, [20]))
    right = tf.to_canonical((100, [80]))
    assert left[1][0] < 50 and right[1][0] > 50
    # preview leaves canonical unchanged when not mirroring
    assert tf.to_preview(left) == left
    assert tf.to_preview(right) == right


def test_preview_only_mirror_transforms_display_exactly_once():
    policy = CameraPolicy(raw_is_mirrored=True, preview_mirror=True)
    tf = CameraTransform(policy, 100, 100, _flip)
    canonical = tf.to_canonical((100, [80]))       # RIGHT object, x=80
    assert canonical == (100, [80])                 # inference space untouched
    preview = tf.to_preview(canonical)              # display flips once
    assert preview == (100, [20])


def test_point_and_box_mapping_follows_preview_mirror():
    policy = CameraPolicy(raw_is_mirrored=True, preview_mirror=True)
    tf = CameraTransform(policy, 640, 480, _flip)
    # a canonical box on the right maps to the left in the mirrored preview,
    # preserving x1<x2 so it stays attached to the (now flipped) object
    box = tf.preview_box([500, 100, 600, 200])
    assert box[0] < box[2]
    assert box == [40, 100, 140, 200]
    assert tf.preview_x(0) == 640
    assert tf.normalized_preview_x(0.25) == pytest.approx(0.75)


def test_no_mirror_leaves_points_unchanged():
    policy = CameraPolicy(raw_is_mirrored=True, preview_mirror=False)
    tf = CameraTransform(policy, 640, 480, _flip)
    assert tf.preview_x(123) == 123
    assert tf.preview_box([10, 20, 30, 40]) == [10, 20, 30, 40]
    assert tf.normalized_preview_x(0.3) == 0.3


def test_device_override_applies_only_to_matching_camera(monkeypatch):
    import jarvis.core.config as cfg

    def fake_section(path):
        if path == "vision.camera":
            return {"raw_is_mirrored": False,
                    "device_overrides": {"1": {"raw_is_mirrored": True}}}
        return {}
    monkeypatch.setattr(cfg, "section", fake_section)
    assert resolve_policy(0).raw_is_mirrored is False    # default camera
    assert resolve_policy(1).raw_is_mirrored is True     # overridden camera


# ── §16 GPU device resolver ──────────────────────────────────────────────

def test_prefers_first_available_backend_in_order():
    probes = {
        "tensorrt": lambda: None,
        "cuda": lambda: {"device": "cuda:0", "device_name": "RTX 4090",
                         "compute_capability": "8.9", "vram_mb": 24564,
                         "half_precision": True},
        "cpu": lambda: {"device": "cpu", "device_name": "CPU"},
    }
    caps = DeviceCapabilityResolver(probes).resolve(
        preference=["tensorrt", "cuda", "cpu"], half_precision="auto")
    assert caps.backend == "cuda"
    assert caps.device_name == "RTX 4090"
    assert caps.half_precision is True
    assert caps.cuda is True and caps.tensorrt is False


def test_falls_back_to_cpu_when_no_gpu_and_records_reason():
    probes = {"cuda": lambda: None, "directml": lambda: None,
              "cpu": lambda: {"device": "cpu", "device_name": "CPU"}}
    caps = DeviceCapabilityResolver(probes).resolve(
        preference=["cuda", "directml", "cpu"])
    assert caps.backend == "cpu"
    assert caps.half_precision is False
    assert "no GPU backend" in caps.fallback_reason


def test_probe_exception_never_crashes_selection():
    def boom():
        raise RuntimeError("driver exploded")
    probes = {"cuda": boom, "cpu": lambda: {"device": "cpu", "device_name": "CPU"}}
    caps = DeviceCapabilityResolver(probes).resolve(preference=["cuda", "cpu"])
    assert caps.backend == "cpu"          # §16: optional provider never crashes startup


def test_cpu_is_always_the_floor_even_if_omitted():
    probes = {"cuda": lambda: None, "cpu": lambda: {"device": "cpu", "device_name": "CPU"}}
    caps = DeviceCapabilityResolver(probes).resolve(preference=["cuda"])
    assert caps.backend == "cpu"


# ── §17 frame governor ───────────────────────────────────────────────────

class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _governor(gpu, monkeypatch, **overrides):
    import jarvis.core.config as cfg
    base = {"max_inflight_frames": 1, "queue_policy": "latest_frame",
            "cpu_fps_limit": 15, "gpu_fps_limit": None}
    base.update(overrides)
    monkeypatch.setattr(cfg, "section", lambda p: base if p == "vision.yolo" else {})
    return FrameGovernor(gpu_active=gpu, clock=_Clock())


def test_gpu_mode_has_no_artificial_inference_cap(monkeypatch):
    gov = _governor(True, monkeypatch)
    assert gov.has_inference_cap is False
    gov.submit("f1")
    assert gov.next_frame() == "f1"
    gov.submit("f2")
    assert gov.next_frame() == "f2"       # immediately, no sleep window


def test_cpu_mode_obeys_configured_limiter(monkeypatch):
    clock = _Clock()
    import jarvis.core.config as cfg
    monkeypatch.setattr(cfg, "section", lambda p: {
        "max_inflight_frames": 1, "queue_policy": "latest_frame",
        "cpu_fps_limit": 10, "gpu_fps_limit": None} if p == "vision.yolo" else {})
    gov = FrameGovernor(gpu_active=False, clock=clock)
    assert gov.has_inference_cap is True
    gov.submit("a")
    assert gov.next_frame() == "a"
    gov.submit("b")
    assert gov.next_frame() is None        # within the 0.1s window → paced out
    clock.advance(0.2)
    gov.submit("c")
    assert gov.next_frame() == "c"


def test_latest_frame_policy_drops_stale_frames(monkeypatch):
    gov = _governor(True, monkeypatch, max_inflight_frames=5)
    for f in ("f1", "f2", "f3"):
        gov.submit(f)
    assert gov.next_frame() == "f3"        # newest
    assert gov.dropped == 2                 # f1, f2 dropped as stale
    assert gov.queue_depth == 0


def test_queue_depth_bounded_by_max_inflight(monkeypatch):
    gov = _governor(True, monkeypatch, max_inflight_frames=2)
    for f in range(100):
        gov.submit(f)
    assert gov.queue_depth <= 2            # never grows unbounded
    assert gov.dropped >= 98


def test_explicit_gpu_limit_is_honored_when_set(monkeypatch):
    clock = _Clock()
    import jarvis.core.config as cfg
    monkeypatch.setattr(cfg, "section", lambda p: {
        "max_inflight_frames": 1, "queue_policy": "latest_frame",
        "cpu_fps_limit": 15, "gpu_fps_limit": 30} if p == "vision.yolo" else {})
    gov = FrameGovernor(gpu_active=True, clock=clock)
    assert gov.has_inference_cap is True   # opt-in cap respected


# MK50 §7 — resolver instalasi Tabbit dihapus bersama jalur Tabbit.
