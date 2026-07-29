"""Vision subsystem (Part 4) — isolated ``multiprocessing.Process``.

    camera → frame → ┬→ YOLOv8n (objects)  → ObjectEvent
                     └→ MediaPipe Hands    → GestureRecognizer → GestureEvent

The UI never touches the camera. The worker publishes events and annotated
JPEG frames over queues; a crash here can never take the UI down. Cursor
control (Part 4.3) also lives in the worker for latency — it acts only while
explicitly ARMED, always with pyautogui's FAILSAFE on, and PALM_HOLD_3S is
the always-active emergency stop.
"""
from __future__ import annotations

import multiprocessing as mp
import queue
import threading
import time

from jarvis.core import config, log
from jarvis.core.bus import BUS

_logger = log.get("vision")


# ═══════════════════════════════════════════════════════════════════════════
# Worker process (no Qt, no bus — queues only)
# ═══════════════════════════════════════════════════════════════════════════

class _CursorController:
    """Gesture → pointer actions. Part 4.3 requirements, enforced here."""

    def __init__(self, cfg: dict, frame_w: int, frame_h: int, events_out):
        import pyautogui
        pyautogui.FAILSAFE = True                     # required
        pyautogui.PAUSE = 0
        self._pg = pyautogui
        self._events = events_out
        self.screen_w, self.screen_h = pyautogui.size()
        self.frame_w, self.frame_h = frame_w, frame_h
        g = cfg
        self.inset = float(g.get("map_inset", 0.2))
        self.dead_zone = float(g.get("dead_zone_px", 3))
        self.cooldown = float(g.get("discrete_cooldown_ms", 300)) / 1000.0
        self.scroll_gain = int(g.get("scroll_gain", 120))
        oe = g.get("one_euro", {})
        from jarvis.vision.filters import PointFilter
        self._filter = PointFilter(
            min_cutoff=float(oe.get("min_cutoff", 1.0)),
            beta=float(oe.get("beta", 0.007)),
            d_cutoff=float(oe.get("d_cutoff", 1.0)))
        self.armed = False
        self._dragging = False
        self._last_xy: tuple[float, float] | None = None
        self._last_discrete = 0.0

    # ── arming ───────────────────────────────────────────────────────────────

    def set_armed(self, armed: bool) -> None:
        self.armed = armed
        if not armed:
            self._release_all()
        self._filter.reset()
        self._last_xy = None

    def emergency_stop(self) -> None:
        self._release_all()
        self.armed = False

    def _release_all(self) -> None:
        if self._dragging:
            try:
                self._pg.mouseUp()
            except Exception:
                pass
            self._dragging = False

    # ── continuous: cursor from index tip while OPEN_PALM ────────────────────

    def move_from_landmark(self, nx: float, ny: float, t: float) -> None:
        if not self.armed:
            return
        # landmarks arrive in canonical space (physical-right = +x), the same
        # space the preview shows — so canonical x maps to screen x directly
        # with no extra mirror (redesign §13: one authoritative transform)

        # map an inset sub-rectangle of the frame to the full screen to determine sensitivity
        lo, hi = self.inset, 1.0 - self.inset
        span = hi - lo
        
        # Apply scaling based on active zone span, but use it relatively
        scaled_x = (nx / span) * self.screen_w
        scaled_y = (ny / span) * self.screen_h
        
        fx, fy = self._filter.filter(scaled_x, scaled_y, t)
        
        if self._last_xy is not None:
            dx = fx - self._last_xy[0]
            dy = fy - self._last_xy[1]
            if abs(dx) > self.dead_zone or abs(dy) > self.dead_zone:
                try:
                    self._pg.move(int(dx), int(dy), _pause=False)
                except Exception:
                    pass
        self._last_xy = (fx, fy)

    # ── discrete gesture actions ─────────────────────────────────────────────

    def _cooldown_ok(self, t: float) -> bool:
        if t - self._last_discrete < self.cooldown:
            return False
        self._last_discrete = t
        return True

    def on_gesture(self, gesture: str, meta: dict, t: float) -> None:
        """Called for every recognizer event. Only acts when armed
        (except the emergency stop, which is handled by the worker)."""
        if not self.armed:
            return
        pg = self._pg
        try:
            if gesture == "PINCH" and self._cooldown_ok(t):
                pg.click()
            elif gesture == "DOUBLE_PINCH" and self._cooldown_ok(t):
                pg.doubleClick()
            elif gesture == "TWO_FINGER_PINCH" and self._cooldown_ok(t):
                pg.rightClick()
            elif gesture == "FIST_DOWN":
                if not self._dragging:
                    pg.mouseDown()
                    self._dragging = True
            elif gesture == "RELEASE":
                if self._dragging:
                    pg.mouseUp()
                    self._dragging = False
            elif gesture == "POINT_UP":
                pg.scroll(int(self.scroll_gain * meta.get("speed", 1.0)))
            elif gesture == "POINT_DOWN":
                pg.scroll(-int(self.scroll_gain * meta.get("speed", 1.0)))
            elif gesture == "SWIPE_LEFT" and self._cooldown_ok(t):
                pg.hotkey("alt", "left")
            elif gesture == "SWIPE_RIGHT" and self._cooldown_ok(t):
                pg.hotkey("alt", "right")
            elif gesture == "L_SHAPE" and self._cooldown_ok(t):
                self._screenshot()
        except self._pg.FailSafeException:
            self.emergency_stop()
            self._events.put({"type": "status", "armed": False,
                              "detail": "pyautogui failsafe triggered"})
        except Exception:
            pass

    def _screenshot(self) -> None:
        from pathlib import Path
        out_dir = Path(config.resolve_path(config.get("logging.dir", "logs"))) / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / f"gesture_{int(time.time())}.png"
        self._pg.screenshot(str(path))
        self._events.put({"type": "screenshot", "path": str(path)})


