"""Fase 14 visual service privacy contract, tanpa tool exposure."""
from __future__ import annotations

def test_visual_service_blocks_denylisted_window_before_pixel_capture():
    from jarvis.automation.visual_observe import VisualObserveService

    calls = []
    service = VisualObserveService(
        foreground=lambda: ("My Password Vault", "Vault"),
        capture=lambda: calls.append("capture"),
        denylisted=lambda *_: True,
    )

    report = service.observe(session_id="visual-a")

    assert report is None
    assert calls == []

def test_visual_service_never_persists_image_or_exposes_pixels_or_ocr():
    import numpy as np
    from PIL import Image
    from jarvis.automation.visual_observe import VisualObserveService

    service = VisualObserveService(
        foreground=lambda: ("Demo", "Demo"),
        capture=lambda: Image.fromarray(np.full((20, 30, 3), 128, dtype=np.uint8), "RGB"),
        denylisted=lambda *_: False,
    )

    report = service.observe(session_id="visual-a")

    assert set(report) == {"visual_observation_id", "brightness", "complexity", "dominant_tone"}
    assert report["brightness"] in {"dark", "balanced", "bright"}
    assert report["complexity"] in {"low", "medium", "high"}
    assert report["dominant_tone"] in {"warm", "neutral", "cool"}
    assert not hasattr(service, "history")
    assert not hasattr(service, "last_image")
