"""Fase 35 — jadikan diam mustahil (S-32).

Audit 2026-08-08 menghitung 199 blok `except …: pass|continue` (ruff S110/S112
menghitung 208). Hanya 13% pembersihan yang sah; 48% adalah kegagalan sungguhan
yang hilang tanpa jejak, dan 36% ada di jalur IO/jaringan — justru tempat
kegagalan paling mungkin terjadi.

Ini akar yang sama dengan hampir setiap bug lapangan Siklus 2–5: S-1 (klaim
panggilan palsu), S-13 (thread bocor), S-22 (barge-in yang tak pernah memicu),
T4 (browser tertanam mati). Tiap fase memperbaikinya satu per satu; helper ini
menutup sisanya sekaligus.

**Batas keras fase ini: jangan mengubah alur kendali.** Blok yang hari ini
menelan tetap menelan — ia hanya berhenti diam. Mengubah `pass` menjadi `raise`
di 208 tempat sekaligus adalah cara tercepat merusak aplikasi yang bekerja.

**Dan kalau ia membanjiri log, ia memindahkan masalah, bukan
menyelesaikannya.** Karena itu peredamannya diuji di sini, bukan diserahkan
pada harapan.
"""
from __future__ import annotations

import json

from jarvis.core import quiet


def _events(caplog):
    out = []
    for record in caplog.records:
        try:
            out.append(json.loads(record.getMessage()))
        except (ValueError, TypeError):
            continue
    return out


# ── kegagalan meninggalkan jejak ──────────────────────────────────────────

def test_a_swallowed_failure_is_recorded(caplog):
    quiet.reset()
    with caplog.at_level("INFO"):
        try:
            raise ValueError("koneksi ditolak")
        except Exception as exc:                             # noqa: BLE001
            quiet.swallowed("browser.close_failed", exc)

    entry = [e for e in _events(caplog) if e.get("event") == "browser.close_failed"]
    assert entry, "kegagalan tetap hilang tanpa jejak"


def test_the_record_names_the_exception_type(caplog):
    """"gagal" tanpa jenisnya tidak bisa ditindaklanjuti."""
    quiet.reset()
    with caplog.at_level("INFO"):
        try:
            raise TimeoutError("tidak menjawab")
        except Exception as exc:                             # noqa: BLE001
            quiet.swallowed("relay.send_failed", exc)

    entry = [e for e in _events(caplog) if e.get("event") == "relay.send_failed"][0]
    assert entry["error"].startswith("TimeoutError")
    assert "tidak menjawab" in entry["error"]


def test_context_travels_with_the_record(caplog):
    quiet.reset()
    with caplog.at_level("INFO"):
        try:
            raise OSError("berkas terkunci")
        except Exception as exc:                             # noqa: BLE001
            quiet.swallowed("file.cleanup_failed", exc, path="c:/x", attempt=2)

    entry = [e for e in _events(caplog) if e.get("event") == "file.cleanup_failed"][0]
    assert entry["path"] == "c:/x"
    assert entry["attempt"] == 2


def test_it_works_without_an_exception(caplog):
    """Sebagian blok menelan tanpa mengikat exception-nya."""
    quiet.reset()
    with caplog.at_level("INFO"):
        quiet.swallowed("panel.teardown_skipped")

    assert [e for e in _events(caplog) if e.get("event") == "panel.teardown_skipped"]


def test_a_long_message_is_truncated(caplog):
    """Satu exception bertele-tele tidak boleh menelan lognya sendiri."""
    quiet.reset()
    with caplog.at_level("INFO"):
        try:
            raise RuntimeError("x" * 5000)
        except Exception as exc:                             # noqa: BLE001
            quiet.swallowed("tool.failed", exc)

    entry = [e for e in _events(caplog) if e.get("event") == "tool.failed"][0]
    assert len(entry["error"]) <= quiet.MAX_ERROR_CHARS + 40


# ── tidak boleh membanjiri log ────────────────────────────────────────────

