"""S-27 — Jarvis menutup DIRINYA SENDIRI lewat hotkey mentah.

Takeda: *"sekarang malah force close ketika di interupt."*

Log sesi 2026-08-05 22:05 menunjukkan itu bukan crash sama sekali:

    {"tool": "computer_control", "result": "Hotkey: alt+f4"}
    telegram.stopped … wake.stopped

Penutupan tertib — bunuh diri, bukan kecelakaan.

`process_guard` menjaga `close_app` (menolak target Jarvis) dan
`shutdown_jarvis` (menuntut konfirmasi dua langkah). Tetapi `computer_control`
dengan `action="hotkey", keys="alt+f4"` melewati keduanya: tidak ada target
yang diperiksa, tidak ada konfirmasi, dan Alt+F4 mendarat di jendela yang
sedang FOKUS — yang setelah user bicara ke Jarvis sering kali Jarvis sendiri.

Cacat ini sudah tertulis di docstring `actions/close_app.py` sejak DIAGNOSIS_2
sebagai alasan modul itu dibuat. Yang tidak ikut ditutup waktu itu: jalur
hotkey mentahnya masih terbuka.
"""
from __future__ import annotations

import pytest

from actions import computer_control as cc


@pytest.fixture
def pressed(monkeypatch):
    keys: list = []
    monkeypatch.setattr(cc, "_hotkey",
                        lambda *k: (keys.append("+".join(k)), "ok")[1])
    monkeypatch.setattr(cc, "_press",
                        lambda k: (keys.append(k), "ok")[1])
    return keys


def _focus_is_jarvis(monkeypatch, value: bool):
    monkeypatch.setattr(cc, "_focused_window_is_jarvis", lambda: value)


# ── hotkey yang menutup jendela ───────────────────────────────────────────

@pytest.mark.parametrize("keys", ["alt+f4", "ALT+F4", "alt + f4"])
def test_alt_f4_is_refused_when_jarvis_is_focused(keys, pressed, monkeypatch):
    _focus_is_jarvis(monkeypatch, True)

    result = cc.computer_control({"action": "hotkey", "keys": keys})

    assert pressed == [], "Alt+F4 tidak boleh sampai ke pyautogui"
    assert "jarvis" in result.casefold()


def test_alt_f4_is_allowed_when_another_window_is_focused(pressed, monkeypatch):
    """Gerbang ini soal SASARAN, bukan larangan menutup jendela."""
    _focus_is_jarvis(monkeypatch, False)

    cc.computer_control({"action": "hotkey", "keys": "alt+f4"})

    assert pressed == ["alt+f4"]


def test_other_hotkeys_are_untouched(pressed, monkeypatch):
    """Menjaga satu jalur tidak boleh melumpuhkan kendali komputer."""
    _focus_is_jarvis(monkeypatch, True)

    cc.computer_control({"action": "hotkey", "keys": "ctrl+c"})

    assert pressed == ["ctrl+c"]


@pytest.mark.parametrize("keys", ["cmd+q", "command+q", "alt+f4"])
def test_every_window_closing_combo_is_guarded(keys, pressed, monkeypatch):
    _focus_is_jarvis(monkeypatch, True)

    cc.computer_control({"action": "hotkey", "keys": keys})

    assert pressed == []


def test_a_bare_f4_press_is_not_blocked(pressed, monkeypatch):
    """Hanya kombinasi yang benar-benar menutup jendela yang dijaga."""
    _focus_is_jarvis(monkeypatch, True)

    cc.computer_control({"action": "press", "key": "f4"})

    assert pressed == ["f4"]


def test_the_guard_never_raises_when_focus_cannot_be_read(pressed, monkeypatch):
    """Tidak bisa membaca fokus bukan alasan melumpuhkan tool.

    Tetapi untuk kombinasi yang mematikan, tidak tahu = jangan lakukan:
    salah di sini menutup Jarvis, dan itu tidak bisa dibatalkan dari dalam.
    """
    def _boom():
        raise RuntimeError("tidak terbaca")

    monkeypatch.setattr(cc, "_focused_window_is_jarvis", _boom)

    result = cc.computer_control({"action": "hotkey", "keys": "alt+f4"})

    assert pressed == []
    assert isinstance(result, str)


def test_focus_detection_recognises_the_jarvis_window(monkeypatch):
    """Deteksi memakai process_guard yang sudah ada, bukan daftar baru."""
    from jarvis.core import process_guard

    assert process_guard.refers_to_jarvis("JARVIS") is True
    assert process_guard.refers_to_jarvis("Google Chrome") is False
