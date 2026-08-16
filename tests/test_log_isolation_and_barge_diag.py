"""Fase 22 — interupsi suara terbukti hidup (S-22).

Takeda: *"voice interupt tidak berfungsi, saya tidak bisa menyela jarvis."*

Diagnosis pertama nyaris salah. Log memuat `barge_in.triggered` 52 kali, yang
tampak seperti "deteksi jalan, interupsinya yang gagal". Timestampnya berjarak
**milidetik** — itu pytest, bukan orang bicara. Suite menulis ke log produksi
yang sama.

Jadi dua pekerjaan, dan urutannya penting:

1. **Pisahkan log test dari log produksi.** Selama bercampur, tidak ada
   diagnosis runtime yang bisa dipercaya — termasuk diagnosis fase ini sendiri.
2. **Buat sesi nyata bisa menjawab sendiri.** Barge-in hanya mencatat saat
   MEMICU, sehingga "tidak pernah memicu" dan "tidak pernah jalan" terlihat
   sama persis di log: sunyi. Diagnostik berkala membedakan keduanya.
"""
from __future__ import annotations

import numpy as np

from jarvis.core import barge_in


SR = 16000
BLOCK = 1024
BLOCK_S = BLOCK / SR


def _hiss(level, n=BLOCK, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.normal(0, level, n).clip(-1, 1) * 32768).astype(np.int16)


# ── 1. log test tidak boleh mencemari log produksi ────────────────────────

def test_test_runs_do_not_write_to_the_production_log():
    """Pytest harus punya berkas lognya sendiri.

    Tanpa ini, `barge_in.triggered` dari suite tidak bisa dibedakan dari
    ucapan Takeda, dan setiap diagnosis runtime jadi tebakan.
    """
    from jarvis.core import log

    assert log.is_test_run() is True, (
        "pytest harus terdeteksi sebagai test run")
    assert "test" in log.active_log_path().name.casefold(), (
        f"log test masih menulis ke {log.active_log_path()}")


def test_production_path_is_used_when_not_testing(monkeypatch):
    from jarvis.core import log

    monkeypatch.setattr(log, "is_test_run", lambda: False)
    assert log.active_log_path().name == "jarvis.log"


# ── 2. sesi nyata harus bisa menjawab sendiri ─────────────────────────────

def test_analyzer_reports_why_it_did_not_fire():
    """"Tidak memicu" dan "tidak jalan" harus terlihat BERBEDA di log.

    Tanpa ini keduanya sama-sama sunyi, dan sunyi tidak membedakan apa pun.
    """
    analyzer = barge_in.BargeInAnalyzer(
        barge_in.BargeInConfig(enabled=True, diagnostics_every_s=0.0))
    analyzer.start_calibration(0.0)
    now = 0.0
    for _ in range(30):
        analyzer.process_block(_hiss(0.02, seed=1), now, speaking=True)
        now += BLOCK_S

    snapshot = analyzer.diagnostics()

    assert snapshot["blocks_while_speaking"] > 0
    assert snapshot["noise_floor"] > 0
    assert snapshot["threshold"] > 0
    assert "peak_rms_while_speaking" in snapshot
    assert snapshot["triggers"] == 0


def test_diagnostics_track_the_loudest_attempt():
    """Angka yang menjawab "apakah suara saya pernah mendekati ambang?"."""
    analyzer = barge_in.BargeInAnalyzer(
        barge_in.BargeInConfig(enabled=True))
    analyzer.start_calibration(0.0)
    now = 0.0
    for _ in range(30):
        analyzer.process_block(_hiss(0.01, seed=2), now, speaking=True)
        now += BLOCK_S

    quiet = analyzer.diagnostics()["peak_rms_while_speaking"]

    for _ in range(5):
        analyzer.process_block(_hiss(0.30, seed=3), now, speaking=True,
                               playback_level=1.0)
        now += BLOCK_S

    assert analyzer.diagnostics()["peak_rms_while_speaking"] > quiet


