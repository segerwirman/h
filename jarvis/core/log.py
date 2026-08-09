"""Structured logging — structlog to file + EventBus → in-UI activity panel.

§37 (S-35) — lognya berotasi, dan **satu berkas hanya boleh punya satu
penulis**. Urutan itu penting, dan alasannya diukur, bukan didebatkan:

    berkas hasil : ['probe.log']
    rotasi gagal : True (36 dari 40)
    ukuran utama : 168 byte  (seharusnya ~1600)

Subsistem visi berjalan sebagai ``multiprocessing.Process`` terpisah. Di
Windows, rotasi melakukan ``os.rename`` pada berkas yang masih dipegang proses
lain; rename-nya gagal, ``handleError`` dipanggil, dan **barisnya hilang sama
sekali**. Rotasi naif di atas satu berkas bersama berarti Jarvis diam-diam
membuang log justru saat visi hidup.

Karena itu setiap proses anak menulis berkasnya sendiri
(``jarvis-vision.log``), dan barulah rotasinya aman. Siapa pun yang kelak ingin
menyatukan kembali berkas-berkas ini harus membaca paragraf di atas lebih dulu.

Berkas ``*_audit.jsonl`` sengaja TIDAK lewat ``logging``: ia jejak yang harus
awet, dan rotasi akan memangkasnya.
"""
from __future__ import annotations

import logging
import logging.handlers
import multiprocessing
import os
from pathlib import Path

from jarvis.core import config
from jarvis.core.bus import BUS

try:
    import structlog
    _HAS_STRUCTLOG = True
except ImportError:          # graceful degradation — stdlib logging only
    structlog = None
    _HAS_STRUCTLOG = False

_configured = False


def _bus_processor(logger, method_name, event_dict):
    BUS.publish(
        "log",
        level=method_name.upper(),
        source=event_dict.get("source", "core"),
        message=event_dict.get("event", ""),
        extra={k: v for k, v in event_dict.items()
               if k not in ("event", "source", "timestamp", "level")},
    )
    return event_dict


def is_test_run() -> bool:
    """Apakah proses ini dijalankan oleh pytest?

    S-22: suite menulis ke log produksi yang sama, sehingga
    ``barge_in.triggered`` dari test tidak bisa dibedakan dari ucapan user.
    Diagnosis runtime jadi tebakan — dan sempat hampir menyesatkan kesimpulan
    seluruh fase. Deteksi lewat modul yang benar-benar dimuat, bukan variabel
    lingkungan yang bisa terbawa ke proses anak.
    """
    import sys

    return "pytest" in sys.modules or "PYTEST_CURRENT_TEST" in os.environ


#: Batas bawaan. 10 MB × (5 + 1) = 60 MB langit-langit — dibandingkan 39 MB
#: dan terus tumbuh sebelum fase ini.
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5

#: Dinyatakan sebagai HIMPUNAN karakter, bukan kelas regex. Bentuk regexnya
#: sempat salah tanpa terlihat: di dalam `[...]`, `\:` hanya berarti `:`,
#: sehingga backslash — karakter pemisah path di Windows — justru tidak ikut
#: dibersihkan. Himpunan tidak punya jebakan escape.
_UNSAFE_NAME_CHARS = frozenset('/\\:*?"<>|' + " \t\r\n")


def _process_suffix() -> str:
    """Penanda proses untuk nama berkas; kosong untuk proses utama.

    Satu berkas, satu penulis — lihat docstring modul. Ini bukan kosmetik:
    tanpa pemisahan ini rotasi MEMBUANG baris log.
    """
    try:
        name = str(multiprocessing.current_process().name or "")
    except Exception:                                        # noqa: BLE001
        return ""
    if not name or name == "MainProcess":
        return ""
    cleaned = "".join("-" if ch in _UNSAFE_NAME_CHARS else ch
                      for ch in name).strip("-").lower()
    cleaned = cleaned.removeprefix("jarvis-")
    return f"-{cleaned}" if cleaned else ""


def active_log_path():
    """Berkas log yang akan ditulis proses ini."""
    log_dir = config.resolve_path(config.get("logging.dir", "logs"))
    name = str(config.get("logging.file", "jarvis.log"))
    if is_test_run():
        name = str(config.get("logging.test_file", "jarvis-test.log"))
    suffix = _process_suffix()
    if suffix:
        stem, dot, ext = name.rpartition(".")
        name = f"{stem or name}{suffix}{dot}{ext}" if dot else f"{name}{suffix}"
    return log_dir / name


def build_handler(path, max_bytes: int | None = None,
                  backup_count: int | None = None):
    """Handler berkas yang BERBATAS. Tidak pernah melempar ke pemanggil."""
    if max_bytes is None:
        try:
            max_bytes = int(config.get("logging.max_bytes", DEFAULT_MAX_BYTES))
        except (TypeError, ValueError):
            max_bytes = DEFAULT_MAX_BYTES
    if backup_count is None:
        try:
            backup_count = int(config.get("logging.backup_count",
                                          DEFAULT_BACKUP_COUNT))
        except (TypeError, ValueError):
            backup_count = DEFAULT_BACKUP_COUNT
    # maxBytes=0 berarti TIDAK PERNAH berotasi — yaitu keadaan sebelum fase
    # ini. Angka yang mustahil dijepit, bukan dituruti.
    max_bytes = max(1024, int(max_bytes))
    backup_count = max(1, int(backup_count))
    try:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        return logging.handlers.RotatingFileHandler(
            path, maxBytes=max_bytes, backupCount=backup_count,
            encoding="utf-8", delay=True)
    except Exception:                                        # noqa: BLE001
        # Log yang gagal disiapkan tidak boleh menjatuhkan boot.
        return logging.NullHandler()


def setup() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    log_dir = config.resolve_path(config.get("logging.dir", "logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = active_log_path()
    level = getattr(logging, config.get("logging.level", "INFO"), logging.INFO)

    handler = build_handler(log_file)
    handler.setFormatter(logging.Formatter("%(message)s"))
    root = logging.getLogger("jarvis")
    root.setLevel(level)
    root.addHandler(handler)
    root.propagate = False

    if _HAS_STRUCTLOG:
        structlog.configure(
            processors=[
                structlog.processors.TimeStamper(fmt="iso"),
                structlog.processors.add_log_level,
                _bus_processor,
                structlog.processors.JSONRenderer(),
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
        )


def get(source: str = "core"):
    """Return a bound logger. Works with or without structlog installed."""
    setup()
    if _HAS_STRUCTLOG:
        return structlog.get_logger("jarvis").bind(source=source)
    return _FallbackLogger(source)


class _FallbackLogger:
    def __init__(self, source: str):
        self._source = source
        self._log = logging.getLogger("jarvis")

    def _emit(self, level: str, event: str, **kw):
        self._log.log(getattr(logging, level.upper(), logging.INFO),
                      f"[{self._source}] {event} {kw if kw else ''}")
        BUS.publish("log", level=level.upper(), source=self._source,
                    message=event, extra=kw)

    def info(self, event, **kw):    self._emit("INFO", event, **kw)
    def warning(self, event, **kw): self._emit("WARNING", event, **kw)
    def error(self, event, **kw):   self._emit("ERROR", event, **kw)
    def debug(self, event, **kw):   self._emit("DEBUG", event, **kw)
