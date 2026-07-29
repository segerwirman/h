"""Observe Gemini Live turns that contain text but no PCM audio.

This is diagnostic-only.  The frozen receive loop keeps its legacy behaviour
unless it explicitly calls ``VOICE_TEXT_ONLY_HOOK`` and this installer is
enabled in config.
"""
from __future__ import annotations

from jarvis.core import config, log

_logger = log.get("voice.text_only")


def install(legacy_module) -> bool:
    """Install a fail-open diagnostic hook when explicitly enabled."""
    if not config.get("voice.text_only_observer.enabled", False):
        return False
    existing = getattr(legacy_module, "VOICE_TEXT_ONLY_HOOK", None)
    if getattr(existing, "_jarvis_text_only_observer", False):
        return True

    async def observe(live, text: str, *, had_audio: bool) -> None:
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

    observe._jarvis_text_only_observer = True
    legacy_module.VOICE_TEXT_ONLY_HOOK = observe
    _logger.info("voice.text_only_observer.installed")
    return True
