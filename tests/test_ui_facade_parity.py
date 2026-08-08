"""Fase 12 — kunci kontrak antara facade legacy (FROZEN) dan facade MK50.

`ui.py` (FROZEN) dan `jarvis/ui/window.py` sama-sama menyediakan kelas
``JarvisUI`` yang men-drive pipeline ``main.JarvisLive``. Selama keduanya
hidup berdampingan, setiap perilaku bersama harus dirawat dua kali — dan
karena `ui.py` frozen, perbaikan hanya bisa masuk di satu sisi.

Biayanya sudah nyata: bug `wait_for_api_key` menunggu tanpa batas ada
IDENTIK di kedua file. Fase 5 hanya bisa memperbaiki sisi MK50; sisa bug itu
masih hidup di `ui.py:2588-2590`, terpicu bila seseorang menjalankan
``python main.py`` langsung (masih mungkin — `main.py:1876`), bukan lewat
``python -m jarvis.main`` yang didokumentasikan readme dan dipaketkan
`pyproject.toml`.

Test ini tidak menghapus duplikasinya — itu keputusan arsitektur Takeda.
Yang dikunci: **MK50 tidak boleh menyusut** dari permukaan legacy, dan setiap
penyimpangan BARU harus disengaja, bukan menyelinap tanpa terlihat.

Analisis statis lewat AST: tidak mengimpor Qt, jadi murah dan bebas display.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[1]
_LEGACY = _REPO / "ui.py"
_MK50 = _REPO / "jarvis" / "ui" / "window.py"

# Penyimpangan yang DISENGAJA. Menambah entri di sini berarti menyatakan
# "ya, saya tahu kedua sisi berbeda, dan ini alasannya".
KNOWN_DIVERGENCE = {
    "__init__":
        "MK50 menerima services={assistant, vision}; legacy tidak punya "
        "konsep itu.",
    "wait_for_api_key":
        "Fase 5 memberi timeout+should_stop di sisi MK50. ui.py FROZEN masih "
        "menunggu tanpa batas (ui.py:2588) — hanya terpicu lewat "
        "`python main.py` langsung. Hapus entri ini setelah Fase 12 memutuskan "
        "nasib dual stack.",
}


def _methods(path: Path, class_name: str) -> dict[str, tuple[str, ...]]:
    tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                item.name: tuple(a.arg for a in item.args.args if a.arg != "self")
                for item in node.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            }
    raise AssertionError(f"kelas {class_name} tidak ditemukan di {path}")


@pytest.fixture(scope="module")
def facades():
    return _methods(_LEGACY, "JarvisUI"), _methods(_MK50, "JarvisUI")


def test_mk50_menyediakan_seluruh_permukaan_legacy(facades):
    """MK50 harus superset: pipeline legacy tidak boleh kehilangan pijakan."""
    legacy, mk50 = facades
    hilang = sorted(set(legacy) - set(mk50))
    assert not hilang, (
        f"jarvis/ui/window.py kehilangan metode yang dipakai pipeline legacy: "
        f"{hilang}")


def test_penyimpangan_tanda_tangan_hanya_yang_didaftarkan(facades):
    """Penyimpangan BARU harus gagal di sini, bukan ditemukan saat runtime."""
    legacy, mk50 = facades
    menyimpang = {
        name for name in set(legacy) & set(mk50)
        if legacy[name] != mk50[name]
    }
    tak_terdaftar = sorted(menyimpang - set(KNOWN_DIVERGENCE))
    assert not tak_terdaftar, (
        f"tanda tangan menyimpang tanpa alasan tertulis: {tak_terdaftar}. "
        f"Daftarkan di KNOWN_DIVERGENCE beserta alasannya, atau selaraskan.")


def test_daftar_penyimpangan_tidak_menyimpan_entri_basi(facades):
    """Kalau sebuah penyimpangan sudah diselesaikan, entrinya harus dibuang."""
    legacy, mk50 = facades
    basi = [
        name for name in KNOWN_DIVERGENCE
        if name in legacy and name in mk50 and legacy[name] == mk50[name]
    ]
    assert not basi, f"entri KNOWN_DIVERGENCE sudah tidak relevan: {basi}"


def test_entry_point_yang_didukung_adalah_jarvis_main():
    """`pyproject.toml` memaketkan SATU entry point; readme mendokumentasikan
    yang sama. Kalau ini berubah, dual stack harus ditinjau ulang."""
    pyproject = (_REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert 'jarvis = "jarvis.main:main"' in pyproject

    readme = (_REPO / "readme.md").read_text(encoding="utf-8", errors="replace")
    assert "python -m jarvis.main" in readme
    assert "\npython main.py" not in readme, (
        "readme mulai mendokumentasikan `python main.py` sebagai perintah; "
        "jalur itu memakai ui.py FROZEN yang masih memuat bug "
        "wait_for_api_key tanpa batas.")


def test_readme_menyatakan_jalur_legacy_tidak_didukung():
    """Fase 12 opsi (b): penegakan satu entry point berupa pernyataan
    eksplisit di readme, karena `main.py:1876` FROZEN dan blok ``__main__``
    di sana tidak boleh dihapus tanpa baseline frozen baru.

    Pernyataan itu adalah SATU-SATUNYA penegakan yang tersedia tanpa
    menyentuh berkas frozen, jadi hilangnya harus membuat test ini merah.
    """
    readme = (_REPO / "readme.md").read_text(encoding="utf-8", errors="replace")
    assert "satu-satunya entry point yang didukung" in readme.casefold(), (
        "readme tidak lagi menyatakan entry point tunggal")
    assert "TIDAK didukung" in readme, (
        "peringatan jalur legacy hilang dari readme")
    assert "ui.py:2588" in readme, (
        "readme tidak lagi menunjuk lokasi bug yang membuat jalur legacy "
        "berbahaya — pembaca kehilangan alasan konkretnya")
