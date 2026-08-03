"""WA3-live RED — audio live harness logic (offline, fake sounddevice).

Logic harness live acceptance: enumerasi loopback device, pemilihan
pasangan cable, perhitungan RMS, tone loopback, wiring CallAudioProof
dengan capture/playback nyata. Tanpa hardware di CI — sounddevice
di-fake; tanpa provider/network/file write.
"""
from __future__ import annotations


def _fake_devices():
    return [
        {"name": "CABLE Output (VB-Audio Virtual Cable)", "index": 1,
         "max_input_channels": 2, "max_output_channels": 0},
        {"name": "CABLE Input (VB-Audio Virtual Cable)", "index": 2,
         "max_input_channels": 0, "max_output_channels": 2},
        {"name": "CABLE Output (VB-Audio Hi-Fi Cable)", "index": 3,
         "max_input_channels": 2, "max_output_channels": 0},
        {"name": "CABLE Input (VB-Audio Hi-Fi Cable)", "index": 4,
         "max_input_channels": 0, "max_output_channels": 2},
        {"name": "Speakers (Realtek)", "index": 5,
         "max_input_channels": 0, "max_output_channels": 2},
        {"name": "Mic (Realtek)", "index": 6,
         "max_input_channels": 2, "max_output_channels": 0},
    ]


def test_enumerate_filters_usable_devices():
    import jarvis.live.audio_live_harness as ah

    usable = ah._usable_devices(_fake_devices())
    assert len(usable) == 6                 # semua device berchannel (4 cable + 2 lainnya)
    assert all(d["max_input_channels"] > 0 or d["max_output_channels"] > 0
               for d in usable)


def test_find_loopback_pair():
    import jarvis.live.audio_live_harness as ah

    pair = ah.find_loopback_pair(devices=_fake_devices())
    assert pair is not None
    assert "VB-Audio Virtual Cable" in pair["capture"]["name"] or \
        "VB-Audio Hi-Fi Cable" in pair["capture"]["name"]
    assert pair["capture"]["max_input_channels"] > 0
    assert pair["playback"]["max_output_channels"] > 0
    # Tanpa cable → None (jujur)
    no_cable = [d for d in _fake_devices() if "CABLE" not in d["name"]]
    assert ah.find_loopback_pair(devices=no_cable) is None


def test_rms_of_samples():
    import numpy as np
    import jarvis.live.audio_live_harness as ah

    silence = np.zeros(8000, dtype=np.float32)
    assert ah.rms_of(silence) == 0.0
    tone = (0.5 * np.sin(2 * np.pi * 440 * np.arange(8000) / 8000)
            ).astype(np.float32)
    assert ah.rms_of(tone) > 0.1


def test_tone_loopback_uses_sounddevice(monkeypatch):
    import numpy as np
    import jarvis.live.audio_live_harness as ah

    calls = {}

    class FakeSD:
        @staticmethod
        def playrec(data, samplerate, channels, device, dtype):
            calls["data"] = data
            calls["samplerate"] = samplerate
            calls["channels"] = channels
            calls["device"] = device
            return data.reshape(-1, 1)      # tone ter-loopback (RMS tinggi)

        @staticmethod
        def wait():
            return None

    monkeypatch.setattr(ah, "sd", FakeSD)
    result = ah.tone_loopback(capture_index=1, playback_index=2,
                              duration_s=2, freq_hz=440)
    assert result["ok"] is True
    assert result["audio_exercised"] is True
    assert calls["device"] == (1, 2)        # (input=capture, output=playback)


def test_live_proof_wires_call_audio(monkeypatch):
    import numpy as np
    import jarvis.live.audio_live_harness as ah

    monkeypatch.setattr(ah, "sd", None)     # tanpanya → jujur exercised False
    from jarvis.core.call_session import CallSession
    session = CallSession()
    session.start("Toko", "cek audio", 300)
    session.approve()
    result = ah.live_proof(session, duration_s=2)
    assert result["status"] == "done"
    assert result["audio_exercised"] is False   # jujur tanpa hardware


def test_harness_no_live_authority_via_static_contract():
    from pathlib import Path

    source = Path("jarvis/live/audio_live_harness.py").read_text(
        encoding="utf-8")
    for forbidden in ("import whatsapp", "requests", "socket", "http",
                      "subprocess", "selenium", "playwright", "write_bytes",
                      "open("):
        assert forbidden not in source, forbidden
