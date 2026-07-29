"""GestureRecognizer (Part 4.2) — MediaPipe landmark geometry → gestures.

Pure geometry + a small FSM for the dynamic gestures (transitions, double
pinch, swipes, palm-hold). No MediaPipe import here: the recognizer consumes
plain ``[(x, y, z), ...] * 21`` normalized landmark lists, which keeps it unit
testable without a camera.

MediaPipe hand landmark indices:
    0 wrist · 1-4 thumb · 5-8 index · 9-12 middle · 13-16 ring · 17-20 pinky
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from enum import Enum


class Gesture(str, Enum):
    NONE             = "NONE"
    OPEN_PALM        = "OPEN_PALM"
    FIST             = "FIST"
    RELEASE          = "RELEASE"            # FIST → OPEN_PALM transition
    PINCH            = "PINCH"
    DOUBLE_PINCH     = "DOUBLE_PINCH"
    TWO_FINGER_PINCH = "TWO_FINGER_PINCH"
    POINT_UP         = "POINT_UP"
    POINT_DOWN       = "POINT_DOWN"
    PEACE_V          = "PEACE_V"
    THUMBS_UP        = "THUMBS_UP"
    THUMBS_DOWN      = "THUMBS_DOWN"
    SPREAD_TO_FIST   = "SPREAD_TO_FIST"     # both hands palm → fist
    SWIPE_LEFT       = "SWIPE_LEFT"
    SWIPE_RIGHT      = "SWIPE_RIGHT"
    L_SHAPE          = "L_SHAPE"
    PALM_HOLD_3S     = "PALM_HOLD_3S"       # emergency stop


# discrete gestures are one-shot events; postures are continuous states
DISCRETE = {
    Gesture.PINCH, Gesture.DOUBLE_PINCH, Gesture.TWO_FINGER_PINCH,
    Gesture.RELEASE, Gesture.SPREAD_TO_FIST, Gesture.SWIPE_LEFT,
    Gesture.SWIPE_RIGHT, Gesture.L_SHAPE, Gesture.PALM_HOLD_3S,
    Gesture.THUMBS_UP, Gesture.THUMBS_DOWN,
}

WRIST = 0
THUMB_TIP, THUMB_IP, THUMB_MCP = 4, 3, 2
INDEX_TIP, INDEX_PIP, INDEX_MCP = 8, 6, 5
MIDDLE_TIP, MIDDLE_PIP = 12, 10
RING_TIP, RING_PIP = 16, 14
PINKY_TIP, PINKY_PIP = 20, 18

Point = tuple[float, float, float]


def _d(a: Point, b: Point) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


@dataclass
class HandPose:
    """Static posture analysis for one hand."""
    landmarks: list[Point]
    thumb: bool = False
    index: bool = False
    middle: bool = False
    ring: bool = False
    pinky: bool = False

    @property
    def extended_count(self) -> int:
        return sum((self.thumb, self.index, self.middle, self.ring, self.pinky))

    @property
    def fingers_only(self) -> int:      # excludes thumb
        return sum((self.index, self.middle, self.ring, self.pinky))


def analyze_pose(lm: list[Point]) -> HandPose:
    wrist = lm[WRIST]
    pose = HandPose(landmarks=lm)

    def finger_extended(tip: int, pip: int) -> bool:
        return _d(lm[tip], wrist) > _d(lm[pip], wrist) * 1.15

    pose.index  = finger_extended(INDEX_TIP, INDEX_PIP)
    pose.middle = finger_extended(MIDDLE_TIP, MIDDLE_PIP)
    pose.ring   = finger_extended(RING_TIP, RING_PIP)
    pose.pinky  = finger_extended(PINKY_TIP, PINKY_PIP)
    # thumb: tip clearly beyond the IP joint relative to the index MCP
    pose.thumb = _d(lm[THUMB_TIP], lm[INDEX_MCP]) > _d(lm[THUMB_IP], lm[INDEX_MCP]) * 1.10
    return pose


def _static_gesture(pose: HandPose, pinch_norm: float) -> Gesture:
    lm = pose.landmarks

    # pinches take precedence when the relevant tips touch. The thumb must be
    # extended (reaching out) — a curled thumb resting near curled fingertips
    # inside a fist or point posture is NOT a pinch. If both candidate tips
    # are within range, the closer one wins.
    if pose.thumb:
        d_index = _d(lm[THUMB_TIP], lm[INDEX_TIP])
        d_middle = _d(lm[THUMB_TIP], lm[MIDDLE_TIP])
        if d_middle < pinch_norm and d_middle < d_index:
            return Gesture.TWO_FINGER_PINCH
        if d_index < pinch_norm:
            return Gesture.PINCH

    if pose.extended_count == 5:
        return Gesture.OPEN_PALM
    if pose.extended_count == 0:
        return Gesture.FIST

    if pose.thumb and pose.index and pose.fingers_only == 1:
        # L-shape: thumb ⊥ index (60–120°)
        v_t = (lm[THUMB_TIP][0] - lm[THUMB_MCP][0], lm[THUMB_TIP][1] - lm[THUMB_MCP][1])
        v_i = (lm[INDEX_TIP][0] - lm[INDEX_MCP][0], lm[INDEX_TIP][1] - lm[INDEX_MCP][1])
        den = (math.hypot(*v_t) * math.hypot(*v_i)) or 1e-9
        ang = math.degrees(math.acos(
            max(-1.0, min(1.0, (v_t[0] * v_i[0] + v_t[1] * v_i[1]) / den))))
        if 60 <= ang <= 120:
            return Gesture.L_SHAPE

    if pose.index and pose.middle and not pose.ring and not pose.pinky and not pose.thumb:
        return Gesture.PEACE_V

    if pose.index and pose.fingers_only == 1 and not pose.thumb:
        # pointing direction: tip vs MCP, y grows downward in image space
        dy = lm[INDEX_TIP][1] - lm[INDEX_MCP][1]
        dx = lm[INDEX_TIP][0] - lm[INDEX_MCP][0]
        if abs(dy) > abs(dx):
            return Gesture.POINT_UP if dy < 0 else Gesture.POINT_DOWN

    if pose.thumb and pose.fingers_only == 0:
        dy = lm[THUMB_TIP][1] - lm[THUMB_MCP][1]
        return Gesture.THUMBS_UP if dy < 0 else Gesture.THUMBS_DOWN

    return Gesture.NONE


@dataclass
class GestureEvent:
    gesture: Gesture
    hand: int                 # 0 / 1
    t: float
    meta: dict = field(default_factory=dict)


@dataclass
class _HandTrack:
    posture: Gesture = Gesture.NONE
    prev_posture: Gesture = Gesture.NONE
    last_pinch_t: float = -10.0
    pinch_active: bool = False
    two_pinch_active: bool = False
    palm_since: float | None = None
    palm_anchor: Point | None = None
    cx_hist: list[tuple[float, float]] = field(default_factory=list)  # (t, x)
    emitted_hold: bool = False


class GestureRecognizer:
    """Feed per-frame landmarks; emits one-shot events + continuous postures."""

    def __init__(self, cfg: dict | None = None, frame_width: int = 640):
        cfg = cfg or {}
        self.pinch_norm = float(cfg.get("pinch_px", 40)) / float(frame_width)
        self.double_pinch_s = float(cfg.get("double_pinch_ms", 400)) / 1000.0
        self.swipe_velocity = float(cfg.get("swipe_velocity", 0.9))
        self.palm_hold_s = float(cfg.get("palm_hold_s", 3.0))
        self.hold_move_eps = 0.04         # normalized drift allowed while holding
        self._tracks: dict[int, _HandTrack] = {}
        self._both_palms_t: float | None = None

    def update(self, hands: list[list[Point]],
               t: float | None = None) -> tuple[list[GestureEvent], dict[int, Gesture]]:
        t = time.monotonic() if t is None else t
        events: list[GestureEvent] = []
        postures: dict[int, Gesture] = {}

        for i, lm in enumerate(hands[:2]):
            track = self._tracks.setdefault(i, _HandTrack())
            pose = analyze_pose(lm)
            g = _static_gesture(pose, self.pinch_norm)
            track.prev_posture, track.posture = track.posture, g
            postures[i] = g
            events.extend(self._dynamic(track, pose, g, i, t))

        # SPREAD_TO_FIST: both hands were palms, both became fists
        if len(hands) >= 2:
            g0 = self._tracks.get(0)
            g1 = self._tracks.get(1)
            if g0 and g1:
                if g0.posture == g1.posture == Gesture.OPEN_PALM:
                    self._both_palms_t = t
                elif (g0.posture == g1.posture == Gesture.FIST
                      and self._both_palms_t is not None
                      and t - self._both_palms_t < 1.2):
                    events.append(GestureEvent(Gesture.SPREAD_TO_FIST, 0, t))
                    self._both_palms_t = None
        else:
            self._both_palms_t = None

        # drop stale tracks
        for idx in list(self._tracks):
            if idx >= len(hands):
                del self._tracks[idx]

        return events, postures

    # ── dynamic gesture FSM per hand ─────────────────────────────────────────

    def _dynamic(self, track: _HandTrack, pose: HandPose, g: Gesture,
                 hand: int, t: float) -> list[GestureEvent]:
        events: list[GestureEvent] = []
        lm = pose.landmarks

        # PINCH onset → click; two onsets < 400 ms → DOUBLE_PINCH
        if g == Gesture.PINCH and not track.pinch_active:
            track.pinch_active = True
            if t - track.last_pinch_t < self.double_pinch_s:
                events.append(GestureEvent(Gesture.DOUBLE_PINCH, hand, t))
            else:
                events.append(GestureEvent(Gesture.PINCH, hand, t))
            track.last_pinch_t = t
        elif g != Gesture.PINCH:
            track.pinch_active = False

        if g == Gesture.TWO_FINGER_PINCH and not track.two_pinch_active:
            track.two_pinch_active = True
            events.append(GestureEvent(Gesture.TWO_FINGER_PINCH, hand, t))
        elif g != Gesture.TWO_FINGER_PINCH:
            track.two_pinch_active = False

        # FIST → OPEN_PALM = release (mouse up)
        if g == Gesture.OPEN_PALM and track.prev_posture == Gesture.FIST:
            events.append(GestureEvent(Gesture.RELEASE, hand, t))

        # one-shot thumbs (posture edge, not continuous re-fire)
        if g in (Gesture.THUMBS_UP, Gesture.THUMBS_DOWN) and track.prev_posture != g:
            events.append(GestureEvent(g, hand, t))

        if g == Gesture.L_SHAPE and track.prev_posture != Gesture.L_SHAPE:
            events.append(GestureEvent(Gesture.L_SHAPE, hand, t))

        # palm-derived dynamics: swipe + emergency hold
        cx = (lm[WRIST][0] + lm[MIDDLE_PIP][0]) / 2
        cy = (lm[WRIST][1] + lm[MIDDLE_PIP][1]) / 2
        if g == Gesture.OPEN_PALM:
            track.cx_hist.append((t, cx))
            track.cx_hist = [(tt, xx) for tt, xx in track.cx_hist if t - tt <= 0.35]
            if len(track.cx_hist) >= 3:
                (t0, x0), (t1, x1) = track.cx_hist[0], track.cx_hist[-1]
                dt = t1 - t0
                if dt > 0.08:
                    v = (x1 - x0) / dt        # frame-widths per second
                    if abs(v) > self.swipe_velocity:
                        events.append(GestureEvent(
                            Gesture.SWIPE_RIGHT if v > 0 else Gesture.SWIPE_LEFT,
                            hand, t, {"velocity": v}))
                        track.cx_hist.clear()

            if track.palm_since is None:
                track.palm_since = t
                track.palm_anchor = (cx, cy, 0.0)
                track.emitted_hold = False
            else:
                anchor = track.palm_anchor or (cx, cy, 0.0)
                if math.hypot(cx - anchor[0], cy - anchor[1]) > self.hold_move_eps:
                    track.palm_since = t
                    track.palm_anchor = (cx, cy, 0.0)
                    track.emitted_hold = False
                elif (not track.emitted_hold
                      and t - track.palm_since >= self.palm_hold_s):
                    track.emitted_hold = True
                    events.append(GestureEvent(Gesture.PALM_HOLD_3S, hand, t))
        else:
            track.palm_since = None
            track.palm_anchor = None
            track.cx_hist.clear()
            track.emitted_hold = False

        return events