def _annotate(frame, boxes, hands_px, postures, armed, gesture_label, cv2,
              draw_objects=False, draw_hands=False):
    """Clean camera by default: object boxes and the hand skeleton are only
    drawn when explicitly enabled. The ARMED border always shows — it is a
    safety signal for gesture control, not decoration."""
    accent = (255, 229, 0)        # BGR of #00e5ff
    green = (128, 222, 74)        # BGR of #4ade80
    red = (68, 68, 255)           # BGR of #ff4444

    if draw_objects:
        for b in boxes:
            x1, y1, x2, y2 = (int(v) for v in b["xyxy"])
            cv2.rectangle(frame, (x1, y1), (x2, y2), accent, 2)
            label = f"{b['name']} {b['conf']:.2f}"
            cv2.putText(frame, label, (x1, max(14, y1 - 6)),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, accent, 1)

    if draw_hands:
        _HAND_EDGES = [(0,1),(1,2),(2,3),(3,4),(0,5),(5,6),(6,7),(7,8),(5,9),(9,10),
                       (10,11),(11,12),(9,13),(13,14),(14,15),(15,16),(13,17),
                       (17,18),(18,19),(19,20),(0,17)]
        for pts in hands_px:
            for a, b in _HAND_EDGES:
                cv2.line(frame, pts[a], pts[b], green, 1)
            for pt in pts:
                cv2.circle(frame, pt, 2, (255, 255, 255), -1)
        if gesture_label and gesture_label != "NONE":
            cv2.putText(frame, gesture_label, (12, 46),
                        cv2.FONT_HERSHEY_DUPLEX, 1.4, accent, 2)

    # unmistakable armed indicator (safety — always shown)
    h, w = frame.shape[:2]
    if armed:
        cv2.rectangle(frame, (0, 0), (w - 1, h - 1), red, 4)
        cv2.putText(frame, "ARMED", (w - 130, 34),
                    cv2.FONT_HERSHEY_DUPLEX, 1.0, red, 2)
    return frame