def test_a_repeating_failure_is_throttled(caplog):
    """Blok di dalam loop ketat bisa memicu ribuan kali per detik.

    Log yang membanjir sama tidak terbacanya dengan log yang sunyi.
    """
    quiet.reset()
    with caplog.at_level("INFO"):
        for _ in range(500):
            quiet.swallowed("mic.block_dropped")

    entries = [e for e in _events(caplog) if e.get("event") == "mic.block_dropped"]
    assert 1 <= len(entries) <= 3, f"{len(entries)} entri untuk 500 kegagalan"


def test_the_suppressed_count_is_reported(caplog):
    """Yang diredam harus TERHITUNG, bukan lenyap — kalau tidak, peredamannya
    sendiri menjadi bentuk baru dari diam."""
    quiet.reset()
    with caplog.at_level("INFO"):
        for _ in range(50):
            quiet.swallowed("mic.block_dropped")
        quiet.flush()

    entries = [e for e in _events(caplog) if e.get("event") == "mic.block_dropped"]
    assert any(e.get("suppressed", 0) > 0 for e in entries), entries


def test_different_events_are_throttled_independently(caplog):
    quiet.reset()
    with caplog.at_level("INFO"):
        for _ in range(20):
            quiet.swallowed("a.failed")
            quiet.swallowed("b.failed")

    events = {e.get("event") for e in _events(caplog)}
    assert "a.failed" in events and "b.failed" in events


def test_the_throttle_table_is_bounded():
    """Nama event yang dibangun dinamis bisa tumbuh tanpa batas."""
    quiet.reset()
    for number in range(quiet.MAX_TRACKED + 200):
        quiet.swallowed(f"dinamis.{number}")

    assert quiet.tracked() <= quiet.MAX_TRACKED


# ── helper-nya sendiri tidak boleh jadi sumber kegagalan ──────────────────

def test_it_never_raises_on_junk():
    quiet.reset()
    quiet.swallowed(None)
    quiet.swallowed(12, "bukan exception")
    quiet.swallowed("x", object())
    quiet.swallowed("y", ValueError("v"), **{"argumen tak wajar": object()})


def test_it_never_raises_when_logging_itself_fails(monkeypatch):
    """Helper pencatat yang melempar adalah kemunduran, bukan perbaikan."""
    quiet.reset()

    def boom(*_args, **_kwargs):
        raise RuntimeError("log mati")

    monkeypatch.setattr(quiet._logger, "info", boom)

    quiet.swallowed("apa.saja", ValueError("v"))


def test_control_flow_is_unchanged():
    """Batas keras fase ini: blok yang menelan tetap menelan."""
    reached = []
    try:
        raise ValueError("x")
    except Exception as exc:                                 # noqa: BLE001
        quiet.swallowed("uji.alur", exc)
    reached.append("sesudah")

    assert reached == ["sesudah"]


# ── penegakan oleh mesin, bukan ingatan ───────────────────────────────────

def test_ruff_forbids_silent_swallowing():
    """Aturannya harus AKTIF, kalau tidak ia cuma niat baik."""
    import tomllib
    from pathlib import Path

    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    selected = config["tool"]["ruff"]["lint"]["select"]

    assert "S110" in selected, "try-except-pass tidak ditegakkan"
    assert "S112" in selected, "try-except-continue tidak ditegakkan"


def test_the_remaining_debt_is_listed_not_hidden():
    """Utang yang tersisa didaftarkan per berkas — sama seperti E722 dulu.

    Dengan begitu pelanggaran BARU di berkas mana pun tetap membuat CI merah,
    sementara yang lama dikerjakan bertahap.
    """
    import tomllib
    from pathlib import Path

    config = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    ignores = config["tool"]["ruff"]["lint"]["per-file-ignores"]
    listed = [path for path, rules in ignores.items()
              if "S110" in rules or "S112" in rules]

    assert listed, "tidak ada utang terdaftar — apakah semuanya sudah bersih?"
    for path in listed:
        assert Path(path.replace("\\", "/")).exists() or "*" in path, path
