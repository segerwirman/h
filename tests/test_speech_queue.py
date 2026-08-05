"""Fase 28 — satu antrean bicara (keluhan lapangan Takeda).

*"ketika jarvis mendapat perintah yang menggunakan agent native suara tumpang
tindih dan saling memotong membuat saya bingung apa yang sedang dikerjakan."*

Sebabnya terukur di kode: `MainWindow._speak_line` melahirkan **thread baru
untuk setiap kalimat**, dan ada 42 pemanggil — ACK, narator progres, hasil
akhir, konfirmasi, ringkasan pencarian. Tidak ada yang menyerialkan mereka,
jadi semuanya bisa berbunyi bersamaan.

Antrean ini bukan sekadar mengurutkan. Yang penting adalah **apa yang DIBUANG**:
progres yang sudah basi ketika hasil akhir tiba tidak boleh diucapkan
belakangan, karena itulah yang membuat user bingung soal apa yang sedang
dikerjakan.
"""
from __future__ import annotations

import pytest

from jarvis.core.speech_queue import SpeechQueue


@pytest.fixture
def spoken():
    return []


@pytest.fixture
def queue(spoken):
    return SpeechQueue(speaker=spoken.append)


# ── serialisasi ───────────────────────────────────────────────────────────

def test_lines_are_spoken_one_at_a_time_in_order(queue, spoken):
    queue.say("satu", kind="final")
    queue.say("dua", kind="final")
    queue.drain()

    assert spoken == ["satu", "dua"]


def test_a_speaker_that_raises_never_stops_the_queue():
    spoken: list[str] = []

    def _speaker(text):
        if text == "meledak":
            raise RuntimeError("tts mati")
        spoken.append(text)

    queue = SpeechQueue(speaker=_speaker)
    queue.say("meledak", kind="final")
    queue.say("lanjut", kind="final")
    queue.drain()

    assert spoken == ["lanjut"]


# ── yang dibuang, bukan yang diurutkan ────────────────────────────────────

def test_newer_progress_supersedes_the_stale_one(queue, spoken):
    """Progres lama tidak berguna begitu ada yang lebih baru."""
    queue.say("mencari kontak…", kind="progress", turn="t1")
    queue.say("membuka whatsapp…", kind="progress", turn="t1")
    queue.drain()

    assert spoken == ["membuka whatsapp…"]


def test_a_final_result_cancels_pending_progress(queue, spoken):
    """Inti keluhan: progres basi terdengar SETELAH hasilnya sudah ada."""
    queue.say("membuka whatsapp…", kind="progress", turn="t1")
    queue.say("Panggilan ke Honbrew berdering.", kind="final", turn="t1")
    queue.drain()

    assert spoken == ["Panggilan ke Honbrew berdering."]


def test_an_ack_is_dropped_when_the_result_already_arrived(queue, spoken):
    """"Baik, saya kerjakan" setelah pekerjaannya selesai hanya membingungkan."""
    queue.say("Baik, saya kerjakan.", kind="ack", turn="t1")
    queue.say("Sudah selesai.", kind="final", turn="t1")
    queue.drain()

    assert spoken == ["Sudah selesai."]


def test_progress_of_another_turn_is_not_cancelled(queue, spoken):
    """Pembatalan mengikat SATU giliran, bukan seluruh antrean."""
    queue.say("mencari…", kind="progress", turn="t1")
    queue.say("Selesai.", kind="final", turn="t2")
    queue.drain()

    assert "mencari…" in spoken


# ── konfirmasi tidak boleh tertelan ───────────────────────────────────────

def test_a_confirmation_question_jumps_the_queue(queue, spoken):
    queue.say("mencari kontak…", kind="progress", turn="t1")
    queue.say("Telepon Honbrew sekarang?", kind="confirm", turn="t1")
    queue.drain()

    assert spoken[0] == "Telepon Honbrew sekarang?"


def test_a_confirmation_is_never_dropped(queue, spoken):
    """Pertanyaan yang hilang membuat user menunggu jawaban yang tak diminta."""
    queue.say("Telepon Honbrew sekarang?", kind="confirm", turn="t1")
    queue.say("Sudah selesai.", kind="final", turn="t1")
    queue.drain()

    assert "Telepon Honbrew sekarang?" in spoken


# ── kebersihan dasar ──────────────────────────────────────────────────────

def test_the_same_sentence_is_not_repeated_back_to_back(queue, spoken):
    queue.say("Sedang saya kerjakan.", kind="progress", turn="t1")
    queue.drain()
    queue.say("Sedang saya kerjakan.", kind="progress", turn="t1")
    queue.drain()

    assert spoken == ["Sedang saya kerjakan."]


def test_empty_text_is_ignored(queue, spoken):
    queue.say("", kind="final")
    queue.say("   ", kind="final")
    queue.drain()

    assert spoken == []


def test_queue_is_bounded(queue, spoken):
    for index in range(SpeechQueue.MAX_PENDING + 50):
        queue.say(f"baris {index}", kind="final", turn=f"t{index}")

    assert queue.pending() <= SpeechQueue.MAX_PENDING


@pytest.mark.parametrize("junk", [None, 12, object()])
def test_junk_never_raises(queue, junk):
    queue.say(junk, kind="final")
    queue.drain()


def test_unknown_kind_is_treated_as_ordinary_speech(queue, spoken):
    queue.say("halo", kind="entah-apa")
    queue.drain()

    assert spoken == ["halo"]


# ── terpasang di jalur nyata ──────────────────────────────────────────────

def test_window_speaks_through_the_queue():
    """42 pemanggil `_speak_line` harus melewati satu pintu.

    Bentuk lama melahirkan thread baru per kalimat tanpa koordinasi — itulah
    penyebab suara tumpang tindih.
    """
    from pathlib import Path

    source = Path("jarvis/ui/window.py").read_text(encoding="utf-8")
    body = source.split("def _speak_line")[1].split("\n    def ")[0]

    assert "speech_queue" in body or "_speech" in body
    assert "threading.Thread" not in body, (
        "satu thread per kalimat adalah sumber tumpang tindihnya")


def test_progress_and_confirmation_are_labelled_by_their_source():
    """Antrean hanya bisa membuang yang basi kalau tahu jenisnya.

    `UIAdapter.progress` adalah narasi kerja (boleh digantikan); `ask` adalah
    pertanyaan konfirmasi (tidak boleh hilang). Tanpa label, keduanya
    diperlakukan sama dan justru pertanyaan yang bisa tertelan.
    """
    import inspect

    from jarvis.agent.adapters import ui as ui_adapter

    source = inspect.getsource(ui_adapter)
    assert 'kind="progress"' in source
    assert 'kind="confirm"' in source


def test_dispatch_labels_ack_and_result():
    """ACK yang tiba setelah hasilnya selesai hanya membingungkan."""
    import inspect

    from jarvis import main as jarvis_main

    source = inspect.getsource(jarvis_main)
    assert 'kind="ack"' in source or "kind='ack'" in source
