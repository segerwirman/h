"""In-memory, privacy-first visual summary with no OCR, persistence, or actions."""
from __future__ import annotations

import uuid
from contextlib import ExitStack, nullcontext

from jarvis.core.privacy_denylist import is_denylisted


class VisualObserveService:
    """Capture one desktop frame only after privacy gate; return coarse categories."""

    def __init__(self, *, foreground=None, capture=None, denylisted=None,
                 capture_pause=None):
        self._foreground = foreground or _foreground_window
        self._capture = capture or _grab
        self._denylisted = denylisted or is_denylisted
        self._capture_pause = capture_pause or _screen_control_capture_pause

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
        # Dua kegagalan berbeda, dua perlakuan berbeda. Jangan disatukan.
        #
        # 1. ``capture_pause`` GAGAL — artinya overlay kursor tidak bisa
        #    disembunyikan (``screen_control.py:169`` sengaja melempar
        #    ``screen_control_capture_exclusion_unavailable``). Mengambil citra
        #    dalam keadaan itu berarti merekam overlay kita sendiri, jadi
        #    fail-closed di sini: ``None``, tanpa menyentuh kamera layar.
        # 2. ``capture`` GAGAL — pause sudah aktif dan aman, dan batas
        #    fail-closed yang sesungguhnya ada di alat:
        #    ``desktop_visual_observe.py:62-65`` meneruskan exception ke
        #    ``ToolResult.fail("desktop_visual_failed")``. Menelan exception di
        #    sini membuat kegagalan capture tak bisa dibedakan dari
        #    "foreground tidak dikenal" (baris 23).
        # ``capture_pause`` adalah ``@contextmanager``, jadi kegagalannya baru
        # terjadi saat ``__enter__`` — bukan saat dipanggil. Karena itu ``try``
        # harus membungkus masuknya context, dan capture diletakkan DI LUARnya
        # supaya kegagalan kamera layar tetap merambat.
        pause = self._capture_pause()
        stack = ExitStack()
        try:
            # Masuknya context dikelola sendiri: bila pause gagal, citra TIDAK
            # diambil — overlay yang tak bisa disembunyikan akan ikut terekam.
            stack.enter_context(pause)
        except Exception:                                    # noqa: BLE001
            return None
        with stack:
            # Kegagalan kamera layar dibiarkan merambat ke alat.
            image = self._capture()
        if image is None:
            return None
        try:
            return _summarize(image)
        finally:
            # Do not retain an image reference, bytes, path, or OCR output.
            del image


def _screen_control_capture_pause():
    try:
        from jarvis.ui.screen_control import COORDINATOR
        return COORDINATOR.capture_pause()
    except Exception:
        return nullcontext()


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
