"""Pengaman: Jarvis tidak boleh membunuh dirinya sendiri.

DIAGNOSIS_2 MASALAH 3 menemukan **tiga jalur bunuh-diri independen** dan
**nol penjaga** — `rg "getpid"` di seluruh kode non-tes mengembalikan nol
hasil:

1. ``actions/computer_settings.py:174`` ``close_app()`` — Alt+F4 buta ke
   jendela yang sedang fokus, dan jendela fokus sering kali Jarvis;
2. ``main.py:966`` ``shutdown_jarvis`` — tanpa konfirmasi, ``os._exit(0)``;
3. ``jarvis/core/target_resolver.py:133`` ``psutil.Process(pid).terminate()``
   tanpa membandingkan pid dengan ``os.getpid()``.

Modul ini adalah satu-satunya tempat keputusan "boleh dibunuh atau tidak"
dibuat.

**Fail-safe ke arah TIDAK MEMBUNUH.** Setiap keraguan — psutil hilang, pid
tak bisa dibaca, target tanpa identitas — dijawab "ini Jarvis, tolak". Salah
menolak hanya merepotkan; salah membunuh menghancurkan pekerjaan user di
tengah jalan.

Guard ini **tidak punya parameter bypass**. Tidak ada ``force``, tidak ada
``allow_self``. Satu-satunya cara Jarvis berhenti adalah jalur shutdown
eksplisit dengan konfirmasi user.
"""
from __future__ import annotations

import os
import sys
import threading
from pathlib import Path

from jarvis.core import log

_logger = log.get("core.process_guard")

# Nama proses yang tidak pernah boleh dibunuh lewat perintah "tutup aplikasi".
# "python"/"pythonw" ada di sini karena Jarvis SENDIRI berjalan sebagai
# python.exe — tanpa ini, "tutup python" adalah bunuh diri.
PROTECTED_NAMES = frozenset({"python", "pythonw", "python3", "pyw", "jarvis"})

# Kata yang berarti "Jarvis sendiri", apa pun bahasanya.
SELF_ALIASES = frozenset({"jarvis", "dirimu", "dirinya", "kamu", "yourself",
                          "asisten", "assistant"})

_CACHE_TTL_S = 2.0
_lock = threading.RLock()
_cached_pids: set[int] = set()
_cached_at: float = -1.0


class SelfTerminationBlocked(RuntimeError):
    """Target yang diminta adalah Jarvis sendiri (atau tidak bisa dipastikan)."""

    def __init__(self, target: object, reason: str) -> None:
        self.target = target
        self.reason = reason
        super().__init__(
            f"Ditolak: target '{target}' adalah Jarvis sendiri ({reason}). "
            f"Untuk mematikan Jarvis, minta secara eksplisit — "
            f"perintah menutup aplikasi tidak akan pernah melakukannya."
        )


def _now() -> float:
    import time
    return time.monotonic()


def own_pids() -> set[int]:
    """PID Jarvis sendiri + hanya anak Python/Jarvis yang kritis.

    Subsistem visi berjalan sebagai child Python dan tetap dilindungi. Browser
    Playwright juga child Jarvis, tetapi proses Chrome/Edge/Firefox bukan
    bagian inti Jarvis dan harus tetap dapat ditutup atas perintah user.

    Parent sengaja TIDAK dianggap bagian Jarvis. Jarvis dapat diluncurkan dari
    browser, terminal, IDE, atau launcher lain; melindungi parent secara buta
    pernah membuat ``close_app Chrome`` ditolak hanya karena Chrome kebetulan
    menjadi proses peluncur.

    Di-cache 2 detik: daftar anak berubah, tapi memindainya tiap panggilan
    membuat guard mahal justru di jalur panas.
    """
    global _cached_pids, _cached_at
    with _lock:
        if _cached_at >= 0 and (_now() - _cached_at) < _CACHE_TTL_S:
            return set(_cached_pids)

    pids = {os.getpid()}
    try:
        import psutil

        me = psutil.Process(os.getpid())
        try:
            for child in me.children(recursive=True):
                try:
                    child_name = _normalize(child.name())
                except Exception:                            # noqa: BLE001
                    # Child tanpa identitas tidak dimasukkan ke daftar target
                    # aplikasi oleh app_registry, jadi tidak perlu membuat
                    # seluruh browser kebal hanya karena inspeksi satu PID
                    # gagal.
                    continue
                if child_name in PROTECTED_NAMES:
                    pids.add(child.pid)
        except Exception:                                    # noqa: BLE001
            pass
    except Exception as exc:                                 # noqa: BLE001
        # ImportError is the common case, but a damaged/locked native psutil
        # package must not disable process actions or bypass protection.
        # Current PID remains protected even when child discovery is
        # temporarily unavailable.
        _logger.warning(
            "process_guard.psutil_unavailable",
            detail="hanya PID sendiri yang bisa dilindungi",
            error=type(exc).__name__,
        )

    with _lock:
        _cached_pids = set(pids)
        _cached_at = _now()
    return set(pids)


