"""Presence: JARVIS menyela sesekali dengan progres, tidak diam total."""
from __future__ import annotations

from jarvis.agent.progress_narrator import ProgressNarrator, phrase_for


def test_phrase_natural_untuk_tool_umum():
    assert "mencari" in phrase_for("web_search").lower()
    assert "gambar" in phrase_for("image_generate").lower()
    # Prefix emoji dari agent loop dibersihkan.
    assert "mencari" in phrase_for("🔧 web_search").lower()


def test_phrase_fallback_generic_untuk_tool_asing():
    out = phrase_for("tool_yang_tidak_dikenal")
    assert out and "kerjakan" in out.lower()


def test_narrator_throttle_min_interval():
    n = ProgressNarrator(min_interval_s=10.0, max_spoken=10)
    assert n.should_speak("A", now=0.0) is True
    # Frasa beda tapi masih dalam interval → tidak diucapkan.
    assert n.should_speak("B", now=3.0) is False
    # Setelah interval lewat → boleh lagi.
    assert n.should_speak("B", now=11.0) is True


def test_narrator_tidak_mengulang_frasa_sama():
    n = ProgressNarrator(min_interval_s=0.0, max_spoken=10)
    assert n.should_speak("sama", now=0.0) is True
    assert n.should_speak("sama", now=1.0) is False   # jangan ulang frasa identik
    assert n.should_speak("beda", now=2.0) is True


def test_narrator_batasi_jumlah_ucapan_per_tugas():
    n = ProgressNarrator(min_interval_s=0.0, max_spoken=2)
    assert n.should_speak("a", now=0.0) is True
    assert n.should_speak("b", now=1.0) is True
    assert n.should_speak("c", now=2.0) is False       # sudah mencapai batas
    n.reset()
    assert n.should_speak("d", now=3.0) is True        # reset → boleh lagi
