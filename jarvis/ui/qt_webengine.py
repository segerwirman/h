"""Satu atribut Qt yang menghidupkan kembali browser tertanam (Fase 32, T4).

Boot melaporkan `core.browser DEGRADED — system browser ready; no embed
driver`, padahal PyQt6-WebEngine terpasang. Qt sendiri menyebutkan sebabnya::

    QtWebEngineWidgets must be imported or Qt.AA_ShareOpenGLContexts must be
    set before a QCoreApplication instance is created

**Ini bukan kosmetik.** ``jarvis/browser/agent_view.py`` dan
``jarvis/browser/embed.py`` mengimpor ``QWebEngineView`` secara *lazy* — yaitu
sesudah ``QApplication`` ada — sehingga importnya SELALU gagal di aplikasi yang
berjalan. Browser agent tertanam mati diam-diam, dan yang terlihat hanya satu
baris status yang terbaca seperti hal sepele. Itu kelas bug yang sama dengan
insiden utama dokumen fase: fitur mati tanpa mengeluarkan suara.

**Perbaikannya bukan mengimpor WebEngine lebih awal.** MK50 §7 sengaja
membuang QtWebEngine dari jalur boot dan ``tests/test_phase5_stage_home.py``
menjaga keputusan itu; menariknya kembali berarti memuat Chromium ~100 MB pada
setiap boot demi fitur yang jarang dipakai. Yang dipasang di sini hanyalah
atributnya — murah, tanpa memuat modul apa pun — sehingga import lazy-nya
berhasil ketika benar-benar dibutuhkan.
"""
from __future__ import annotations

from jarvis.core import log

_logger = log.get("ui.qt_webengine")

_enabled = False


def _set_attribute() -> bool:
    """Pasang ``AA_ShareOpenGLContexts``. ``False`` bila sudah terlambat."""
    from PyQt6.QtCore import QCoreApplication, Qt

    if QCoreApplication.instance() is not None:
        # Terlambat adalah terlambat: Qt membaca atribut ini saat aplikasi
        # dibuat. Mengembalikan True di sini akan berbohong tentang keadaan
        # yang sudah tidak bisa diubah.
        return False
    QCoreApplication.setAttribute(
        Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)
    return True


def enable_shared_gl() -> bool:
    """Panggil SEBELUM ``QApplication`` dibuat. Tidak pernah melempar."""
    global _enabled
    try:
        if _enabled:
            return True
        _enabled = _set_attribute()
        if _enabled:
            _logger.info("qt_webengine.shared_gl_enabled")
        else:
            _logger.warning(
                "qt_webengine.too_late",
                detail="QApplication sudah dibuat; browser tertanam akan "
                       "tetap tidak tersedia di proses ini")
        return _enabled
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("qt_webengine.unavailable", error=str(exc)[:120])
        return False


__all__ = ["enable_shared_gl"]
