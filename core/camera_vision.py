import cv2
import numpy as np
import math

from jarvis.core import quiet

try:
    import mediapipe as mp
except ImportError:
    mp = None

try:
    import matplotlib
    matplotlib.use('Agg')
    from ultralytics import YOLO
except ImportError:
    YOLO = None

class VisionProcessor:
    def __init__(self):
        self.mp_hands = mp.solutions.hands.Hands(
            static_image_mode=False,
            max_num_hands=1,
            min_detection_confidence=0.7,
            min_tracking_confidence=0.7
        ) if mp else None
        self.mp_draw = mp.solutions.drawing_utils if mp else None

        # Overlay flags — a clean, selfie-style camera by default (no YOLO
        # boxes, no hand skeleton). Detection still runs so JARVIS stays
        # object-aware; only the drawing is suppressed. Overridable in
        # config/api_keys.json.
        self.draw_boxes = False
        self.draw_hands = False
        self.enable_gestures = True

        # GPU auto-select — used for every inference call below.
        self.device = "cpu"
        try:
            import torch
            if torch.cuda.is_available():
                self.device = "cuda"
                print("[Vision] ✅ YOLOv8 on GPU (CUDA)")
        except Exception:
            self.device = "cpu"

        self.yolo_model = self._load_yolo() if YOLO else None

        self.is_pinching = False
        self.pinch_start_pos = None

        self.frame_count = 0
        self.skip_frames = 5
        self.last_hand_landmarks = None
        self.last_yolo_boxes = []
        self.reload_config()

    def _yolo_weights(self) -> str:
        """Configured detector weights. Default: Open Images V7 (~600 classes)
        — far more recognizable objects than COCO's 80. Override with
        `yolo_weights` in config/api_keys.json."""
        try:
            import json
            from pathlib import Path
            p = Path(__file__).parent.parent / "config" / "api_keys.json"
            w = json.loads(p.read_text(encoding="utf-8")).get("yolo_weights")
            return w or "yolov8s-oiv7.pt"
        except Exception:
            return "yolov8s-oiv7.pt"

    def _load_yolo(self):
        """Load the configured model; fall back to yolov8n.pt if it can't be
        fetched/loaded so the camera never breaks on a bad weights name or an
        offline first run."""
        want = self._yolo_weights()
        for weights in (want, "yolov8n.pt"):
            try:
                model = YOLO(weights)
                print(f"[Vision] ✅ YOLO loaded: {weights} "
                      f"({len(model.names)} classes) on {self.device}")
                return model
            except Exception as e:
                print(f"[Vision] ⚠️  YOLO load failed for {weights}: {e}")
        return None

    def reload_config(self):
        import json
        from pathlib import Path
        config_path = Path(__file__).parent.parent / "config" / "api_keys.json"
        try:
            with open(config_path, "r") as f:
                cfg = json.load(f)
                self.enable_gestures = cfg.get("enable_gestures", True)
                self.draw_boxes = bool(cfg.get("camera_draw_boxes", False))
                self.draw_hands = bool(cfg.get("camera_draw_hands", False))
        except Exception as exc:
            quiet.swallowed("core.camera_vision.config_load_failed", exc)

    def process_frame(self, frame):
        self.frame_count += 1
        run_heavy = (self.frame_count % self.skip_frames == 0)

        # MediaPipe Hand Tracking (Gesture Control)
        if self.mp_hands and run_heavy and self.enable_gestures:
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            results = self.mp_hands.process(frame_rgb)
            self.last_hand_landmarks = results.multi_hand_landmarks

        if self.last_hand_landmarks and self.enable_gestures:
            for hand_landmarks in self.last_hand_landmarks:
                if self.mp_draw and self.draw_hands:
                    self.mp_draw.draw_landmarks(frame, hand_landmarks, mp.solutions.hands.HAND_CONNECTIONS)

                # Check Pinch Gesture
                thumb_tip = hand_landmarks.landmark[mp.solutions.hands.HandLandmark.THUMB_TIP]
                index_tip = hand_landmarks.landmark[mp.solutions.hands.HandLandmark.INDEX_FINGER_TIP]
                
                dist = math.hypot(thumb_tip.x - index_tip.x, thumb_tip.y - index_tip.y)
                if dist < 0.05:
                    if not self.is_pinching:
                        self.is_pinching = True
                        self.pinch_start_pos = (index_tip.x, index_tip.y)
                else:
                    self.is_pinching = False
                    self.pinch_start_pos = None
        else:
            self.is_pinching = False
            self.pinch_start_pos = None

        # YOLO Object Detection
        if self.yolo_model:
            if run_heavy:
                results = self.yolo_model(frame, stream=True, verbose=False, device=self.device)
                boxes_cache = []
                for r in results:
                    for box in r.boxes:
                        boxes_cache.append({
                            'xyxy': [float(x) for x in box.xyxy[0]],
                            'conf': float(box.conf[0]),
                            'cls': int(box.cls[0])
                        })
                self.last_yolo_boxes = boxes_cache

            # Detection stays live (object awareness) but the camera view is
            # kept clean — boxes/labels only drawn when explicitly enabled.
            if self.draw_boxes:
                for box in self.last_yolo_boxes:
                    x1, y1, x2, y2 = (int(v) for v in box['xyxy'])
                    conf = math.ceil((box['conf'] * 100)) / 100
                    if conf > 0.5:
                        label = f"{self.yolo_model.names[box['cls']]} {conf:.2f}"
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (255, 212, 0), 2)
                        (tw, th), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)
                        cv2.rectangle(frame, (x1, max(y1 - 20, 0)), (x1 + tw, max(y1, 20)), (255, 212, 0), -1)
                        cv2.putText(frame, label, (x1, max(y1 - 5, 15)), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1)

        return frame, self.is_pinching, self.pinch_start_pos
