"""Inter-process poller lease (Telegram getUpdates single-owner).

Latar: log produksi memperlihatkan
``telegram.error.Conflict: terminated by other getUpdates request`` — dua
proses OS mem-polling token bot yang sama. python-telegram-bot tidak bisa
membedakan "konflik jaringan" dari "proses kedua milik kita", jadi pemilik
tunggal harus disepakati **sebelum** ``run_polling()`` dimulai.

Mekanisme: lockfile create-exclusive di direktori data. Proses pertama yang
menciptakan file memegang lease; proses kedua gagal cepat (``lease_held``)
tanpa retry storm. Lease milik PID yang terverifikasi mati boleh langsung
diambil alih; bila liveness tidak dapat dipastikan, takeover baru boleh setelah
umur lease melewati batas. Lease milik proses hidup tidak pernah dicuri.

KEAMANAN: metadata lease hanya berisi PID, incarnation proses, dan timestamp
non-rahasia untuk stale detection — **tidak pernah** token bot, string turunan
token, atau URL ber-token.

Injeksi: ``PollerLease`` menerima pemilik path, pemeriksa PID, jam, dan
umur-staleness — semua fake-able untuk test offline tanpa filesystem nyata.
"""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path

from jarvis.core import log

_logger = log.get("integrations.poller_lease")

#: Umur maksimum (detik) lease sebelum dianggap basi bila PID-nya sudah
#: tidak bisa diverifikasi hidup. Default 12 jam — cukup untuk restart
#: mesin, cukup pendek agar sampah tidak mengunci polling selamanya.
DEFAULT_STALE_SECONDS = 12 * 3600


@dataclass(frozen=True)
class LeaseAcquireResult:
    """Hasil ``PollerLease.acquire`` — status + lease opsional + alasan."""

    acquired: bool
    lease: "PollerLease | None"
    reason: str  # "acquired" | "lease_held" | "stale_taken_over" | "io_error"


