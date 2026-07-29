"""Canonical camera coordinate space (redesign §13/§14).

Root cause of "move right → appears left": a raw webcam faces the user, so a
hand moved to the user's PHYSICAL right lands on the raw image's LEFT. The
old pipeline applied one ad-hoc ``cv2.flip`` gated by ``vision.mirror`` and
every consumer (preview, YOLO, MediaPipe, cursor, emergency stop) implicitly
assumed that flip — correct only by coincidence, with no per-device handling
and no single source of truth, so a driver that already delivers mirrored
frames (many do) silently double-flips or un-mirrors.

This module defines ONE canonical space and the single transform into it:

    Canonical space: +x points to the user's PHYSICAL right, matching the
    ContentStage preview. Detection boxes, hand landmarks, gesture regions,
    and the emergency-stop test all live in this one space, so they can
    never diverge from what is shown.

``CameraTransform`` converts a raw driver frame into the canonical frame
exactly once. Everything downstream (inference AND display) consumes the
canonical frame, guaranteeing alignment with zero double-flips. Preview
mirroring, when explicitly enabled, is a *presentation-only* horizontal flip
applied after inference — and point mapping accounts for it so overlays
stay attached.

Pure geometry + an injected flip function, so it is unit-testable with no
camera and no OpenCV import at module load.
"""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.core import config


@dataclass(frozen=True)
class CameraPolicy:
    """Resolved per-camera orientation policy.

    raw_is_mirrored: the driver ALREADY delivers a selfie-mirrored frame
        (physical-right already on the right). Then reaching canonical
        needs NO flip. If the driver delivers a true optical frame
        (physical-right on the left), canonical needs one horizontal flip.
    preview_mirror: present a mirrored (selfie) preview. Presentation only.
    inference_mirror: also feed the mirrored frame to inference. Kept for
        explicit parity; canonical already aligns inference with the
        non-mirrored display, so this is only for callers who deliberately
        want inference in the mirrored frame.
    """

    raw_is_mirrored: bool = False
    preview_mirror: bool = False
    inference_mirror: bool = False

    @property
    def canonical_needs_flip(self) -> bool:
        # optical raw (not pre-mirrored) → flip once to reach canonical
        return not self.raw_is_mirrored


def resolve_policy(device_key: str | int = 0) -> CameraPolicy:
    """Build the policy for one camera from config, applying any
    ``vision.camera.device_overrides.<key>`` on top of the base settings."""
    cam = config.section("vision.camera")
    base = {
        "raw_is_mirrored": bool(cam.get("raw_is_mirrored", False)),
        "preview_mirror": bool(cam.get("preview_mirror", False)),
        "inference_mirror": bool(cam.get("inference_mirror", False)),
    }
    overrides = cam.get("device_overrides", {}) or {}
    ov = overrides.get(str(device_key), overrides.get(device_key, {})) or {}
    for k in base:
        if k in ov:
            base[k] = bool(ov[k])
    return CameraPolicy(**base)


class CameraTransform:
    """Single authoritative raw→canonical converter.

    ``flip_fn`` performs a horizontal flip of a frame (in the worker this is
    ``lambda f: cv2.flip(f, 1)``); injected so this class needs no OpenCV.
    """

    def __init__(self, policy: CameraPolicy, width: int, height: int, flip_fn):
        self.policy = policy
        self.width = width
        self.height = height
        self._flip = flip_fn

    # ── frames ────────────────────────────────────────────────────────────

    def to_canonical(self, raw_frame):
        """Raw driver frame → canonical frame (exactly one flip at most)."""
        if self.policy.canonical_needs_flip:
            return self._flip(raw_frame)
        return raw_frame

    def to_preview(self, canonical_frame):
        """Canonical frame → what ContentStage shows. Preview mirroring is a
        presentation-only flip; without it the preview IS the canonical
        frame, so physical-right shows on the right."""
        if self.policy.preview_mirror:
            return self._flip(canonical_frame)
        return canonical_frame

    # ── point mapping (keeps overlays attached) ──────────────────────────

    def preview_x(self, canonical_x: float) -> float:
        """Map a canonical x to preview x. Only differs when preview mirror
        is on — the single place that horizontal flip is accounted for, so
        boxes/landmarks/gesture regions never drift."""
        if self.policy.preview_mirror:
            return self.width - canonical_x
        return canonical_x

    def preview_point(self, canonical_x: float, canonical_y: float):
        return (self.preview_x(canonical_x), canonical_y)   # vertical unchanged

    def preview_box(self, xyxy):
        """Map a canonical [x1,y1,x2,y2] box into preview space, preserving
        x1<x2 ordering after any mirror."""
        x1, y1, x2, y2 = xyxy
        px1, px2 = self.preview_x(x1), self.preview_x(x2)
        lo, hi = (px1, px2) if px1 <= px2 else (px2, px1)
        return [lo, y1, hi, y2]

    def normalized_preview_x(self, canonical_nx: float) -> float:
        """Normalized-coordinate (0..1) variant for MediaPipe landmarks."""
        return (1.0 - canonical_nx) if self.policy.preview_mirror else canonical_nx
