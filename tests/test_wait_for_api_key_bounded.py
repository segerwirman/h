"""Fase 6.3 — menunggu API key TIDAK boleh menggantung selamanya.

Bentuk lama (jarvis/ui/window.py:2448, dan salinan identik di ui.py FROZEN):

    def wait_for_api_key(self):
        while not self._win._ready:
            time.sleep(0.1)

Dipanggil jarvis/main.py SEBELUM JarvisLive(ui) dibuat, pada thread yang
dibuat daemon=False. Bila API key belum diisi, thread menggantung selamanya
sehingga ``ui.on_text_command`` tak pernah ter-bind — gejalanya identik
dengan insiden boot-diam 2026-08-04, tetapi penyebabnya sama sekali berbeda.
Proses juga tidak bisa keluar bersih.

Test ini memakai stub ``_win`` supaya kontraknya teruji tanpa membangun
seluruh aplikasi Qt.
"""
from __future__ import annotations

import threading
import time

from jarvis.ui.window import JarvisUI

_wait = JarvisUI.wait_for_api_key


class _Win:
    def __init__(self, ready: bool = False):
        self._ready = ready


class _Stub:
    """Objek seminimal mungkin: hanya atribut yang benar-benar disentuh."""

    def __init__(self, ready: bool = False):
        self._win = _Win(ready)


def test_tidak_menggantung_saat_key_tidak_pernah_diisi():
    stub = _Stub(ready=False)
    t0 = time.monotonic()

    result = _wait(stub, timeout=0.5)

    elapsed = time.monotonic() - t0
    assert result is False, "timeout harus melapor gagal, bukan sukses"
    assert elapsed < 5.0, f"menggantung {elapsed:.1f}s — batas tidak dihormati"


def test_mengembalikan_true_saat_key_masuk():
    stub = _Stub(ready=False)

    def arrive():
        time.sleep(0.15)
        stub._win._ready = True

    threading.Thread(target=arrive, daemon=True).start()
    assert _wait(stub, timeout=5.0) is True


def test_langsung_true_bila_sudah_siap():
    t0 = time.monotonic()
    assert _wait(_Stub(ready=True), timeout=5.0) is True
    assert time.monotonic() - t0 < 1.0


def test_should_stop_membatalkan_penantian():
    stub = _Stub(ready=False)
    t0 = time.monotonic()

    result = _wait(stub, timeout=30.0, should_stop=lambda: True)

    elapsed = time.monotonic() - t0
    assert result is False
    assert elapsed < 5.0, f"shutdown diabaikan, menunggu {elapsed:.1f}s"


def test_default_timeout_terbatas_bukan_tak_hingga():
    """Pemanggilan lama ``wait_for_api_key()`` tanpa argumen harus tetap
    punya batas — kalau tidak, bug lamanya hidup lagi lewat pintu belakang."""
    import inspect

    sig = inspect.signature(_wait)
    assert "timeout" in sig.parameters, "parameter timeout hilang"
    default = sig.parameters["timeout"].default
    if default is not None:
        assert 0 < float(default) < 86400, default
