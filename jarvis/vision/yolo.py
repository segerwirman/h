"""YOLOv8n object detection with ByteTrack gap-filling (Part 4.1).

Detection runs every Nth frame; between detections the last tracked boxes are
reused, so the overlay stays at camera FPS while the GPU/CPU only pays for
1-in-N inferences. All imports are wrapped — missing weights or ultralytics
degrade to "no object detection" without touching the rest of vision.
"""
from __future__ import annotations


class YoloDetector:
    def __init__(self, weights_path: str, conf: float = 0.5,
                 tracker: str = "bytetrack.yaml", every_n: int = 3):
        self.available = False
        self.conf = conf
        self.every_n = max(1, every_n)
        self._tracker = tracker
        self._model = None
        self._device = "cpu"
        self._frame_i = 0
        self._last: list[dict] = []
        self.names: dict[int, str] = {}
        try:
            import torch
            self._device = 0 if torch.cuda.is_available() else "cpu"
        except Exception:
            self._device = "cpu"
        self._model = self._load(weights_path)
        if self._model is not None:
            self.names = dict(self._model.names)
            self.available = True

    def _load(self, weights_path: str):
        """Load configured weights. If the absolute path is missing, retry with
        the bare name so ultralytics auto-downloads it (e.g. Open Images V7);
        finally fall back to yolov8n.pt so a bad name never kills detection."""
        import os
        try:
            from ultralytics import YOLO
        except Exception as e:
            self._error = str(e)[:200]
            return None
        candidates = [weights_path]
        base = os.path.basename(weights_path)
        if base and base != weights_path and not os.path.exists(weights_path):
            candidates.append(base)          # bare name → auto-download
        candidates.append("yolov8n.pt")
        for w in candidates:
            try:
                return YOLO(w)
            except Exception as e:
                self._error = str(e)[:200]
        return None

    def process(self, frame) -> list[dict]:
        """Return current detections for this frame (tracked between infers)."""
        if not self.available:
            return []
        self._frame_i += 1
        if (self._frame_i - 1) % self.every_n != 0:
            return self._last

        try:
            results = self._model.track(
                frame, persist=True, conf=self.conf, verbose=False,
                device=self._device, tracker=self._tracker)
        except Exception:
            # tracker unavailable → plain detection
            results = self._model(frame, conf=self.conf, verbose=False,
                                  device=self._device)

        boxes: list[dict] = []
        for r in results:
            if r.boxes is None:
                continue
            for box in r.boxes:
                cls = int(box.cls[0])
                boxes.append({
                    "xyxy": [float(v) for v in box.xyxy[0]],
                    "conf": float(box.conf[0]),
                    "cls": cls,
                    "name": self.names.get(cls, str(cls)),
                    "id": int(box.id[0]) if box.id is not None else -1,
                })
        self._last = boxes
        return boxes
