"""Thin Telegram voice-note bridge to the frozen Jarvis STT implementation.

This module only decodes Telegram's OGG/Opus container to the mono 16 kHz
float samples already expected by ``core.stt.WhisperSTT``.  It deliberately
does not duplicate or modify the speech recognizer.
"""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np

_lock = threading.Lock()
_stt = None


class VoiceNoteError(RuntimeError):
    """Safe, user-facing failure raised by the optional voice bridge."""


def transcribe(path: str | Path) -> str:
    audio = _decode_ogg(path)
    recognizer = _recognizer()
    try:
        return str(recognizer.transcribe(audio) or "").strip()
    except Exception as exc:  # noqa: BLE001
        raise VoiceNoteError(
            f"STT Jarvis gagal memproses voice note ({type(exc).__name__})."
        ) from None


def _recognizer():
    global _stt
    with _lock:
        if _stt is not None:
            return _stt
        try:
            # FROZEN: diimpor dan dibungkus; implementasinya tidak diubah.
            from core.stt import WhisperSTT
            _stt = WhisperSTT(model_name="base")
        except Exception as exc:  # noqa: BLE001
            raise VoiceNoteError(
                f"STT Jarvis tidak tersedia ({type(exc).__name__})."
            ) from None
        return _stt


def _decode_ogg(path: str | Path) -> np.ndarray:
    try:
        import av
    except ImportError:
        raise VoiceNoteError(
            "Decoder voice note belum tersedia (pasang dependency av)."
        ) from None

    samples: list[np.ndarray] = []
    try:
        with av.open(str(path), mode="r") as container:
            resampler = av.AudioResampler(format="flt", layout="mono",
                                          rate=16_000)
            for frame in container.decode(audio=0):
                for converted in resampler.resample(frame):
                    samples.append(np.asarray(
                        converted.to_ndarray(), dtype=np.float32).reshape(-1))
            for converted in resampler.resample(None):
                samples.append(np.asarray(
                    converted.to_ndarray(), dtype=np.float32).reshape(-1))
    except VoiceNoteError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise VoiceNoteError(
            f"Voice note tidak dapat didekode ({type(exc).__name__})."
        ) from None
    if not samples:
        raise VoiceNoteError("Voice note tidak berisi audio yang dapat dibaca.")
    return np.ascontiguousarray(np.concatenate(samples), dtype=np.float32)
