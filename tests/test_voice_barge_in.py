"""Voice playback must not self-interrupt on speaker echo.

Fase 19 — penguncian lama dibalik, dengan alasan tertulis.

Test ini dulu mengunci `enabled: false`. Alasannya sah pada waktunya: detektor
saat itu adalah gerbang RMS ambang TETAP 0.14 tanpa noise floor adaptif, tanpa
pembeda suara-vs-bunyi, dan echo guard yang hanya menutup 400 ms pertama.
Dengan detektor itu, menyalakan barge-in berarti Jarvis memotong dirinya
sendiri lewat echo speaker.

Prasyarat itu sudah dijawab di `jarvis/core/barge_in.py`:

* ambang **relatif** terhadap noise floor ruangan (kalibrasi + EMA), bukan
  angka mati;
* transien (pintu, tepukan) dan desis broadband ditolak lewat crest factor dan
  rasio pita suara — hanya ucapan berkelanjutan yang lolos;
* echo guard menaikkan ambang **sepanjang** Jarvis bicara, sebanding dengan
  level playback-nya, bukan hanya di 400 ms pertama;
* sustain harus BERTURUT-TURUT sebelum memicu, dan satu jeda mengembalikan
  hitungan ke nol.

Karena itu yang dikunci sekarang berubah: barge-in menyala, DAN pengaman yang
membuatnya aman wajib tetap ada. Menghapus salah satu pengaman membuat suite
merah — itulah yang mencegah kita kembali ke keadaan lama tanpa sadar.
"""
from __future__ import annotations

from pathlib import Path

import yaml


def _barge_in() -> dict:
    config = yaml.safe_load(Path("config.yaml").read_text(encoding="utf-8-sig"))
    return config["voice"]["barge_in"]


def test_barge_in_is_enabled_now_that_echo_is_handled():
    assert _barge_in()["enabled"] is True


def test_the_safeguards_that_justify_enabling_it_are_present():
    """Menyalakan barge-in hanya sah selama keempat pengaman ini ada."""
    section = _barge_in()

    assert section["calibration_seconds"] > 0, "noise floor adaptif"
    assert section["noise_alpha"] > 0, "noise floor adaptif"
    assert section["echo_multiplier"] >= 2, "echo guard sepanjang ucapan"
    assert section["max_crest"] > 0, "penolak transien"
    assert section["min_voice_band_ratio"] > 0, "penolak desis broadband"


def test_the_fixed_threshold_is_gone():
    """`rms_threshold` adalah angka mati yang membuat detektor lama gagal.

    Membiarkannya di config akan mengundang penyetelan yang tidak berpengaruh
    apa pun terhadap detektor baru.
    """
    assert "rms_threshold" not in _barge_in()


def test_sensitivity_is_the_single_knob():
    assert _barge_in()["sensitivity"] in ("low", "medium", "high")


def test_window_no_longer_owns_the_interrupt_decision():
    """Keputusannya milik modul murni yang bisa diuji, bukan callback audio."""
    source = Path("jarvis/ui/window.py").read_text(encoding="utf-8")
    assert "from jarvis.core.barge_in import" in source
    assert "rms_threshold" not in source


def test_missing_playback_level_assumes_the_loudest_case():
    """Tidak bisa mengukur bukan alasan mematikan echo guard.

    Window tidak punya level playback nyata (audio diputar di main.py yang
    FROZEN). Bila nilai itu absen, wiring HARUS menganggap Jarvis sedang
    berbunyi paling keras — ambang naik penuh. Salah arah di sini berarti
    kembali ke cacat yang membuat barge-in dimatikan: memotong diri sendiri.

    Melewatkan interupsi hanya menjengkelkan; memotong diri sendiri lewat echo
    adalah kegagalan yang membuat fitur ini mati bertahun-tahun.
    """
    from jarvis.ui import window

    # Modul tap tidak bisa diimpor sama sekali → worst-case, BUKAN 0.0.
    class _Win:
        _playback_level = None

    import builtins
    real_import = builtins.__import__

    def _no_tap(name, *a, **k):
        if name == "jarvis.integrations.voice_playback_level":
            raise ImportError("tap tidak terpasang")
        return real_import(name, *a, **k)

    builtins.__import__ = _no_tap
    try:
        assert window._playback_level(_Win()) == 1.0
    finally:
        builtins.__import__ = real_import


def test_explicit_playback_level_wins_for_tests_and_future_seams():
    from jarvis.ui import window

    class _Win:
        _playback_level = 0.25

    assert window._playback_level(_Win()) == 0.25


def test_uninstalled_tap_is_not_mistaken_for_silence():
    """"Belum dipasang" dan "Jarvis sedang diam" adalah dua hal berbeda.

    Bila tap belum terpasang, `current_level()` yang mengembalikan 0.0 akan
    membuat echo guard MATI — arah gagal yang berbahaya, persis cacat yang
    membuat barge-in dimatikan sejak awal. Yang belum terukur harus dianggap
    keras.
    """
    from jarvis.integrations import voice_playback_level as vpl
    from jarvis.ui import window

    installed = vpl.is_installed()
    try:
        vpl._installed = False
        vpl.reset()
        assert window._playback_level(object()) == 1.0

        vpl._installed = True
        vpl.reset()
        assert window._playback_level(object()) == 0.0
    finally:
        vpl._installed = installed
        vpl.reset()
