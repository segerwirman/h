"""In-memory, privacy-first visual summary with no OCR, persistence, or actions."""
from __future__ import annotations

import uuid

from jarvis.core.privacy_denylist import is_denylisted


class VisualObserveService:
    """Capture one desktop frame only after privacy gate; return coarse categories."""

    def __init__(self, *, foreground=None, capture=None, denylisted=None):
        self._foreground = foreground or _foreground_window
        self._capture = capture or _grab
        self._denylisted = denylisted or is_denylisted

    def observe(self, *, session_id: str) -> dict | None:
        foreground = self._foreground()
        if foreground is None:
            return None  # foreground tidak dapat diidentifikasi — fail closed
        title, app = foreground
        title = str(title or "").strip()
        app = str(app or "").strip()
        if not title or not app:
            return None  # identitas foreground tidak cukup — tolak sebelum capture
        if self._denylisted(title, app):
            return None
        image = self._capture()
        if image is None:
            return None
        try:
            return _summarize(image)
        finally:
            # Do not retain an image reference, bytes, path, or OCR output.
            del image


def _foreground_window() -> tuple[str, str] | None:
    try:
        import pygetwindow as gw
        window = gw.getActiveWindow()
        title = str((window.title if window else "") or "")
    except Exception:
        return None
    app = title.split(" - ")[-1].strip() if " - " in title else title
    return title, app


def _grab():
    from PIL import ImageGrab
    return ImageGrab.grab()


def _summarize(image) -> dict:
    import numpy as np

    pixels = np.asarray(image.convert("RGB"), dtype=np.float32)
    if pixels.size == 0:
        raise RuntimeError("visual_frame_empty")
    mean = float(pixels.mean())
    spread = float(pixels.std())
    channels = pixels.reshape(-1, 3).mean(axis=0)
    brightness = "dark" if mean < 85 else "bright" if mean > 170 else "balanced"
    complexity = "low" if spread < 30 else "high" if spread > 75 else "medium"
    red_blue = float(channels[0] - channels[2])
    dominant_tone = "warm" if red_blue > 15 else "cool" if red_blue < -15 else "neutral"
    return {
        "visual_observation_id": uuid.uuid4().hex,
        "brightness": brightness,
        "complexity": complexity,
        "dominant_tone": dominant_tone,
    }


__all__ = ["VisualObserveService"]
