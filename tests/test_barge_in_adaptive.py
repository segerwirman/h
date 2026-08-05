"""Fase 19 — barge-in adaptif yang tahan noise (S-4).

Dua permintaan Takeda adalah SATU pekerjaan: "bisa diinterupsi natural" dan
"tidak terlalu sensitif pada noise". Menyalakan detektor lama apa adanya
menghasilkan persis kepekaan yang ditolak, karena ia gerbang RMS ambang TETAP
(0.14) tanpa noise floor adaptif, tanpa pembeda suara-vs-bunyi, dan dengan echo
guard yang hanya menutup 400 ms pertama.

Preseden yang dipakai ulang ada di repo ini sendiri: detektor tepuk
(`jarvis/core/wake.py`, FROZEN — dibaca, tidak disentuh) sudah memakai
kalibrasi + EMA noise floor, crest factor, dan rasio spektral.

Kuncinya: barge-in adalah KEBALIKAN deteksi tepuk. Tepukan = transien pendek,
crest TINGGI, broadband. Suara manusia = berkelanjutan, crest RENDAH, energi
terkonsentrasi di pita suara. Primitif sama, ambang dibalik.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from jarvis.core import barge_in

SR = 16000
BLOCK = 1024
BLOCK_S = BLOCK / SR


def _voice(level: float, n: int = BLOCK, f0: float = 180.0) -> np.ndarray:
    """Nada mirip suara: harmonik rendah, berkelanjutan, crest rendah."""
    t = np.arange(n) / SR
    wave = sum(math.pow(0.6, k) * np.sin(2 * math.pi * f0 * (k + 1) * t)
               for k in range(4))
    wave = wave / (np.max(np.abs(wave)) + 1e-9)
    return (wave * level * 32768).astype(np.int16)


def _hiss(level: float, n: int = BLOCK, seed: int = 0) -> np.ndarray:
    """Derau broadband berkelanjutan — AC, kipas, jalan raya."""
    rng = np.random.default_rng(seed)
    return (rng.normal(0, level, n).clip(-1, 1) * 32768).astype(np.int16)


def _clap(level: float, n: int = BLOCK) -> np.ndarray:
    """Transien pendek: crest tinggi, broadband. Pintu, tepukan, ketukan."""
    rng = np.random.default_rng(7)
    out = np.zeros(n)
    burst = 40
    out[:burst] = rng.normal(0, 1.0, burst)
    out = out / (np.max(np.abs(out)) + 1e-9)
    return (out * level * 32768).astype(np.int16)


def _analyzer(**overrides) -> barge_in.BargeInAnalyzer:
    cfg = barge_in.BargeInConfig(**{"enabled": True, **overrides})
    return barge_in.BargeInAnalyzer(cfg)


def _calibrate(analyzer, ambient, now=0.0, seconds=1.6):
    analyzer.start_calibration(now)
    steps = int(seconds / BLOCK_S) + 1
    for i in range(steps):
        analyzer.process_block(ambient, now + i * BLOCK_S, speaking=True)
    return now + steps * BLOCK_S


def _feed(analyzer, block, start, count, **kwargs):
    """Suapkan blok berturut-turut; kembalikan verdict pertama yang memotong."""
    now = start
    for _ in range(count):
        verdict = analyzer.process_block(block, now, **kwargs)
        if verdict.interrupt:
            return verdict, now
        now += BLOCK_S
    return None, now


# ── noise floor adaptif ───────────────────────────────────────────────────

def test_calibration_learns_the_room():
    analyzer = _analyzer()
    _calibrate(analyzer, _hiss(0.05))

    assert analyzer.noise_floor > 0.0
    assert analyzer.threshold() > analyzer.noise_floor


def test_room_noise_at_ambient_level_never_interrupts():
    """Ruangan berisik yang KONSISTEN tidak boleh memotong Jarvis."""
    analyzer = _analyzer()
    ambient = _hiss(0.18, seed=1)          # jauh di atas ambang tetap lama 0.14
    now = _calibrate(analyzer, ambient)

    hit, _ = _feed(analyzer, _hiss(0.18, seed=2), now, 60, speaking=True)
    assert hit is None, "ambang tetap lama akan memotong di sini"


def test_a_quiet_room_makes_the_detector_more_sensitive():
    """Ambang relatif terhadap ruangan, bukan angka mati."""
    loud = _analyzer()
    _calibrate(loud, _hiss(0.20, seed=3))
    quiet = _analyzer()
    _calibrate(quiet, _hiss(0.01, seed=4))

    assert quiet.threshold() < loud.threshold()


# ── pembeda suara vs bunyi ────────────────────────────────────────────────

def test_speech_like_sound_interrupts_quickly():
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=5))

    hit, at = _feed(analyzer, _voice(0.30), now, 40, speaking=True)

    assert hit is not None, "suara jelas di atas noise floor harus memotong"
    assert (at - now) < 0.6, f"terlalu lambat: {at - now:.2f}s"


def test_a_transient_bang_does_not_interrupt():
    """Pintu dan tepukan tidak boleh memotong — itu bukan orang bicara."""
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=6))

    hit, _ = _feed(analyzer, _clap(0.9), now, 40, speaking=True)
    assert hit is None


def test_broadband_hiss_above_the_floor_does_not_interrupt():
    """Derau keras mendadak (AC menyala) bukan ucapan."""
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=8))

    hit, _ = _feed(analyzer, _hiss(0.35, seed=9), now, 30, speaking=True)
    assert hit is None


# ── echo guard sepanjang ucapan ───────────────────────────────────────────

def test_echo_is_guarded_for_the_whole_utterance_not_just_the_onset():
    """Cacat yang membuat barge-in dimatikan sejak awal.

    Grace 400 ms hanya menutup awal ucapan. Echo speaker berlangsung SELAMA
    Jarvis bicara, jadi ambang harus naik sepanjang itu — sebanding dengan
    seberapa keras Jarvis sedang berbunyi.
    """
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=10))
    echo = _voice(0.30)

    # Jarvis MULAI bicara: jendela grace mengukur echo-nya (S-24).
    _feed(analyzer, echo, now, 5, speaking=True, speaking_since=now,
          playback_level=0.9)

    # Jauh setelah jendela grace, tetapi Jarvis masih bicara keras.
    hit, _ = _feed(analyzer, echo, now + 5.0, 40,
                   speaking=True, speaking_since=now, playback_level=0.9)
    assert hit is None, "echo speaker tidak boleh memotong Jarvis sendiri"


def test_the_user_still_wins_over_a_quiet_tts_tail():
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=11))

    hit, _ = _feed(analyzer, _voice(0.45), now + 5.0, 40,
                   speaking=True, playback_level=0.05)
    assert hit is not None


def test_onset_grace_still_applies():
    analyzer = _analyzer(tts_grace_ms=400)
    now = _calibrate(analyzer, _hiss(0.01, seed=12))

    hit, _ = _feed(analyzer, _voice(0.5), now, 3,
                   speaking=True, speaking_since=now, playback_level=0.2)
    assert hit is None


# ── ketahanan temporal ────────────────────────────────────────────────────

def test_one_loud_block_is_not_an_interruption():
    analyzer = _analyzer(min_ms=450)
    now = _calibrate(analyzer, _hiss(0.01, seed=13))

    verdict = analyzer.process_block(_voice(0.5), now, speaking=True)
    assert verdict.interrupt is False


def test_a_gap_resets_the_sustain_counter():
    """Ucapan harus BERTURUT-TURUT, bukan sekadar terkumpul."""
    analyzer = _analyzer(min_ms=450)
    now = _calibrate(analyzer, _hiss(0.01, seed=14))
    quiet = _hiss(0.01, seed=15)

    for _ in range(12):
        analyzer.process_block(_voice(0.4), now, speaking=True)
        now += BLOCK_S
        analyzer.process_block(quiet, now, speaking=True)   # jeda
        now += BLOCK_S
        assert analyzer.sustained_s == 0.0


def test_cooldown_prevents_a_second_interrupt_immediately():
    analyzer = _analyzer(cooldown_ms=2000)
    now = _calibrate(analyzer, _hiss(0.01, seed=16))

    hit, at = _feed(analyzer, _voice(0.4), now, 40, speaking=True)
    assert hit is not None

    again, _ = _feed(analyzer, _voice(0.4), at + BLOCK_S, 20, speaking=True)
    assert again is None


def test_only_interrupts_while_jarvis_is_speaking():
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=17))

    hit, _ = _feed(analyzer, _voice(0.5), now, 40, speaking=False)
    assert hit is None


# ── satu kenop ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("low,high", [("low", "medium"), ("medium", "high")])
def test_sensitivity_is_monotonic(low, high):
    """Satu kenop yang bisa diputar Takeda tanpa menyentuh lima angka mentah."""
    a = _analyzer(sensitivity=low)
    b = _analyzer(sensitivity=high)
    _calibrate(a, _hiss(0.02, seed=18))
    _calibrate(b, _hiss(0.02, seed=18))

    assert b.threshold() < a.threshold(), "high harus lebih peka daripada low"


def test_unknown_sensitivity_falls_back_to_medium():
    analyzer = _analyzer(sensitivity="sesuka-hati")
    assert analyzer.cfg.sensitivity == "medium"


# ── keamanan dasar ────────────────────────────────────────────────────────

def test_disabled_analyzer_never_interrupts():
    analyzer = _analyzer(enabled=False)
    now = _calibrate(analyzer, _hiss(0.01, seed=19))

    hit, _ = _feed(analyzer, _voice(0.9), now, 40, speaking=True)
    assert hit is None


def test_junk_input_never_raises():
    analyzer = _analyzer()
    for value in (np.array([], dtype=np.int16), None, [], [0] * 8):
        verdict = analyzer.process_block(value, 1.0, speaking=True)
        assert verdict.interrupt is False


def test_config_is_read_from_the_voice_section():
    cfg = barge_in.BargeInConfig.from_config()
    assert cfg.sensitivity in ("low", "medium", "high")
    assert cfg.min_ms >= 300, "sustain terlalu pendek mengundang salah picu"


def test_barge_in_is_enabled_by_default_now():
    """Fase 19 poin 5 — baru boleh menyala SETELAH 1-4 terpasang."""
    from jarvis.core import config

    assert config.get("voice.barge_in.enabled") is True


# ── level playback diukur, bukan diasumsikan ──────────────────────────────

def test_measured_playback_level_lets_barge_in_actually_work():
    """Asumsi volume penuh membuat barge-in menyala tapi mati dalam praktik.

    Dengan `playback_level=1.0` ambangnya naik ~8x dan tidak ada tingkat suara
    wajar yang bisa memotong. Karena itu levelnya DIUKUR dari audio yang
    benar-benar diputar; saat Jarvis sedang senyap (jeda antar kalimat), user
    bisa masuk dengan volume normal.
    """
    from jarvis.core.barge_in import BargeInConfig

    analyzer = barge_in.BargeInAnalyzer(BargeInConfig.from_config())
    now = _calibrate(analyzer, _hiss(0.02, seed=30))

    loud, _ = _feed(analyzer, _voice(0.35), now, 40,
                    speaking=True, speaking_since=now, playback_level=1.0)
    assert loud is None, "saat Jarvis berbunyi keras, echo tidak boleh menang"

    analyzer2 = barge_in.BargeInAnalyzer(BargeInConfig.from_config())
    now2 = _calibrate(analyzer2, _hiss(0.02, seed=30))
    quiet, _ = _feed(analyzer2, _voice(0.35), now2, 40,
                     speaking=True, playback_level=0.0)
    assert quiet is not None, (
        "saat Jarvis senyap, user harus bisa memotong dengan suara wajar")


def test_playback_level_tap_measures_and_decays():
    from jarvis.integrations import voice_playback_level as vpl

    vpl.reset()
    assert vpl.current_level() == 0.0

    loud = (np.ones(1600) * 12000).astype(np.int16).tobytes()
    vpl.note_chunk(loud)
    assert vpl.current_level() > 0.2

    vpl.note_chunk(b"")
    assert vpl.current_level() > 0.0        # potongan kosong tidak menghapus

    vpl.reset()
    assert vpl.current_level() == 0.0


def test_playback_level_tap_never_raises_on_junk():
    from jarvis.integrations import voice_playback_level as vpl

    for value in (None, b"", b"\x01", "bukan bytes"):
        vpl.note_chunk(value)
    vpl.reset()


# ── S-24: echo guard yang DIUKUR, bukan dikali angka tebakan ──────────────

def _speechlike(level: float, n: int = BLOCK, seed: int = 0) -> np.ndarray:
    """Lebih mirip suara manusia daripada nada 4-harmonik.

    Nada uji lama hampir seluruhnya di bawah 1 kHz (rasio pita 0.95) dan
    ber-crest rendah, sehingga LOLOS semua pembeda dengan mudah. Ucapan
    sungguhan jauh lebih lebar spektrumnya — dan itulah kenapa test lama
    memberi rasa aman palsu.
    """
    rng = np.random.default_rng(seed)
    t = np.arange(n) / SR
    wave = (np.sin(2 * math.pi * 130 * t) * 0.9
            + np.sin(2 * math.pi * 700 * t) * 0.5
            + np.sin(2 * math.pi * 1800 * t) * 0.25
            + np.sin(2 * math.pi * 3000 * t) * 0.12
            + rng.normal(0, 0.06, n))
    wave *= 0.6 + 0.4 * np.sin(2 * math.pi * 4 * t)
    wave = wave / (np.max(np.abs(wave)) + 1e-9)
    return (wave * level * 32768).astype(np.int16)


def test_real_speech_interrupts_while_jarvis_is_speaking_loudly():
    """Kegagalan lapangan yang terukur (S-24).

    Log sesi nyata: blocks_while_speaking 2028, peak_rms 0.551, threshold
    0.0296 — suara Takeda 18x di atas ambang dasar — dan triggers 0.
    Penyebabnya echo_multiplier 8x: saat Jarvis bicara keras, ambang melonjak
    di atas RMS ucapan normal. Angka itu dipilih agar test echo lolos, bukan
    dari pengukuran.
    """
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=40))

    # Jarvis bicara lebih dulu; echo-nya terukur di jendela grace.
    _feed(analyzer, _speechlike(0.20, seed=46), now, 5, speaking=True,
          speaking_since=now, playback_level=0.9)
    now += 5 * BLOCK_S

    hit, _ = _feed(analyzer, _speechlike(0.55, seed=41), now, 40,
                   speaking=True, speaking_since=now - 5.0, playback_level=0.9)

    assert hit is not None, "ucapan nyata harus bisa memotong Jarvis"


def test_steady_echo_still_does_not_interrupt():
    """Pengaman yang membuat barge-in layak dinyalakan tidak boleh hilang."""
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=42))
    echo = _speechlike(0.28, seed=43)

    # Echo mantap: level yang sama berulang-ulang, tanpa lonjakan.
    hit, _ = _feed(analyzer, echo, now, 60, speaking=True,
                   speaking_since=now, playback_level=0.9)

    assert hit is None, "echo yang stabil tidak boleh memotong Jarvis sendiri"


def test_diagnostics_name_the_reason_blocks_are_rejected():
    """Berhenti menebak antara ambang, crest, dan pita suara.

    Tiga kandidat penyebab pernah dipertimbangkan sekaligus; hanya simulasi
    yang memutuskannya. Log harus bisa memutuskannya sendiri lain kali.
    """
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=44))
    _feed(analyzer, _hiss(0.005, seed=45), now, 10, speaking=True)

    rejects = analyzer.diagnostics().get("rejects")

    assert isinstance(rejects, dict)
    assert rejects.get("below_threshold", 0) > 0


# ── S-25: pembeda suara dipelajari dari mikrofon, bukan angka sintetis ────

def test_voice_band_reference_is_learned_from_this_microphone():
    """Log sesi nyata Takeda (2026-08-05 21:37):

        threshold 0.02, echo_floor 0.0001, peak_rms 0.9797, triggers 0
        rejects: below_threshold 4857, broadband 262, transient 56,
                 sustaining 1

    Echo guard sudah benar \u2014 ambang tidak lagi melonjak. Tetapi dari ~318 blok
    yang lolos ambang, hampir semua ditolak `broadband`. Ambang 0.55 dipilih
    dari NADA SINTETIS 4-harmonik (rasio 0.95), bukan dari mikrofon Takeda.

    Perbaikannya bukan menurunkan angka tebakan lagi \u2014 itu sudah dua kali
    gagal. Suara Jarvis sendiri yang lewat speaker ke mikrofon ADALAH ucapan,
    jadi rasio pita yang terukur di jendela grace adalah acuan yang benar untuk
    "seperti apa ucapan terlihat di mikrofon INI".
    """
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=60))

    # Jarvis bicara: acuan pita suara diukur dari echo-nya sendiri.
    _feed(analyzer, _speechlike(0.30, seed=61), now, 6, speaking=True,
          speaking_since=now, playback_level=0.9)

    assert analyzer.voice_ratio_floor > 0.0


def test_speech_no_worse_than_jarvis_own_voice_is_accepted():
    """Jangan menuntut ucapan user lebih "mirip suara" daripada suara Jarvis."""
    analyzer = _analyzer(min_voice_band_ratio=0.95)   # mustahil secara absolut
    now = _calibrate(analyzer, _hiss(0.01, seed=62))
    _feed(analyzer, _speechlike(0.25, seed=63), now, 6, speaking=True,
          speaking_since=now, playback_level=0.9)
    now += 6 * BLOCK_S

    # Level dari log sesi nyata Takeda: peak_rms_while_speaking 0.9797.
    # Memakai angka yang lebih rendah membuat test menguji skenario yang
    # tidak pernah terjadi di mesinnya.
    hit, _ = _feed(analyzer, _speechlike(0.95, seed=64), now, 40,
                   speaking=True, speaking_since=now - 5.0, playback_level=0.9)

    assert hit is not None, (
        "acuan terukur harus mengalahkan ambang absolut yang terlalu ketat")


def test_broadband_noise_is_still_rejected_against_the_reference():
    """Melonggarkan tidak boleh berarti menerima desis."""
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=65))
    _feed(analyzer, _speechlike(0.25, seed=66), now, 6, speaking=True,
          speaking_since=now, playback_level=0.9)
    now += 6 * BLOCK_S

    hit, _ = _feed(analyzer, _hiss(0.40, seed=67), now, 40,
                   speaking=True, speaking_since=now - 5.0, playback_level=0.9)

    assert hit is None


def test_diagnostics_expose_the_observed_ratio():
    """Angka berikutnya harus datang dari mikrofon Takeda, bukan dari sintesis."""
    analyzer = _analyzer()
    now = _calibrate(analyzer, _hiss(0.01, seed=68))
    _feed(analyzer, _speechlike(0.55, seed=69), now, 10, speaking=True)

    snapshot = analyzer.diagnostics()

    assert "voice_ratio_floor" in snapshot
    assert "last_voice_ratio" in snapshot
