"""Fase 10.2 — skrip elevasi firewall tidak boleh ditulis di direktori bersama.

`dashboard/server.py` membangun berkas `.bat` lalu menjalankannya — dan bila
gagal, menjalankannya ULANG lewat ``ShellExecuteW(..., "runas", ...)`` yang
menaikkan hak ke Administrator dengan jendela tersembunyi.

Bentuk lama memakai ``tempfile.mkstemp()``, yaitu direktori temp yang bisa
ditulis proses lain di mesin yang sama. Antara saat berkas ditulis dan saat
dieksekusi ada jendela waktu; siapa pun yang bisa menulis di sana berpeluang
mengganti isinya, dan yang berjalan kemudian adalah perintah pihak lain
dengan hak Administrator.

Kontrak yang dikunci di sini: skrip elevasi hidup di direktori privat milik
user, bukan di temp bersama, dan dibersihkan setelah dipakai.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from dashboard.server import _elevation_script


def test_skrip_tidak_ditulis_di_direktori_temp_bersama():
    with _elevation_script("@echo off\r\n") as path:
        shared = Path(tempfile.gettempdir()).resolve()
        assert shared not in path.resolve().parents, (
            f"skrip elevasi berada di temp bersama: {path}")


def test_skrip_berada_di_direktori_privat_jarvis():
    with _elevation_script("@echo off\r\n") as path:
        parts = {p.lower() for p in path.resolve().parts}
        assert ".jarvis" in parts, path


def test_isi_skrip_ditulis_apa_adanya():
    body = "@echo off\r\nnetsh advfirewall firewall add rule name=\"X\"\r\n"
    with _elevation_script(body) as path:
        assert path.read_bytes() == body.encode("mbcs")


def test_berkas_dihapus_setelah_context_selesai():
    with _elevation_script("@echo off\r\n") as path:
        assert path.exists()
    assert not path.exists(), "skrip elevasi tertinggal setelah dipakai"


def test_dihapus_juga_saat_terjadi_exception():
    captured = {}
    try:
        with _elevation_script("@echo off\r\n") as path:
            captured["path"] = path
            raise RuntimeError("gagal di tengah")
    except RuntimeError:
        pass
    assert not captured["path"].exists()


def test_setiap_pemanggilan_memakai_nama_unik():
    with _elevation_script("@echo off\r\n") as a:
        with _elevation_script("@echo off\r\n") as b:
            assert a != b