class PollerLease:
    """Satu lease polling antar-proses berbasis lockfile create-exclusive.

    Semua dependensi eksternal (path, PID, jam) diinjeksi supaya test
    offline bisa memalsukannya; produksi memakai default nyata.
    """

    def __init__(
        self,
        path: Path,
        *,
        incarnation: str,
        pid_fn=os.getpid,
        now_fn=time.time,
        alive_fn=None,
        stale_seconds: float = DEFAULT_STALE_SECONDS,
    ) -> None:
        self._path = Path(path)
        self._incarnation = str(incarnation)
        self._pid_fn = pid_fn
        self._now_fn = now_fn
        self._alive_fn = alive_fn if alive_fn is not None else _default_alive
        self._stale_seconds = float(stale_seconds)
        self._held = False

    # ── properti status ──────────────────────────────────────────────────

    @property
    def held(self) -> bool:
        return self._held

    @property
    def path(self) -> Path:
        return self._path

    # ── pembacaan metadata lease di disk ─────────────────────────────────

    def _read_meta(self) -> dict | None:
        """None = file tidak ada; {} = ada tapi tak terbaca; dict = parse."""
        try:
            raw = self._path.read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        except OSError:
            return {}
        # Format: baris "k=v" sederhana; token TIDAK PERNAH ada di sini.
        meta: dict[str, str] = {}
        for line in raw.splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                meta[key.strip()] = value.strip()
        # Garbage total (tanpa k=v valid dan tanpa pid) → tidak valid.
        if not meta or "pid" not in meta:
            return {}
        return meta

    def _pid_alive(self, pid: int) -> bool:
        return self._alive_fn(pid)

    # ── akuisisi ─────────────────────────────────────────────────────────

    def acquire(self) -> LeaseAcquireResult:
        """Coba pegang lease. Fail closed: keraguan = tidak acquire."""
        if self._held:
            return LeaseAcquireResult(True, self, "acquired")
        pid = int(self._pid_fn())
        meta = self._read_meta()
        taken_over = False
        if meta is None:
            # Tidak ada file → langsung create-exclusive di bawah.
            pass
        elif meta == {}:
            # File ada tapi tak terbaca/invalid — jangan asumsikan basi.
            return LeaseAcquireResult(False, None, "lease_held")
        else:
            other_alive = self._other_holder_alive(meta)
            age = self._meta_age(meta)
            if other_alive is True:
                return LeaseAcquireResult(False, None, "lease_held")
            if other_alive is None and age < self._stale_seconds:
                # PID tidak bisa diverifikasi dan lease masih muda —
                # fail closed supaya tidak mengambil alih proses hidup.
                return LeaseAcquireResult(False, None, "lease_held")
            # Pemilik terverifikasi mati (lease pasti terlantar — aman
            # ambil alih tanpa syarat umur) atau tak terverifikasi dan
            # sudah melewati batas stale: ambil alih.
            self._unlink()
            taken_over = True
            _logger.info("poller_lease.taken_over",
                         previous_age_s=round(age, 1))

        # Create-exclusive: hanya satu proses di OS yang berhasil.
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # O_EXCL pada Windows bekerja lewat O_CREAT|O_EXCL di CRT.
            fd = os.open(str(self._path),
                         os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError:
            # Balapan antar-proses: pemenang baru saja create.
            return LeaseAcquireResult(False, None, "lease_held")
        except OSError as exc:
            _logger.warning("poller_lease.io_error",
                            error=type(exc).__name__)
            return LeaseAcquireResult(False, None, "io_error")
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            # KEAMANAN: hanya PID + incarnation + timestamp. Tanpa token.
            fh.write(f"pid={pid}\nincarnation={self._incarnation}\n"
                     f"written={self._now_fn()}\n")
        self._held = True
        _logger.info("poller_lease.acquired", pid=pid)
        reason = "stale_taken_over" if taken_over else "acquired"
        return LeaseAcquireResult(True, self, reason)

    def _other_holder_alive(self, meta: dict) -> bool | None:
        """True/False bila bisa dipastikan; None bila tidak pasti."""
        try:
            pid = int(str(meta.get("pid", "")))
        except (TypeError, ValueError):
            return False  # metadata rusak → lease tidak valid → basi
        return self._pid_alive(pid)

    def _meta_age(self, meta: dict) -> float:
        """Umur lease dari timestamp ``written`` di metadata (bukan mtime
        filesystem — jam injectable test bisa jauh dari jam nyata)."""
        try:
            written = float(str(meta.get("written", "")))
        except (TypeError, ValueError):
            return float("inf")  # tanpa timestamp → anggap tua (basi)
        return max(0.0, self._now_fn() - written)

    def _unlink(self) -> None:
        try:
            self._path.unlink(missing_ok=True)
        except OSError:
            pass

    # ── pelepasan ────────────────────────────────────────────────────────

    def release(self) -> None:
        """Lepas lease: verifikasi pemilik masih kita, lalu hapus file."""
        if not self._held:
            return
        meta = self._read_meta()
        if meta is None:
            # File sudah hilang — lease kita sudah tidak ada; turunkan
            # tangan tanpa menghapus apa pun.
            self._held = False
            return
        mine = meta != {} and str(meta.get("incarnation", "")) == \
            self._incarnation
        if not mine:
            # Lease sudah diambil alih / file invalid — jangan hapus
            # milik pihak lain; cukup turunkan tangan.
            self._held = False
            return
        self._unlink()
        self._held = False
        _logger.info("poller_lease.released")


def _default_alive(pid: int) -> bool:
    """Pemeriksa PID produksi — cross-platform, fail closed (anggap hidup)."""
    if pid <= 0:
        return False
    if os.name == "nt":
        return _windows_pid_alive(pid)
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # Proses ada tapi milik user lain — anggap hidup (jangan curi).
        return True
    except OSError:
        return True


def _windows_pid_alive(pid: int) -> bool:
    """Fallback pemeriksaan PID di Windows tanpa psutil."""
    if pid <= 0:
        return False
    # os.kill(pid, 0) di Windows melempar OSError untuk proses hidup
    # milik user yang sama kadang-jadi-kadang; gunakan OpenProcess ringan
    # via ctypes bila tersedia, else anggap hidup (fail closed).
    try:
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        STILL_ACTIVE = 259
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.OpenProcess(
            PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not handle:
            return False
        try:
            exit_code = ctypes.c_ulong()
            if kernel32.GetExitCodeProcess(handle, ctypes.byref(exit_code)):
                return exit_code.value == STILL_ACTIVE
            return True  # tak bisa query — anggap hidup (jangan curi)
        finally:
            kernel32.CloseHandle(handle)
    except Exception:                                    # noqa: BLE001
        return True


def default_lease_path() -> Path:
    """Lokasi lockfile standar: ``<data>/telegram_poller.lease``."""
    from jarvis.agent.paths import data_dir
    return data_dir() / "telegram_poller.lease"


def process_incarnation() -> str:
    """Inkarnasi proses — dibuat SEKALI per proses (bukan per panggilan).

    Sengaja TIDAK memakai ``TaskLedger.process_incarnation()``: fungsi itu
    menghitung ulang timestamp tiap panggilan sehingga dua pemanggil di
    proses sama mendapat nilai berbeda. Lease butuh nilai konstan agar
    ``release`` bisa memverifikasi pemilik.
    """
    global _INCARNATION
    try:
        return _INCARNATION
    except NameError:
        _INCARNATION = f"{os.getpid()}-{time.time_ns()}"
        return _INCARNATION


def acquire_default(name: str = "telegram") -> LeaseAcquireResult:
    """Convenience produksi: lease dengan path/incarnation default."""
    return PollerLease(
        default_lease_path(),
        incarnation=process_incarnation(),
    ).acquire()