def test_diagnostics_count_real_triggers():
    analyzer = barge_in.BargeInAnalyzer(barge_in.BargeInConfig(enabled=True))
    analyzer.start_calibration(0.0)
    now = 0.0
    for _ in range(30):
        analyzer.process_block(_hiss(0.01, seed=4), now, speaking=True)
        now += BLOCK_S

    t = np.arange(BLOCK) / SR
    voice = (np.sin(2 * np.pi * 180 * t) * 0.4 * 32768).astype(np.int16)
    for _ in range(40):
        if analyzer.process_block(voice, now, speaking=True).interrupt:
            break
        now += BLOCK_S

    assert analyzer.diagnostics()["triggers"] == 1


def test_diagnostics_never_raise():
    analyzer = barge_in.BargeInAnalyzer(barge_in.BargeInConfig())
    assert isinstance(analyzer.diagnostics(), dict)


# ── 3. rantai interupsi terkunci ──────────────────────────────────────────

def test_microphone_interrupt_is_separate_from_escape_panel_semantics(monkeypatch):
    """Barge-in mikrofon tidak boleh berubah menjadi ESC saat UI sudah diam.

    Callback audio diproses secara queued. Saat event sampai, state UI dapat
    sudah LISTENING; event suara tetap memotong turn yang cocok dan tidak
    menutup panel biasa.
    """
    from types import SimpleNamespace

    from jarvis.integrations import voice_interrupt
    from jarvis.ui import window

    called: list[str] = []
    closed: list[str] = []
    monkeypatch.setattr(
        voice_interrupt, "validate_event",
        lambda _win, _event: "voice_interrupt_accepted",
    )

    class _Stage:
        current = "browser"

    class _Fake:
        _legacy_state = "LISTENING"
        _last_voice_interrupt_token = ""
        stage = _Stage()
        on_interrupt = staticmethod(lambda: called.append("interrupt"))

        def _close_stage_panels(self):
            closed.append("panel")

        def write_log(self, _text):
            return None

    event = SimpleNamespace(
        token="microphone:1:2:3:4", playback_generation=2,
        playback_epoch=3, capture_generation=1,
        rms=0.2, threshold=0.1, noise_floor=0.01,
    )
    window.MainWindow._do_voice_interrupt(_Fake(), event)

    assert called == ["interrupt"]
    assert closed == []


def test_esc_closes_a_panel_only_when_jarvis_is_silent():
    """Memotong ucapan menang atas menutup panel — urutan itu do-not-regress."""
    from jarvis.ui import window

    closed: list[str] = []
    called: list[str] = []

    class _Stage:
        current = "browser"

    class _Fake:
        _legacy_state = "LISTENING"
        stage = _Stage()
        on_interrupt = staticmethod(lambda: called.append("interrupt"))

        def _close_stage_panels(self):
            closed.append("panel")

    window.MainWindow._do_interrupt(_Fake())

    assert closed == ["panel"] and called == []


def test_legacy_facade_binds_the_window_callback():
    """`main.py` memasang `ui.on_interrupt`; facade harus meneruskannya."""
    import inspect

    from jarvis.ui import window

    source = inspect.getsource(window)
    assert "def on_interrupt" in source
    assert "self._win.on_interrupt = cb" in source


def test_mic_meter_announces_that_it_is_alive():
    """Thread mati dan barge-in yang tak memicu sama-sama sunyi di log.

    Satu baris saat stream terbuka membedakan keduanya, dan itulah pembeda
    yang membuat sesi nyata bisa menjawab tanpa menebak.
    """
    from pathlib import Path

    source = Path("jarvis/ui/window.py").read_text(encoding="utf-8")
    body = source.split("def _mic_meter")[1].split("\n    # ")[0]
    assert "mic_meter.started" in body
    assert "diagnostics()" in body
