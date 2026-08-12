"""Observe Gemini Live turns that contain text but no PCM audio.

This is diagnostic-only. The frozen receive loop calls :func:`observe`
directly at its turn boundary; the function is a true no-op unless explicitly
enabled in config.
"""
from __future__ import annotations

from jarvis.core import config, log

_logger = log.get("voice.text_only")


async def observe(live, text: str, *, had_audio: bool) -> None:
    """Report text-only output when enabled without affecting voice delivery."""
    if not config.get("voice.text_only_observer.enabled", False):
        return
    if had_audio:
        return
    message = " ".join(str(text or "").split())
    if not message:
        return
    request_id = str(getattr(live, "_turn_id", "") or "")
    _logger.warning(
        "voice.text_only_output",
        request_id=request_id,
        text_chars=len(message),
    )
    try:
        live.ui.write_log(
            "SYS: Respons Gemini diterima tanpa audio; teks tetap ditampilkan."
        )
    except Exception:  # noqa: BLE001 - observation must never break voice
        pass


__all__ = ["observe"]
