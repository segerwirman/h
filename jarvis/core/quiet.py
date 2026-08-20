"""Kegagalan yang ditelan tetap meninggalkan jejak (Fase 35, S-32).

Audit 2026-08-08 menghitung 208 blok `except …: pass|continue` (ruff S110/S112).
Hanya 13% pembersihan yang sah; **48% adalah kegagalan sungguhan yang hilang
tanpa jejak**, dan 36% ada di jalur IO/jaringan — justru tempat kegagalan
paling mungkin terjadi dan paling perlu dilaporkan.

Ini akar yang sama dengan hampir setiap bug lapangan Siklus 2–5: S-1 (klaim
panggilan palsu), S-13 (thread bocor), S-22 (barge-in yang tak pernah memicu),
T4 (browser tertanam mati selama berbulan-bulan). Bukan bug-nya yang mahal,
melainkan **diamnya** — setiap kali penyebabnya butuh berjam-jam justru karena
tidak ada apa pun di log yang menunjuk ke sana.

Pemakaian::

    except Exception as exc:                    # noqa: BLE001
        quiet.swallowed("browser.close_failed", exc, session=session_id)

**Alur kendali tidak berubah.** Blok yang menelan tetap menelan; ia hanya
berhenti diam. Mengubah `pass` menjadi `raise` di 208 tempat sekaligus adalah
cara tercepat merusak aplikasi yang sedang bekerja.

**Dan bila ini membanjiri log, ia memindahkan masalah, bukan
menyelesaikannya.** Sebagian blok hidup di dalam loop ketat — callback mic
berjalan ~16 kali per detik. Karena itu tiap nama event diredam, dan yang
diredam **dihitung**: peredaman tanpa hitungan hanyalah bentuk baru dari diam.
"""
from __future__ import annotations

import threading
import time

from jarvis.core import log

_logger = log.get("core.quiet")
_lock = threading.Lock()

#: Satu event dicatat paling sering sekali per selang ini.
THROTTLE_S = 5.0
#: Pesan exception dipotong di sini — satu exception bertele-tele tidak boleh
#: menelan lognya sendiri.
MAX_ERROR_CHARS = 200
#: Nama event bisa dibangun dinamis; tabelnya tidak boleh tumbuh tanpa batas.
MAX_TRACKED = 512

#: nama event → [waktu emit terakhir, jumlah yang diredam sejak itu]
_seen: dict[str, list] = {}


def _describe(exc) -> str:
    if exc is None:
        return ""
    try:
        text = f"{type(exc).__name__}: {exc}"
    except Exception:                                        # noqa: BLE001
        return "exception yang tidak bisa dideskripsikan"
    return text[:MAX_ERROR_CHARS]


def _should_emit(event: str) -> int | None:
    """``None`` bila diredam; selain itu jumlah yang diredam sebelumnya."""
    now = time.monotonic()
    with _lock:
        entry = _seen.get(event)
        if entry is None:
            if len(_seen) >= MAX_TRACKED:
                # Buang yang paling lama tidak dipakai, bukan seluruh tabel:
                # mengosongkan semuanya membuat event yang sedang ramai
                # kehilangan hitungan redamnya.
                oldest = min(_seen, key=lambda key: _seen[key][0])
                _seen.pop(oldest, None)
            _seen[event] = [now, 0]
            return 0
        last, suppressed = entry
        if now - last >= THROTTLE_S:
            entry[0] = now
            entry[1] = 0
            return suppressed
        entry[1] = suppressed + 1
        return None


def swallowed(event, exc=None, **context) -> None:
    """Catat kegagalan yang sengaja ditelan. Tidak pernah melempar."""
    try:
        name = str(event or "unknown.swallowed")
        suppressed = _should_emit(name)
        if suppressed is None:
            return
        fields = {}
        for key, value in context.items():
            key = str(key)
            if key.isidentifier():
                fields[key] = value
        error = _describe(exc)
        if error:
            fields["error"] = error
        if suppressed:
            fields["suppressed"] = suppressed
        _logger.info(name, **fields)
    except Exception:                                        # noqa: BLE001
        # Helper pencatat yang melempar adalah kemunduran, bukan perbaikan.
        pass


def flush() -> None:
    """Terbitkan hitungan yang masih tertahan. Dipakai saat shutdown/diagnostik."""
    try:
        with _lock:
            pending = [(name, entry[1]) for name, entry in _seen.items()
                       if entry[1]]
            for name, _ in pending:
                _seen[name][0] = time.monotonic()
                _seen[name][1] = 0
        for name, suppressed in pending:
            _logger.info(name, suppressed=suppressed)
    except Exception as exc:                                # noqa: BLE001
        swallowed(
            "quiet.flush_emit_failed",
            exc,
        )


def tracked() -> int:
    with _lock:
        return len(_seen)


def reset() -> None:
    with _lock:
        _seen.clear()


__all__ = ["MAX_ERROR_CHARS", "MAX_TRACKED", "THROTTLE_S", "flush", "reset",
           "swallowed", "tracked"]
