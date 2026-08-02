"""Static disposable acceptance fixtures for Phase 14.5 visual-read-only lane.

This script never captures the user's desktop. It injects a generated image or
controlled denied/unavailable capture seam into the real VisualObserveService.
Its final output is status-only and contains no title, app, pixels, OCR, path,
or native exception.
"""
from __future__ import annotations

import sys


def _safe_frame():
    import numpy as np
    from PIL import Image
    return Image.fromarray(np.full((16, 24, 3), 128, dtype=np.uint8), "RGB")


def run_fixture(name: str) -> dict:
    from jarvis.automation.visual_observe import VisualObserveService

    normalized = str(name or "").strip()
    calls: list[str] = []
    if normalized == "safe_frame":
        service = VisualObserveService(
            foreground=lambda: ("Fixture", "Fixture"),
            capture=lambda: calls.append("capture") or _safe_frame(),
            denylisted=lambda *_: False,
        )
        report = service.observe(session_id="visual-soak")
        accepted = bool(report and set(report) == {
            "visual_observation_id", "brightness", "complexity", "dominant_tone",
        } and calls == ["capture"])
    elif normalized == "denylisted":
        service = VisualObserveService(
            foreground=lambda: ("Sensitive", "Sensitive"),
            capture=lambda: calls.append("capture") or _safe_frame(),
            denylisted=lambda *_: True,
        )
        report = service.observe(session_id="visual-soak")
        accepted = report is None and calls == []
    elif normalized == "capture_unavailable":
        service = VisualObserveService(
            foreground=lambda: ("Fixture", "Fixture"),
            capture=lambda: calls.append("capture") or None,
            denylisted=lambda *_: False,
        )
        report = service.observe(session_id="visual-soak")
        accepted = report is None and calls == ["capture"]
    else:
        accepted = False
    return {"accepted": accepted, "verified": accepted}


def main() -> int:
    result = run_fixture(sys.argv[1] if len(sys.argv) == 2 else "")
    print(result)
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