def _worker_main(cfg: dict, frame_q: mp.Queue, event_q: mp.Queue,
                 ctrl_q: mp.Queue) -> None:
    """Entry point of the vision child process."""
    try:
        import cv2
        import mediapipe as mp_lib
    except Exception as e:
        event_q.put({"type": "fatal", "detail": f"vision imports failed: {e}"})
        return

    from jarvis.vision.gestures import GestureRecognizer, Gesture, DISCRETE
    from jarvis.vision.yolo import YoloDetector

    vis = cfg["vision"]
    ges = cfg["gestures"]
    fw, fh = int(vis["frame_width"]), int(vis["frame_height"])
    target_dt = 1.0 / float(vis.get("target_fps", 20))
    # Selfie preview is mirrored; mirror the gesture-cursor x by the same flag
    # so moving the hand right also moves the pointer right (matches the view).
    selfie = bool(vis.get("preview_selfie", True))

    # Single authoritative camera transform (redesign §13). The raw driver
    # frame is converted into canonical space exactly once; inference AND
    # display then share that one frame, so overlays can never diverge and no
    # double-flip is possible. Preview mirroring, if enabled, is applied only
    # to the displayed frame after inference.
    from jarvis.vision.camera_transform import CameraPolicy, CameraTransform
    pol = vis.get("camera_policy", {})
    policy = CameraPolicy(
        raw_is_mirrored=bool(pol.get("raw_is_mirrored", False)),
        preview_mirror=bool(pol.get("preview_mirror", False)),
        inference_mirror=bool(pol.get("inference_mirror", False)))
    cam_tf = CameraTransform(policy, fw, fh, lambda f: cv2.flip(f, 1))

    cap = cv2.VideoCapture(int(vis.get("camera_index", 0)),
                           getattr(cv2, "CAP_DSHOW", 0))
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, fw)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, fh)
    if hasattr(cv2, "CAP_PROP_HW_ACCELERATION"):
        cap.set(cv2.CAP_PROP_HW_ACCELERATION, getattr(cv2, "VIDEO_ACCELERATION_ANY", 1))

    if not cap.isOpened():
        event_q.put({"type": "fatal", "detail": "camera unavailable"})
        return

    yolo = YoloDetector(vis["yolo_weights_abs"], conf=float(vis.get("yolo_conf", 0.5)),
                        tracker=vis.get("yolo_tracker", "bytetrack.yaml"),
                        every_n=int(vis.get("detect_every_n", 3)))
    hands_cfg = vis.get("hands", {})
    try:
        mp_hands = mp_lib.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=int(hands_cfg.get("max_num_hands", 2)),
            min_detection_confidence=float(hands_cfg.get("min_detection_confidence", 0.7)),
            min_tracking_confidence=float(hands_cfg.get("min_tracking_confidence", 0.6)))
    except Exception as e:
        mp_hands = None
        event_q.put({"type": "status", "armed": False,
                     "detail": f"hands disabled: {e}"})

    recognizer = GestureRecognizer(ges, frame_width=fw)
    cursor = _CursorController(ges, fw, fh, event_q)

    event_q.put({"type": "status", "armed": False, "alive": True,
                 "detail": f"vision online (yolo={'ok' if yolo.available else 'off'})"})

    running = True
    fist_down_sent = False
    frame_count = 0
    fps_t0 = time.monotonic()
    while running:
        loop_t0 = time.monotonic()

        # control commands
        try:
            while True:
                cmd = ctrl_q.get_nowait()
                if cmd == "stop":
                    running = False
                elif cmd == "arm":
                    cursor.set_armed(True)
                    event_q.put({"type": "status", "armed": True,
                                 "detail": "gesture control ARMED"})
                elif cmd == "disarm":
                    cursor.set_armed(False)
                    event_q.put({"type": "status", "armed": False,
                                 "detail": "gesture control disarmed"})
        except queue.Empty:
            pass
        if not running:
            break

        ok, frame = cap.read()
        if not ok or frame is None:
            time.sleep(0.05)
            continue
        raw = cv2.resize(frame, (fw, fh))
        # raw → canonical (physical-right = +x = displayed-right), one flip max
        frame = cam_tf.to_canonical(raw)
        now = time.monotonic()

        # inference runs on the canonical frame — the same space the preview
        # shows — so YOLO boxes, hand landmarks, gesture regions, and the
        # emergency-stop test all stay aligned with what the user sees.
        boxes = yolo.process(frame)

        hands_norm: list[list[tuple[float, float, float]]] = []
        hands_px: list[list[tuple[int, int]]] = []
        if mp_hands is not None:
            rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            res = mp_hands.process(rgb)
            if res.multi_hand_landmarks:
                for hl in res.multi_hand_landmarks:
                    pts = [(l.x, l.y, l.z) for l in hl.landmark]
                    hands_norm.append(pts)
                    hands_px.append([(int(l.x * fw), int(l.y * fh))
                                     for l in hl.landmark])

        events, postures = recognizer.update(hands_norm, now)
        posture0 = postures.get(0, Gesture.NONE)

        # continuous cursor: OPEN_PALM steers with the index tip
        if posture0 == Gesture.OPEN_PALM and hands_norm:
            tip = hands_norm[0][8]
            tx = (1.0 - tip[0]) if selfie else tip[0]   # match the mirrored view
            cursor.move_from_landmark(tx, tip[1], now)

        # FIST posture edge → mouse down (release handled by RELEASE event)
        if posture0 == Gesture.FIST and not fist_down_sent:
            fist_down_sent = True
            cursor.on_gesture("FIST_DOWN", {}, now)
        elif posture0 != Gesture.FIST:
            fist_down_sent = False

        # continuous scroll while pointing
        if posture0 in (Gesture.POINT_UP, Gesture.POINT_DOWN):
            cursor.on_gesture(posture0.value, {"speed": 1.0}, now)

        for ev in events:
            if ev.gesture == Gesture.PALM_HOLD_3S:
                # emergency stop works even when nothing else is bound yet
                cursor.emergency_stop()
                event_q.put({"type": "status", "armed": False,
                             "detail": "EMERGENCY STOP (palm hold 3s)"})
            else:
                cursor.on_gesture(ev.gesture.value, ev.meta, ev.t)
            event_q.put({"type": "gesture", "gesture": ev.gesture.value,
                         "hand": ev.hand, "meta": ev.meta})

        if boxes:
            event_q.put({"type": "objects",
                         "objects": [{"name": b["name"], "conf": round(b["conf"], 2),
                                      "id": b["id"]} for b in boxes]})

        display_gesture = posture0.value
        for ev in events:
            if ev.gesture in DISCRETE:
                display_gesture = ev.gesture.value
        # annotate in canonical space (overlays share the frame's coordinates)
        ov = vis.get("overlay", {})
        frame = _annotate(frame, boxes, hands_px, postures, cursor.armed,
                          display_gesture, cv2,
                          draw_objects=bool(ov.get("draw_objects", False)),
                          draw_hands=bool(ov.get("draw_hands", False)))
        # presentation-only preview mirror, applied AFTER inference+annotation
        # so the single canonical space governs detection while the user can
        # still opt into a selfie preview (overlays flip with the image).
        frame = cam_tf.to_preview(frame)

        okj, buf = cv2.imencode(".jpg", frame,
                                [cv2.IMWRITE_JPEG_QUALITY,
                                 int(vis.get("jpeg_quality", 70))])
        if okj:
            try:
                frame_q.put_nowait(buf.tobytes())
            except queue.Full:
                pass                                   # drop — UI is behind

        frame_count += 1
        if now - fps_t0 >= 5.0:
            event_q.put({"type": "fps", "fps": round(frame_count / (now - fps_t0), 1)})
            frame_count, fps_t0 = 0, now

        sleep_for = target_dt - (time.monotonic() - loop_t0)
        if sleep_for > 0:
            time.sleep(sleep_for)

    cursor.emergency_stop()
    cap.release()
    event_q.put({"type": "status", "armed": False, "alive": False,
                 "detail": "vision worker stopped"})


