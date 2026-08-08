"""S-30 — kamera menutup sendiri tanpa diperintah.

Takeda: *"ketika saya perintah buka kamera semua berjalan normal, tapi setelah
beberapa menit kamera otomatis tertutup sendiri padahal belum saya perintah
untuk menutup kamera."*

Yang TIDAK menutupnya: `main.py`. Jalur vision di sana justru menyimpan kamera
tetap terbuka — kode auto-close-nya dikomentari, dan system prompt-nya berbunyi
*"the live view stays open until user says close it or calls close_camera."*

Yang menutupnya: `_do_interrupt`. Saat interupsi tiba dan Jarvis sedang TIDAK
bicara, ia menutup panel stage — dan `stage.hide_all()` membawa serta panel
kamera.

Sejak barge-in benar-benar memicu (S-24/S-25), jalur ini hidup: user bicara
menimpa Jarvis, interupsi dijadwalkan, dan pada saat `_do_interrupt` berjalan
Jarvis kerap sudah selesai bicara — sehingga cabang "tutup panel" yang diambil,
bukan cabang "potong ucapan".

Kamera bukan panel biasa. Ia perangkat fisik yang dinyalakan user secara
eksplisit, dengan LED menyala. Menutupnya sebagai efek samping interupsi adalah
mengambil keputusan yang tidak pernah diminta.
"""
from __future__ import annotations

import pytest


class _Stage:
    def __init__(self, current=None):
        self.current = current
        self.hidden = False

    def hide_all(self):
        self.hidden = True
        self.current = None


def _window(monkeypatch, *, state: str, stage_current):
    from jarvis.ui import window as win_mod

    closed: list[str] = []
    interrupted: list[str] = []

    class _Fake:
        _legacy_state = state
        stage = _Stage(stage_current)
        on_interrupt = staticmethod(lambda: interrupted.append("interrupt"))

        def _close_stage_panels(self):
            closed.append("panels")

        def write_log(self, _text):
            pass

    return win_mod, _Fake(), closed, interrupted


# ── kamera tidak boleh jadi korban interupsi ──────────────────────────────

def test_interrupt_does_not_close_the_camera():
    """Inti keluhan Takeda."""
    win_mod, fake, closed, interrupted = _window(
        monkeypatch=None, state="LISTENING", stage_current="vision")

    win_mod.MainWindow._do_interrupt(fake)

    assert closed == [], "kamera tidak boleh ditutup oleh interupsi"


def test_interrupt_still_closes_an_ordinary_panel():
    """Menutup panel lewat ESC tetap perilaku yang benar."""
    win_mod, fake, closed, _ = _window(
        monkeypatch=None, state="LISTENING", stage_current="browser")

    win_mod.MainWindow._do_interrupt(fake)

    assert closed == ["panels"]


def test_interrupt_while_speaking_still_cuts_speech():
    """Memotong ucapan tetap menang — do-not-regress sejak Fase 22."""
    win_mod, fake, closed, interrupted = _window(
        monkeypatch=None, state="SPEAKING", stage_current="vision")

    win_mod.MainWindow._do_interrupt(fake)

    assert interrupted == ["interrupt"]
    assert closed == []


def test_interrupt_with_no_panel_open_cuts_speech():
    win_mod, fake, closed, interrupted = _window(
        monkeypatch=None, state="SPEAKING", stage_current=None)

    win_mod.MainWindow._do_interrupt(fake)

    assert interrupted == ["interrupt"]


# ── menutup kamera tetap bisa, lewat perintah ─────────────────────────────

def test_an_explicit_close_still_closes_the_camera():
    """Gerbang ini soal SEBAB, bukan larangan menutup kamera."""
    import inspect

    from jarvis.ui import window as win_mod

    source = inspect.getsource(win_mod.MainWindow._set_vision_visible)
    assert "_close_stage_panels" in source, (
        "perintah tutup kamera yang eksplisit harus tetap bekerja")


# ── siapa pun yang menutup kamera harus menyebut namanya ──────────────────

def test_camera_open_and_close_are_logged_with_a_reason():
    """Log sesi Takeda hanya memuat `vision.process_started` dan
    `vision.status` — nol peristiwa buka/tutup panel.

    Karena itu "siapa yang menutup kamera" tidak bisa dijawab dari log dan
    harus dilacak lewat kode. Kesalahan yang sama dengan Fase 22: sunyi tidak
    membedakan apa pun.
    """
    import inspect

    from jarvis.ui import window as win_mod

    source = inspect.getsource(win_mod.MainWindow._set_vision_visible)
    assert "vision.panel" in source


@pytest.mark.parametrize("state", ["LISTENING", "IDLE", "THINKING"])
def test_camera_survives_an_interrupt_in_any_quiet_state(state):
    win_mod, fake, closed, _ = _window(
        monkeypatch=None, state=state, stage_current="vision")

    win_mod.MainWindow._do_interrupt(fake)

    assert closed == []
