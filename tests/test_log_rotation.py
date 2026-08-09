"""Fase 37 — rotasi log + pisahkan kanal bukti (S-35).

`logs/jarvis.log` tumbuh 39 MB / 200 ribu baris dalam empat minggu tanpa batas.
Itu bukan soal kebersihan disk: seluruh metode kerja dokumen fase bersandar
pada log sebagai **bukti**, dan Fase 35 baru saja menambah 32 titik yang
bersuara ke sana. Kanal bukti yang tumbuh tanpa batas berhenti bisa dibaca
tepat ketika paling dibutuhkan.

**Pengukuran mengubah rancangan fase ini.** `RotatingFileHandler` polos adalah
jawaban yang salah di sini, dan itu diukur, bukan didebatkan::

    berkas hasil : ['probe.log']
    rotasi gagal : True (36x dari 40)
    ukuran utama : 168 byte  (seharusnya ~1600)

Subsistem visi berjalan sebagai ``multiprocessing.Process`` terpisah dan
menulis berkas log yang SAMA. Di Windows, rotasi melakukan ``os.rename`` pada
berkas yang masih dipegang proses lain; renamenya gagal, `handleError`
dipanggil, dan **barisnya hilang sama sekali**. Rotasi naif berarti Jarvis
diam-diam membuang log justru saat visi hidup.

Karena itu: **satu penulis per berkas** lebih dulu, baru rotasi.
"""
from __future__ import annotations

import logging
import logging.handlers
import multiprocessing
from pathlib import Path

import pytest

from jarvis.core import log


# ── satu penulis per berkas ───────────────────────────────────────────────

def test_the_main_process_keeps_the_plain_name(monkeypatch):
    monkeypatch.setattr(log, "is_test_run", lambda: False)
    monkeypatch.setattr(multiprocessing, "current_process",
                        lambda: type("P", (), {"name": "MainProcess"})())

    assert log.active_log_path().name == "jarvis.log"


def test_a_child_process_writes_its_own_file(monkeypatch):
    """Dua penulis pada satu berkas membuat rotasi MEMBUANG baris (diukur)."""
    monkeypatch.setattr(log, "is_test_run", lambda: False)
    monkeypatch.setattr(multiprocessing, "current_process",
                        lambda: type("P", (), {"name": "jarvis-vision"})())

    assert log.active_log_path().name == "jarvis-vision.log"


def test_a_child_process_name_is_made_safe_for_a_filename(monkeypatch):
    """Nama proses bisa memuat karakter yang tidak sah untuk nama berkas."""
    monkeypatch.setattr(log, "is_test_run", lambda: False)
    monkeypatch.setattr(multiprocessing, "current_process",
                        lambda: type("P", (), {"name": "Proc" + chr(92) + "1/aneh:x*?"})())

    name = log.active_log_path().name
    assert not any(ch in name for ch in '/\\:*?"<>|')


def test_the_test_log_stays_separate(monkeypatch):
    """§22 — pemisahan log uji itu yang membuat S-22 bisa dipecahkan."""
    monkeypatch.setattr(log, "is_test_run", lambda: True)
    monkeypatch.setattr(multiprocessing, "current_process",
                        lambda: type("P", (), {"name": "MainProcess"})())

    assert "test" in log.active_log_path().name


def test_naming_never_raises_without_a_process_name(monkeypatch):
    monkeypatch.setattr(multiprocessing, "current_process",
                        lambda: type("P", (), {"name": None})())

    assert log.active_log_path().name.endswith(".log")


# ── rotasi yang benar-benar membatasi ─────────────────────────────────────

def test_the_handler_rotates(tmp_path, monkeypatch):
    handler = log.build_handler(tmp_path / "x.log")

    assert isinstance(handler, logging.handlers.RotatingFileHandler)
    assert handler.maxBytes > 0
    assert handler.backupCount > 0
    handler.close()


def test_the_total_size_is_bounded(tmp_path):
    """Batasnya harus nyata, bukan niat."""
    handler = log.build_handler(tmp_path / "x.log", max_bytes=2_000,
                                backup_count=2)
    logger = logging.getLogger("uji.rotasi.batas")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for index in range(500):
        logger.info("baris %d %s", index, "y" * 80)
    handler.close()

    total = sum(p.stat().st_size for p in tmp_path.glob("x.log*"))
    assert total <= 2_000 * (2 + 1) * 1.2, total