# ═══════════════════════════════════════════════════════════════════════════
# UI-side manager
# ═══════════════════════════════════════════════════════════════════════════

class VisionSystem:
    """Owns the child process and republishes its queue traffic on the bus."""

    def __init__(self) -> None:
        self._proc: mp.Process | None = None
        self._frame_q: mp.Queue | None = None
        self._event_q: mp.Queue | None = None
        self._ctrl_q: mp.Queue | None = None
        self._drain: threading.Thread | None = None
        self._stop = threading.Event()
        self.armed = False
        self.alive = False
        self._latest_jpeg: bytes | None = None    # newest frame for on-demand vision
        self._frame_lock = threading.Lock()

    def start(self) -> bool:
        if self._proc is not None and self._proc.is_alive():
            return True
        # resolve the per-device canonical camera policy on the UI side and
        # hand it to the worker (spawn ctx can't share config singletons)
        from jarvis.vision.camera_transform import resolve_policy
        policy = resolve_policy(config.get("vision.camera_index", 0))
        cfg = {
            "vision": {**config.section("vision"),
                       "yolo_weights_abs": str(config.resolve_path(
                           config.get("vision.yolo_weights", "yolov8n.pt"))),
                       "camera_policy": {
                           "raw_is_mirrored": policy.raw_is_mirrored,
                           "preview_mirror": policy.preview_mirror,
                           "inference_mirror": policy.inference_mirror}},
            "gestures": config.section("gestures"),
        }
        ctx = mp.get_context("spawn")
        self._frame_q = ctx.Queue(maxsize=2)
        self._event_q = ctx.Queue(maxsize=256)
        self._ctrl_q = ctx.Queue()
        self._proc = ctx.Process(
            target=_worker_main,
            args=(cfg, self._frame_q, self._event_q, self._ctrl_q),
            daemon=True, name="jarvis-vision")
        try:
            self._proc.start()
        except Exception as e:
            _logger.error("vision.start_failed", error=str(e)[:200])
            return False
        self._stop.clear()
        self._drain = threading.Thread(target=self._drain_loop, daemon=True,
                                       name="vision-drain")
        self._drain.start()
        _logger.info("vision.process_started", pid=self._proc.pid)
        return True

    def stop(self) -> None:
        if self._ctrl_q is not None:
            try:
                self._ctrl_q.put("stop")
            except Exception:
                pass
        self._stop.set()
        if self._proc is not None:
            self._proc.join(timeout=3)
            if self._proc.is_alive():
                self._proc.terminate()
            self._proc = None
        with self._frame_lock:
            self._latest_jpeg = None
        self.alive = False

    def latest_frame_jpeg(self, timeout: float = 2.5) -> bytes | None:
        """Newest camera frame (clean, canonical) from the worker — the single
        camera owner. Used for on-demand vision so JARVIS never opens a second
        camera handle (the cause of intermittent 'can't see')."""
        import time as _t
        deadline = _t.monotonic() + timeout
        while _t.monotonic() < deadline:
            with self._frame_lock:
                if self._latest_jpeg is not None:
                    return self._latest_jpeg
            if self._stop.wait(0.05):
                break
        with self._frame_lock:
            return self._latest_jpeg

    def arm(self) -> None:
        if self._ctrl_q is not None:
            self._ctrl_q.put("arm")

    def disarm(self) -> None:
        if self._ctrl_q is not None:
            self._ctrl_q.put("disarm")

    # ── queue → bus ──────────────────────────────────────────────────────────

    def _drain_loop(self) -> None:
        while not self._stop.is_set():
            drained = False
            try:
                ev = self._event_q.get(timeout=0.02)
                drained = True
                self._handle_event(ev)
            except queue.Empty:
                pass
            except (EOFError, OSError):
                break
            try:
                jpeg = None
                while True:                       # keep only the newest frame
                    jpeg = self._frame_q.get_nowait()
            except queue.Empty:
                if jpeg is not None:
                    drained = True
                    with self._frame_lock:
                        self._latest_jpeg = jpeg
                    BUS.publish("vision.frame", jpeg=jpeg)
            except (EOFError, OSError):
                break
            if not drained:
                # crash detection: process died without a farewell event
                if self._proc is not None and not self._proc.is_alive() and self.alive:
                    self.alive = False
                    _logger.error("vision.process_died")
                    BUS.publish("vision.status", armed=False, alive=False,
                                detail="vision process died — UI unaffected")

    def _handle_event(self, ev: dict) -> None:
        kind = ev.get("type")
        if kind == "status":
            self.armed = bool(ev.get("armed", False))
            if "alive" in ev:
                self.alive = bool(ev["alive"])
            else:
                self.alive = True
            _logger.info("vision.status", **{k: v for k, v in ev.items()
                                             if k != "type"})
            BUS.publish("vision.status", armed=self.armed, alive=self.alive,
                        detail=ev.get("detail", ""))
        elif kind == "gesture":
            _logger.info("vision.gesture", gesture=ev.get("gesture"),
                         hand=ev.get("hand"))
            BUS.publish("vision.gesture", gesture=ev.get("gesture"),
                        meta=ev.get("meta", {}))
        elif kind == "objects":
            BUS.publish("vision.object", objects=ev.get("objects", []))
        elif kind == "fps":
            BUS.publish("vision.status", armed=self.armed, alive=True,
                        detail=f"{ev.get('fps')} fps")
        elif kind == "screenshot":
            _logger.info("vision.screenshot", path=ev.get("path"))
            BUS.publish("notify", title="Screenshot",
                        body=ev.get("path", ""))
        elif kind == "fatal":
            self.alive = False
            _logger.error("vision.fatal", detail=ev.get("detail"))
            BUS.publish("vision.status", armed=False, alive=False,
                        detail=ev.get("detail", "vision failed"))