def own_process_names() -> set[str]:
    """Nama proses Jarvis sendiri, ternormalisasi."""
    names = {_normalize(Path(sys.executable).stem)}
    try:
        import psutil
        names.add(_normalize(psutil.Process(os.getpid()).name()))
    except Exception:                                        # noqa: BLE001
        pass
    names.discard("")
    return names


def _normalize(text: str) -> str:
    value = str(text or "").strip().lower()
    if value.endswith(".exe") or value.endswith(".app"):
        value = value.rsplit(".", 1)[0]
    return value


def is_self(pid: int | None = None, name: str | None = None) -> bool:
    """``True`` bila target ini Jarvis. **Ragu → True.**

    Dipanggil tanpa pid maupun name juga ``True``: target tanpa identitas
    tidak bisa dibuktikan aman, dan menebak di sini persis bug yang
    dilaporkan user.
    """
    if pid is None and not name:
        return True                                   # tak ada identitas → tolak

    if pid is not None:
        try:
            pid_int = int(pid)
        except (TypeError, ValueError):
            return True                               # pid tak terbaca → tolak
        if pid_int <= 0:
            return True
        if pid_int in own_pids():
            return True

    if name:
        key = _normalize(name)
        if not key:
            return True
        if key in SELF_ALIASES:
            return True
        if key in PROTECTED_NAMES:
            return True
        if key in own_process_names():
            return True
        # Nama yang MENGANDUNG nama proses kita (mis. "python3.11") juga
        # dianggap milik kita — lebih baik menolak daripada salah bunuh.
        for own in own_process_names():
            if own and (own in key or key in own):
                return True

    return False


def _extract(target: object) -> tuple[int | None, str | None]:
    """Ambil (pid, name) dari int, str, atau objek ber-atribut."""
    if target is None:
        return None, None
    if isinstance(target, bool):
        return None, None
    if isinstance(target, int):
        return target, None
    if isinstance(target, str):
        stripped = target.strip()
        if stripped.isdigit():
            return int(stripped), None
        return None, stripped
    pid = getattr(target, "pid", None)
    name = getattr(target, "name", None)
    if callable(name):
        try:
            name = name()
        except Exception:                                    # noqa: BLE001
            name = None
    if name is None:
        name = getattr(target, "window_title", None) or getattr(
            target, "title", None)
    try:
        pid = int(pid) if pid is not None else None
    except (TypeError, ValueError):
        pid = None
    return pid, (str(name) if name else None)


def assert_not_self(target: object) -> None:
    """Lempar ``SelfTerminationBlocked`` bila target adalah Jarvis.

    WAJIB dipanggil oleh **setiap** jalur yang bisa menghentikan proses,
    sebelum tindakan apa pun.
    """
    pid, name = _extract(target)
    if is_self(pid, name):
        reason = ("tanpa identitas" if pid is None and not name
                  else f"pid={pid} name={name}")
        _logger.warning("process_guard.blocked", pid=pid,
                        name=str(name)[:60], reason=reason[:80])
        raise SelfTerminationBlocked(target, reason)


def is_protected_name(name: str) -> bool:
    """Bantu UI/tool menjelaskan penolakan sebelum mencoba."""
    return _normalize(name) in PROTECTED_NAMES or _normalize(name) in SELF_ALIASES


def refers_to_jarvis(text: str) -> bool:
    """Apakah kalimat user menunjuk Jarvis sendiri, bukan aplikasi lain?

    Dipakai router/tool untuk mengarahkan "tutup jarvis" ke jalur shutdown
    yang berkonfirmasi, bukan ke close_app yang akan menolaknya.
    """
    words = {_normalize(w) for w in str(text or "").split()}
    return bool(words & SELF_ALIASES)


def _reset_cache_for_tests() -> None:
    global _cached_at
    with _lock:
        _cached_at = -1.0


__all__ = [
    "SelfTerminationBlocked", "PROTECTED_NAMES", "SELF_ALIASES",
    "own_pids", "own_process_names", "is_self", "assert_not_self",
    "is_protected_name", "refers_to_jarvis",
]