def test_rotation_keeps_the_recent_entries(tmp_path):
    """Membatasi bukan berarti membuang yang barusan ditulis.

    Ini pembeda antara rotasi dan pemangkasan: yang lama boleh hilang, yang
    baru tidak.
    """
    handler = log.build_handler(tmp_path / "x.log", max_bytes=1_000,
                                backup_count=3)
    logger = logging.getLogger("uji.rotasi.terbaru")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False

    for index in range(300):
        logger.info("penanda-%03d", index)
    handler.close()

    text = "".join(p.read_text(encoding="utf-8", errors="replace")
                   for p in sorted(tmp_path.glob("x.log*")))
    assert "penanda-299" in text, "entri terakhir hilang"
    assert "penanda-298" in text


def test_the_limits_come_from_config(tmp_path, monkeypatch):
    monkeypatch.setattr(log.config, "get",
                        lambda path, default=None:
                        {"logging.max_bytes": 4096,
                         "logging.backup_count": 7}.get(path, default))

    handler = log.build_handler(tmp_path / "x.log")

    assert handler.maxBytes == 4096
    assert handler.backupCount == 7
    handler.close()


def test_absurd_limits_are_clamped(tmp_path, monkeypatch):
    """maxBytes=0 berarti TIDAK PERNAH berotasi — yaitu keadaan hari ini."""
    monkeypatch.setattr(log.config, "get",
                        lambda path, default=None:
                        {"logging.max_bytes": 0,
                         "logging.backup_count": -3}.get(path, default))

    handler = log.build_handler(tmp_path / "x.log")

    assert handler.maxBytes > 0
    assert handler.backupCount >= 1
    handler.close()


def test_building_a_handler_never_raises_on_a_bad_path(tmp_path):
    """Log yang gagal disiapkan tidak boleh menjatuhkan boot."""
    assert log.build_handler(tmp_path / "tidak-ada" / "x.log") is not None


# ── kanal bukti yang harus awet ───────────────────────────────────────────

def test_audit_jsonl_is_not_touched_by_rotation(tmp_path):
    """`*_audit.jsonl` adalah jejak yang harus bertahan.

    Ia ditulis langsung, bukan lewat `logging` — dan fase ini tidak boleh
    diam-diam menariknya ke dalam rotasi.
    """
    audit = tmp_path / "window_controls_audit.jsonl"
    audit.write_text('{"a": 1}\n', encoding="utf-8")

    handler = log.build_handler(tmp_path / "jarvis.log", max_bytes=500,
                                backup_count=1)
    logger = logging.getLogger("uji.audit.utuh")
    logger.handlers = [handler]
    logger.setLevel(logging.INFO)
    logger.propagate = False
    for _ in range(200):
        logger.info("z" * 100)
    handler.close()

    assert audit.read_text(encoding="utf-8") == '{"a": 1}\n'


def test_the_audit_writers_do_not_go_through_logging():
    """Kalau mereka lewat `logging`, rotasi akan memangkas bukti."""
    import inspect

    from jarvis.core import target_resolver, window_controls

    for module in (target_resolver, window_controls):
        source = inspect.getsource(module)
        index = source.find("_audit.jsonl")
        assert index > 0, module.__name__
        window = source[max(0, index - 400):index + 400]
        assert "_logger.info" not in window or "open(" in window


# ── keadaan nyata setelah fase ini ────────────────────────────────────────

def test_the_real_setup_uses_a_bounded_handler():
    """Diperiksa pada logger yang sungguhan, bukan tiruan.

    Disaring ke handler yang benar-benar menulis BERKAS LOG kita: pytest
    memasang penangkapnya sendiri yang juga turunan `FileHandler` tetapi
    mengarah ke perangkat null, dan menghitungnya membuat uji ini gagal karena
    hal yang sama sekali bukan urusannya.
    """
    log.setup()
    target = log.active_log_path().name
    root = logging.getLogger("jarvis")
    ours = [h for h in root.handlers
            if str(getattr(h, "baseFilename", "")).endswith(target)]

    assert ours, f"tidak ada handler untuk {target}"
    plain = [h for h in ours
             if not isinstance(h, logging.handlers.RotatingFileHandler)]
    assert not plain, [
        (type(h).__name__, getattr(h, "baseFilename", "")) for h in plain]


def test_rotation_is_documented_as_needing_one_writer():
    """Pengetahuan yang mahal didapat harus tinggal di kodenya.

    36 dari 40 baris HILANG ketika dua proses memegang satu berkas. Siapa pun
    yang kelak menyatukan kembali berkasnya harus menemukan alasannya di sini.
    """
    import inspect

    source = inspect.getsource(log)
    lowered = source.lower()

    assert "rename" in lowered or "proses" in lowered
    assert "rotat" in lowered
