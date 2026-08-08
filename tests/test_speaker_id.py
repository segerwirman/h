"""Fase 30 — Jarvis mengenali suara Takeda.

Permintaan aslinya: *"saya ingin jarvis bisa mengenali suara saya seperti siri
dan hanya merespon suara saya ketika pertama kali booting."*

**Batas jujur, dinyatakan di muka.** Tidak ada model speaker di repo, dan
ECAPA/Resemblyzer berarti unduhan puluhan MB — keputusan Takeda, bukan
keputusan kode. Yang diuji di sini adalah sidik suara spektral memakai numpy
saja: ia memisahkan dua suara yang jelas berbeda pada mikrofon dan ruangan
yang sama, dan ia **tidak** setara pengenal suara neural.

**Yang uji-uji ini TIDAK buktikan.** Sinyal sintetis membuktikan pipa-nya:
determinisme, batas, penanganan sampah, dan bahwa penolakan terlihat. Ia tidak
membuktikan akurasi pada suara manusia — S-25 sudah mengajarkan itu dengan
mahal, ketika ambang 0.55 yang lahir dari nada empat harmonik menolak 262 blok
suara Takeda yang sungguhan. Akurasinya menunggu suara Takeda di mikrofon
Takeda, dan sampai itu ada, gerbangnya MATI.
"""
from __future__ import annotations

import numpy as np
import pytest

from jarvis.core import speaker_id


SR = 16_000


