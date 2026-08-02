"""A50: visual observe must fail closed when foreground cannot be identified.

Regression: _foreground_window returned ("","") on failure, which bypassed the
denylist and still captured a screenshot. Contract: unknown or empty foreground
identity rejects BEFORE any pixel capture.
"""
from jarvis.automation.visual_observe import VisualObserveService


def test_observe_rejects_unknown_foreground_before_capture():
    calls = []

    service = VisualObserveService(
        foreground=lambda: None,
        capture=lambda: calls.append("CAPTURE"),
        denylisted=lambda title, app: False,
    )
    result = service.observe(session_id="desktop-a")
    assert result is None
    assert calls == [], "capture tidak boleh dipanggil tanpa identitas foreground"


def test_observe_rejects_empty_foreground_before_capture():
    calls = []

    service = VisualObserveService(
        foreground=lambda: ("", ""),
        capture=lambda: calls.append("CAPTURE"),
        denylisted=lambda title, app: False,
    )
    result = service.observe(session_id="desktop-a")
    assert result is None
    assert calls == [], "capture tidak boleh dipanggil dengan foreground kosong"


def test_observe_still_captures_when_foreground_known_and_allowed():
    calls = []

    class _Image:
        def convert(self, _mode):
            import numpy as np
            return np.zeros((2, 2, 3), dtype=np.uint8)

    service = VisualObserveService(
        foreground=lambda: ("JARVIS", "JARVIS"),
        capture=lambda: (calls.append("CAPTURE") or _Image()),
        denylisted=lambda title, app: False,
    )
    result = service.observe(session_id="desktop-a")
    assert result is not None
    assert calls == ["CAPTURE"]
    assert set(result) == {"visual_observation_id", "brightness", "complexity", "dominant_tone"}
