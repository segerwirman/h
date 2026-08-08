"""Fase 32 — WebEngine bisa dimuat saat dibutuhkan (T4).

Boot melaporkan `core.browser DEGRADED — system browser ready; no embed
driver`, padahal PyQt6-WebEngine terpasang. Direproduksi di dua proses bersih,
dan Qt sendiri menyebutkan sebabnya:

    QtWebEngineWidgets must be imported or Qt.AA_ShareOpenGLContexts must be
    set before a QCoreApplication instance is created

**Ini bukan kosmetik.** `jarvis/browser/agent_view.py` dan
`jarvis/browser/embed.py` mengimpor `QWebEngineView` secara *lazy* — yaitu
sesudah `QApplication` ada — sehingga importnya SELALU gagal di aplikasi yang
berjalan. Browser agent tertanam mati diam-diam, dan yang terlihat hanya satu
baris status yang terbaca seperti hal sepele.

**Perbaikannya bukan mengimpor WebEngine lebih awal.** MK50 §7 sengaja
membuang QtWebEngine dari jalur boot, dan `tests/test_phase5_stage_home.py`
menjaga keputusan itu. Menariknya kembali berarti memuat Chromium ~100 MB pada
setiap boot demi fitur yang jarang dipakai. Yang dipasang adalah satu atribut
Qt — murah, tanpa memuat apa pun — sehingga import lazy-nya berhasil ketika
benar-benar dibutuhkan.
"""
from __future__ import annotations

import os
import subprocess
import sys


def _run(code: str) -> str:
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    result = subprocess.run([sys.executable, "-c", code], capture_output=True,
                            text=True, cwd=".", env=env, timeout=180)
    return (result.stdout + result.stderr).strip()


def test_the_failure_this_phase_fixes_is_real():
    """Kunci premisnya. Kalau Qt berubah, fase ini harus ditinjau ulang."""
    output = _run(
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication(['jarvis'])\n"
        "try:\n"
        "    from PyQt6.QtWebEngineWidgets import QWebEngineView\n"
        "    print('IMPORT_OK')\n"
        "except ImportError as exc:\n"
        "    print('IMPORT_FAILED', str(exc)[:120])\n"
    )

    assert "IMPORT_FAILED" in output, output
    assert "AA_ShareOpenGLContexts" in output


def test_the_attribute_makes_the_lazy_import_work():
    """Inti fase ini: satu atribut, dipasang sebelum QApplication."""
    output = _run(
        "import sys; sys.path.insert(0, '.')\n"
        "from jarvis.ui import qt_webengine\n"
        "qt_webengine.enable_shared_gl()\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication(['jarvis'])\n"
        "from PyQt6.QtWebEngineWidgets import QWebEngineView\n"
        "print('IMPORT_OK', QWebEngineView.__name__)\n"
    )

    assert "IMPORT_OK" in output, output


def test_enabling_does_not_load_chromium():
    """MK50 §7 tetap berlaku: Chromium tidak boleh ikut di jalur boot.

    Menariknya kembali berarti ~100 MB pada setiap boot demi fitur yang jarang
    dipakai — persis yang dulu sengaja dibuang.
    """
    output = _run(
        "import sys; sys.path.insert(0, '.')\n"
        "from jarvis.ui import qt_webengine\n"
        "qt_webengine.enable_shared_gl()\n"
        "loaded = [name for name in sys.modules if 'WebEngine' in name]\n"
        "print('LOADED', loaded)\n"
    )

    assert "LOADED []" in output, output


def test_the_boot_check_reports_ready_in_the_real_order():
    """Yang diukur harus jalur yang sungguhan, bukan proses kosong."""
    output = _run(
        "import sys; sys.path.insert(0, '.')\n"
        "from jarvis.ui import qt_webengine\n"
        "qt_webengine.enable_shared_gl()\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication(['jarvis'])\n"
        "from jarvis.core.boot import _check_browser\n"
        "result = _check_browser()\n"
        "print('DEGRADED', result.degraded, '|', result.detail)\n"
    )

    assert "DEGRADED False" in output, output
    assert "QtWebEngine ready" in output


def test_enabling_is_idempotent():
    output = _run(
        "import sys; sys.path.insert(0, '.')\n"
        "from jarvis.ui import qt_webengine\n"
        "print('FIRST', qt_webengine.enable_shared_gl())\n"
        "print('SECOND', qt_webengine.enable_shared_gl())\n"
    )

    assert "FIRST True" in output, output
    assert "SECOND True" in output


def test_enabling_after_the_application_exists_reports_failure_honestly():
    """Terlambat adalah terlambat. Mengembalikan True akan berbohong."""
    output = _run(
        "import sys; sys.path.insert(0, '.')\n"
        "from PyQt6.QtWidgets import QApplication\n"
        "app = QApplication(['jarvis'])\n"
        "from jarvis.ui import qt_webengine\n"
        "print('LATE', qt_webengine.enable_shared_gl())\n"
    )

    assert "LATE False" in output, output


def test_enabling_never_raises_without_qt(monkeypatch):
    from jarvis.ui import qt_webengine

    monkeypatch.setattr(qt_webengine, "_set_attribute",
                        lambda: (_ for _ in ()).throw(RuntimeError("tanpa Qt")))

    assert qt_webengine.enable_shared_gl() is False


# ── terpasang di tempat QApplication benar-benar lahir ────────────────────

def test_the_ui_enables_it_before_creating_the_application():
    """Urutannya adalah keseluruhan perbaikannya."""
    import inspect

    from jarvis.ui import window

    source = inspect.getsource(window.JarvisUI)
    assert "enable_shared_gl" in source, "atributnya tidak pernah dipasang"
    assert source.index("enable_shared_gl") < source.index("QApplication("), (
        "atribut harus dipasang SEBELUM QApplication dibuat")