def _voice(f0: float, seconds: float = 1.0, formants=(1.0, 0.5, 0.3),
           noise: float = 0.01, seed: int = 0) -> np.ndarray:
    """Suara tiruan: harmonik f0 dengan selubung formant + sedikit derau.

    Cukup untuk membedakan dua "penutur" sintetis, dan sengaja TIDAK diklaim
    mewakili suara manusia.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(int(SR * seconds)) / SR
    signal = np.zeros_like(t)
    for index, gain in enumerate(formants, start=1):
        signal += gain * np.sin(2 * np.pi * f0 * index * t)
    signal += noise * rng.standard_normal(t.size)
    return (signal / (np.max(np.abs(signal)) + 1e-9)).astype(np.float32)


# ── sidik suara ───────────────────────────────────────────────────────────

def test_a_fingerprint_is_deterministic():
    audio = _voice(120.0)

    assert speaker_id.fingerprint(audio, SR) == speaker_id.fingerprint(audio, SR)


def test_a_fingerprint_has_the_declared_size():
    assert len(speaker_id.fingerprint(_voice(120.0), SR)) == speaker_id.DIM


def test_two_takes_of_one_voice_are_close():
    first = speaker_id.fingerprint(_voice(120.0, seed=1), SR)
    second = speaker_id.fingerprint(_voice(120.0, seed=2), SR)

    assert speaker_id.similarity(first, second) > 0.9


def test_two_clearly_different_voices_are_apart():
    low = speaker_id.fingerprint(_voice(95.0, formants=(1.0, 0.6, 0.2)), SR)
    high = speaker_id.fingerprint(_voice(210.0, formants=(0.4, 1.0, 0.8)), SR)

    assert speaker_id.similarity(low, high) < 0.8


def test_silence_produces_no_fingerprint():
    """Diam bukan suara siapa pun. Menyidiknya berarti mencocokkan derau."""
    assert speaker_id.fingerprint(np.zeros(SR, dtype=np.float32), SR) == []


def test_a_clip_too_short_produces_no_fingerprint():
    tiny = _voice(120.0, seconds=0.05)

    assert speaker_id.fingerprint(tiny, SR) == []


def test_fingerprint_never_raises_on_junk():
    for value in (None, 12, "bukan audio", np.array([]), object()):
        assert speaker_id.fingerprint(value, SR) == []


def test_similarity_of_empty_fingerprints_is_zero():
    assert speaker_id.similarity([], []) == 0.0


def test_loudness_alone_does_not_change_who_is_speaking():
    """Bicara lebih keras bukan berarti menjadi orang lain."""
    quiet = _voice(120.0) * 0.2
    loud = _voice(120.0) * 0.9

    assert speaker_id.similarity(speaker_id.fingerprint(quiet, SR),
                                 speaker_id.fingerprint(loud, SR)) > 0.95


# ── profil: pendaftaran & penyimpanan ─────────────────────────────────────

@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(speaker_id, "_profile_path",
                        lambda: tmp_path / "speaker.json")
    speaker_id.forget()
    return speaker_id


def test_nobody_is_enrolled_at_first_boot(profile):
    assert profile.enrolled() is False
    assert profile.verify(_voice(120.0), SR).status == "not_enrolled"


def test_enrolment_needs_several_samples(profile):
    """Satu potong audio tidak cukup untuk mewakili suara seseorang."""
    assert profile.enroll([_voice(120.0, seed=1)], SR) is False
    assert profile.enrolled() is False


def test_an_enrolled_voice_is_recognised(profile):
    samples = [_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)]
    assert profile.enroll(samples, SR) is True

    result = profile.verify(_voice(120.0, seed=99), SR)

    assert result.status == "match"
    assert result.score > 0.0


def test_a_different_voice_scores_lower_than_the_owner(profile):
    samples = [_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)]
    profile.enroll(samples, SR)

    owner = profile.verify(_voice(120.0, seed=99), SR)
    stranger = profile.verify(_voice(210.0, formants=(0.4, 1.0, 0.8)), SR)

    assert stranger.score < owner.score


def test_the_profile_survives_a_restart(profile, tmp_path, monkeypatch):
    samples = [_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)]
    profile.enroll(samples, SR)

    speaker_id._cached = None                 # seolah proses baru
    assert profile.enrolled() is True
    assert profile.verify(_voice(120.0, seed=7), SR).status == "match"


def test_forgetting_returns_to_the_unenrolled_state(profile):
    profile.enroll([_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)], SR)
    profile.forget()

    assert profile.enrolled() is False


def test_a_corrupt_profile_is_treated_as_unenrolled(profile, tmp_path):
    (tmp_path / "speaker.json").write_text("{ bukan json", encoding="utf-8")
    speaker_id._cached = None

    assert profile.enrolled() is False


# ── gerbangnya MATI sampai Takeda menyalakannya ───────────────────────────

def test_gating_is_off_by_default(profile):
    """Verifikasi yang keliru membuat Jarvis TULI terhadap pemiliknya.

    Itu jauh lebih buruk daripada menjawab orang lain sesekali, jadi fase ini
    mengamati dulu dan menolak belakangan — setelah angkanya terlihat.
    """
    assert profile.gating_enabled() is False


def test_observation_never_blocks_anyone(profile):
    profile.enroll([_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)], SR)

    stranger = profile.verify(_voice(210.0, formants=(0.4, 1.0, 0.8)), SR)

    assert stranger.blocked is False, "mengamati tidak boleh menolak"


def test_a_stranger_is_blocked_only_once_gating_is_on(profile, monkeypatch):
    profile.enroll([_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)], SR)
    monkeypatch.setattr(profile.config, "get",
                        lambda path, default=None:
                        True if "speaker_id.gate" in path else default)

    stranger = profile.verify(_voice(210.0, formants=(0.4, 1.0, 0.8)), SR)

    assert stranger.status == "stranger"
    assert stranger.blocked is True


def test_the_owner_is_never_blocked_even_with_gating_on(profile, monkeypatch):
    profile.enroll([_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)], SR)
    monkeypatch.setattr(profile.config, "get",
                        lambda path, default=None:
                        True if "speaker_id.gate" in path else default)

    assert profile.verify(_voice(120.0, seed=99), SR).blocked is False


def test_an_unusable_clip_is_never_blocked_even_with_gating_on(profile,
                                                               monkeypatch):
    """Audio yang tidak bisa dinilai bukan bukti bahwa itu orang lain.

    Menolaknya berarti Jarvis membisu setiap kali mikrofonnya sedang buruk.
    """
    profile.enroll([_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)], SR)
    monkeypatch.setattr(profile.config, "get",
                        lambda path, default=None:
                        True if "speaker_id.gate" in path else default)

    result = profile.verify(np.zeros(SR, dtype=np.float32), SR)

    assert result.status == "unusable"
    assert result.blocked is False


def test_a_rejection_is_always_visible(profile, monkeypatch, caplog):
    """Perintah yang diabaikan diam-diam adalah kelas bug yang tujuh fase
    dihabiskan untuk memberantasnya.
    """
    import json

    profile.enroll([_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)], SR)
    monkeypatch.setattr(profile.config, "get",
                        lambda path, default=None:
                        True if "speaker_id.gate" in path else default)

    with caplog.at_level("INFO"):
        profile.verify(_voice(210.0, formants=(0.4, 1.0, 0.8)), SR)

    events = []
    for record in caplog.records:
        try:
            events.append(json.loads(record.getMessage()))
        except (ValueError, TypeError):
            continue
    blocked = [event for event in events
               if event.get("event") == "speaker_id.blocked"]
    assert blocked, "penolakan tidak terlihat di mana pun"
    assert "score" in blocked[-1]


def test_every_verdict_is_measurable(profile):
    """Ambangnya harus lahir dari angka Takeda, bukan dari nada sintetis."""
    profile.enroll([_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)], SR)

    result = profile.verify(_voice(120.0, seed=5), SR)

    assert 0.0 <= result.score <= 1.0
    assert result.threshold > 0.0
    assert result.status in {"match", "stranger", "unusable", "not_enrolled"}


# ── ambang lahir dari suara PEMILIK, bukan dari angka bawaan ──────────────

def test_enrolment_calibrates_the_threshold_from_the_owners_own_spread(profile):
    """S-25 diterapkan: angka bawaan tidak tahu apa-apa tentang mikrofon ini."""
    samples = [_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)]
    profile.enroll(samples, SR)

    import json

    stored = json.loads(profile._profile_path().read_text(encoding="utf-8"))
    assert stored["threshold"] > 0.0
    assert profile.threshold() == stored["threshold"]


def test_the_owner_stays_above_the_calibrated_threshold(profile):
    samples = [_voice(120.0, seed=n) for n in range(6)]
    profile.enroll(samples, SR)

    for seed in (91, 92, 93):
        assert profile.verify(_voice(120.0, seed=seed), SR).status == "match"


def test_calibration_rejects_a_stranger_a_fixed_threshold_would_accept(profile):
    """Ini bug yang ditemukan pengukuran, bukan skenario karangan.

    Pada suara sintetis, penutur "rendah" mencetak 0.903 — LOLOS ambang tetap
    0.82. Kalibrasi dari sebaran pemilik sendirilah yang menangkapnya.
    """
    samples = [_voice(120.0, seed=n) for n in range(6)]
    profile.enroll(samples, SR)

    stranger = _voice(95.0, formants=(1.0, 0.6, 0.2), seed=3)
    result = profile.verify(stranger, SR)

    assert result.score > profile.DEFAULT_THRESHOLD, "premis ujinya berubah"
    assert result.status == "stranger"


def test_an_explicit_setting_still_wins_over_calibration(profile, monkeypatch):
    profile.enroll([_voice(120.0, seed=n) for n in range(6)], SR)
    monkeypatch.setattr(profile.config, "get",
                        lambda path, default=None:
                        0.5 if "speaker_id.threshold" in path else default)

    assert profile.threshold() == 0.5


def test_diagnostics_expose_the_numbers(profile):
    """Sunyi bukan bukti — Takeda harus bisa melihat angkanya sendiri."""
    profile.enroll([_voice(120.0, seed=n) for n in range(profile.MIN_SAMPLES)], SR)

    report = profile.diagnostics()

    assert report["enrolled"] is True
    assert report["samples"] >= profile.MIN_SAMPLES
    assert report["threshold"] > 0.0
    assert report["gating"] is False


# ── terpasang di jalur mic yang sungguhan ─────────────────────────────────

def test_the_listener_ignores_audio_while_jarvis_is_not_listening(profile):
    """Mic meter berjalan terus; hanya ucapan ke Jarvis yang dinilai."""
    listener = speaker_id.Listener(SR)
    block = _voice(120.0, seconds=0.064)

    for _ in range(40):
        assert listener.feed(block, listening=False) is None


def test_the_listener_needs_a_whole_utterance_not_one_block(profile):
    """Satu blok 64 ms tidak cukup untuk mengenali siapa pun."""
    listener = speaker_id.Listener(SR)

    assert listener.feed(_voice(120.0, seconds=0.064), listening=True) is None


def test_the_listener_enrols_the_first_voice_it_hears(profile):
    """"...ketika pertama kali booting" — pemilik itu yang bicara duluan."""
    listener = speaker_id.Listener(SR)

    for take in range(profile.MIN_SAMPLES):
        _speak(listener, _voice(120.0, seed=take))

    assert profile.enrolled() is True


def test_once_enrolled_the_listener_reports_a_verdict(profile):
    listener = speaker_id.Listener(SR)
    for take in range(profile.MIN_SAMPLES):
        _speak(listener, _voice(120.0, seed=take))

    verdict = _speak(listener, _voice(120.0, seed=50))

    assert verdict is not None
    assert verdict.status == "match"


def test_silence_between_utterances_does_not_merge_two_speakers(profile):
    """Buffer yang tidak pernah dikosongkan akan mencampur dua orang."""
    listener = speaker_id.Listener(SR)
    _speak(listener, _voice(120.0, seed=1))
    for _ in range(20):                       # jeda sunyi
        listener.feed(np.zeros(1024, dtype=np.float32), listening=True)

    assert listener.buffered_seconds() == 0.0


def test_the_listener_buffer_is_bounded(profile):
    """Orang yang bicara sangat panjang tidak boleh memakan memori."""
    listener = speaker_id.Listener(SR)
    block = _voice(120.0, seconds=0.064)

    for _ in range(2000):
        listener.feed(block, listening=True)

    assert listener.buffered_seconds() <= speaker_id.MAX_UTTERANCE_SECONDS


def test_the_listener_never_raises_on_junk(profile):
    listener = speaker_id.Listener(SR)

    for value in (None, "bukan audio", np.array([]), object()):
        assert listener.feed(value, listening=True) is None


def test_the_mic_loop_actually_feeds_the_listener():
    """Modul yang tidak pernah dipanggil tidak mengenali siapa pun."""
    import inspect

    from jarvis.ui import window

    source = inspect.getsource(window.JarvisUI._mic_meter)
    assert "speaker" in source.lower()


def _speak(listener, audio, block=1024):
    """Suapkan satu ucapan blok demi blok, seperti `sd.InputStream`.

    Diakhiri blok sunyi karena begitulah ucapan sungguhan berakhir — dan
    justru sunyi itulah yang menutup ucapannya.
    """
    verdict = None
    for start in range(0, len(audio) - block, block):
        result = listener.feed(audio[start:start + block], listening=True)
        verdict = result or verdict
    for _ in range(speaker_id.SILENCE_BLOCKS_TO_CLOSE + 1):
        result = listener.feed(np.zeros(block, dtype=np.float32), listening=True)
        verdict = result or verdict
    return verdict
