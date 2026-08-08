"""Fase 33 — memori semantik: hidup, atau mati dengan jujur (T5).

T5 tercatat: *"`memory.faiss_missing` muncul di setiap boot; memori semantik
nonaktif... satu fitur mati diam-diam."*

**Pengukuran membantah separuh temuan itu.** Ada DUA penyimpanan memori:

* `jarvis/agent/memory_store.py` — SQLite + FTS5 + embedding, cosine
  in-memory, tanpa FAISS sama sekali. Diukur di mesin Takeda: **298 dari 298**
  baris punya embedding.
* `jarvis/core/memory.py` — indeks vektor lama yang memang memakai FAISS.
  Berkas `data/memory.faiss` bahkan tidak pernah ada.

Jadi peringatannya berbunyi *"Semantic memory disabled"* padahal memori
semantik yang benar-benar dipakai agent hidup sepenuhnya. Itu melebih-lebihkan
kerugiannya — kelas kesalahan yang sama dengan klaim palsu yang diberantas
Siklus 2, hanya arahnya terbalik: bukan sukses palsu, melainkan kegagalan
palsu.

Fase ini tidak memasang FAISS. Ia membuat keadaannya **tepat** dan
**terlihat**.
"""
from __future__ import annotations

import json


def _events(caplog):
    out = []
    for record in caplog.records:
        try:
            out.append(json.loads(record.getMessage()))
        except (ValueError, TypeError):
            continue
    return out


# ── pesannya tidak boleh melebih-lebihkan kerugiannya ─────────────────────

def test_the_warning_no_longer_claims_semantic_memory_is_disabled():
    """298 dari 298 memori agent punya embedding. Mengatakan memori semantik
    mati adalah kegagalan palsu — sama merusaknya dengan sukses palsu.
    """
    from jarvis.core import memory

    assert "disabled" not in memory.FAISS_MISSING_DETAIL.lower()
    assert "nonaktif" in memory.FAISS_MISSING_DETAIL


def test_the_warning_names_what_is_actually_off():
    from jarvis.core import memory

    assert "memory_store" in memory.FAISS_MISSING_DETAIL, (
        "pesannya harus menunjuk penyimpanan yang MASIH bekerja")
    assert "core.memory" in memory.FAISS_MISSING_DETAIL, (
        "dan menyebut persisnya apa yang mati")


# ── keadaannya terlihat di tempat Takeda benar-benar melihat ──────────────

def test_memory_is_one_of_the_boot_subsystems():
    """Satu baris peringatan di log 41 MB bukan "terlihat"."""
    from jarvis.core import boot

    assert "core.memory" in boot._CHECKS


def test_the_boot_check_counts_real_rows(monkeypatch):
    from jarvis.core import boot

    monkeypatch.setattr(boot, "_memory_counts", lambda: (298, 298))

    result = boot._check_memory()

    assert result.ok is True
    assert "298" in result.detail


def test_memory_without_embeddings_is_degraded_not_silent(monkeypatch):
    from jarvis.core import boot

    monkeypatch.setattr(boot, "_memory_counts", lambda: (120, 0))

    result = boot._check_memory()

    assert result.ok is True
    assert result.degraded is True
    assert "0" in result.detail


def test_an_empty_memory_is_reported_as_empty_not_broken(monkeypatch):
    """Memori kosong pada pemasangan baru bukan kerusakan."""
    from jarvis.core import boot

    monkeypatch.setattr(boot, "_memory_counts", lambda: (0, 0))

    result = boot._check_memory()

    assert result.ok is True
    assert result.degraded is False


def test_an_unreadable_store_is_reported_as_failed(monkeypatch):
    """Tidak bisa dibaca bukan sama dengan kosong."""
    from jarvis.core import boot

    def boom():
        raise sqlite_error()

    monkeypatch.setattr(boot, "_memory_counts", boom)

    result = boot._check_memory()

    assert result.ok is False


def test_the_check_never_raises(monkeypatch):
    from jarvis.core import boot

    monkeypatch.setattr(boot, "_memory_counts",
                        lambda: (_ for _ in ()).throw(RuntimeError("x")))

    assert boot._check_memory().ok is False


def test_counts_come_from_the_store_that_is_actually_used(tmp_path, monkeypatch):
    """Menghitung indeks FAISS yang tidak pernah ada tidak memberi tahu apa pun.

    Diuji terhadap basis data sungguhan, bukan terhadap teks sumbernya.
    """
    import sqlite3

    from jarvis.agent import paths
    from jarvis.core import boot

    database = tmp_path / "agent.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("CREATE TABLE memories (id INTEGER PRIMARY KEY, "
                       "embedding BLOB)")
    connection.executemany("INSERT INTO memories (embedding) VALUES (?)",
                           [(b"x",), (b"y",), (None,)])
    connection.commit()
    connection.close()
    monkeypatch.setattr(paths, "db_path", lambda: database)

    assert boot._memory_counts() == (3, 2)

    result = boot._check_memory()
    assert result.degraded is True
    assert "2/3" in result.detail


def test_the_real_store_reports_without_raising():
    """Dijalankan terhadap basis data yang sungguhan, bukan tiruan."""
    from jarvis.core import boot

    result = boot._check_memory()

    assert result.subsystem == "core.memory"
    assert isinstance(result.detail, str) and result.detail


def sqlite_error():
    import sqlite3

    return sqlite3.OperationalError("database is locked")
