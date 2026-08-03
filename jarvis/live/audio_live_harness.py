"""WA3-live — audio live acceptance harness.

Harness live acceptance dua arah via virtual cable (VB-Audio):
enumerasi device loopback, pemilihan pasangan CABLE, tone loopback
(sine → playback device → capture device → RMS), dan wiring
CallAudioProof dengan capture/playback NYATA. Tanpa hardware di CI —
sounddevice di-fake di test; `audio_exercised` jujur False saat device
tidak tersedia. STT/TTS/voice_listener FROZEN tidak disentuh. Tanpa
provider/network/file write.
"""
from __future__ import annotations

import numpy as np
import sounddevice as sd

SAMPLE_RATE = 48000
RMS_THRESHOLD = 0.01


def _usable_devices(devices: list[dict]) -> list[dict]:
    """Device yang punya channel input ATAU output."""
    return [d for d in devices
            if d.get("max_input_channels", 0) > 0
            or d.get("max_output_channels", 0) > 0]


def enumerate_devices() -> list[dict]:
    """Metadata device audio (nama/index/channel) — tanpa path/raw."""
    devices = []
    for index, info in enumerate(sd.query_devices()):
        devices.append({
            "name": str(info["name"]),
            "index": index,
            "max_input_channels": int(info["max_input_channels"]),
            "max_output_channels": int(info["max_output_channels"]),
        })
    return devices


def find_loopback_pair(devices: list[dict] | None = None) -> dict | None:
    """Pasangan CABLE: capture (output cable, punya input) + playback
    (input cable, punya output). Tanpa cable → None (jujur)."""
    if devices is None:
        devices = enumerate_devices()
    usable = _usable_devices(devices)
    captures = [d for d in usable if "CABLE" in d["name"]
                and d["max_input_channels"] > 0]
    playbacks = [d for d in usable if "CABLE" in d["name"]
                 and d["max_output_channels"] > 0]
    if not captures or not playbacks:
        return None
    return {"capture": captures[0], "playback": playbacks[0]}


def rms_of(samples: np.ndarray) -> float:
    """RMS (root mean square) — 0.0 untuk diam."""
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float32)))))


def tone_loopback(capture_index: int, playback_index: int,
                  duration_s: int = 3, freq_hz: int = 440) -> dict:
    """Tone sine → playback device; capture dari input device; hitung RMS.

    Bukti loopback end-to-end NYATA: energi tone tertangkap di sisi
    capture. Metadata-only hasil (tanpa audio/path/raw).
    """
    if sd is None:
        return {"ok": False, "reason": "sounddevice_unavailable",
                "audio_exercised": False}
    n = int(SAMPLE_RATE * max(1, duration_s))
    t = np.arange(n, dtype=np.float32) / SAMPLE_RATE
    tone = (0.5 * np.sin(2 * np.pi * freq_hz * t)).astype(np.float32)
    try:
        recorded = sd.playrec(tone, samplerate=SAMPLE_RATE, channels=1,
                              device=(capture_index, playback_index),
                              dtype="float32")
        sd.wait()
    except Exception:  # noqa: BLE001
        return {"ok": False, "reason": "loopback_failed",
                "audio_exercised": True}
    rms = rms_of(np.asarray(recorded).reshape(-1))
    return {
        "ok": rms >= RMS_THRESHOLD,
        "reason": None if rms >= RMS_THRESHOLD else "loopback_silent",
        "rms": rms,
        "samples": int(len(recorded)),
        "duration_s": int(max(1, duration_s)),
        "audio_exercised": True,
    }


def live_proof(session: object, duration_s: int = 3) -> dict:
    """Wire capture/playback NYATA ke CallAudioProof (WA3).

    Tanpa sounddevice/device → `audio_exercised` jujur False.
    """
    from jarvis.core.call_audio import CallAudioProof

    pair = find_loopback_pair() if sd is not None else None
    if pair is None:
        proof = CallAudioProof()
        if not proof.start(session, duration_s):
            return {"ok": False, "status": proof.status(),
                    "audio_exercised": False}
        proof.stop()
        return proof.result()

    def _capture(duration: int) -> int:
        result = tone_loopback(pair["capture"]["index"],
                               pair["playback"]["index"],
                               duration_s=duration)
        return result["samples"] if result.get("ok") else 0

    def _playback(duration: int) -> bool:
        result = tone_loopback(pair["capture"]["index"],
                               pair["playback"]["index"],
                               duration_s=duration)
        return bool(result.get("ok"))

    proof = CallAudioProof(capture=_capture, playback=_playback)
    if not proof.start(session, duration_s):
        return {"ok": False, "status": proof.status(),
                "audio_exercised": False}
    proof.stop()
    return proof.result()


__all__ = ["enumerate_devices", "find_loopback_pair", "rms_of",
           "tone_loopback", "live_proof", "SAMPLE_RATE", "RMS_THRESHOLD"]
