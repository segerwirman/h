"""Fase 13.0 — backfill vektor memori yang hilang (temuan S-9).

Selama ``routing.light.provider`` menunjuk endpoint yang tidak melayani
embedding, ``_embed`` mengembalikan ``None`` dan memori tersimpan dengan
``embedding IS NULL``. Baris itu tidak terjangkau pencarian semantik dan tidak
pulih sendiri ketika provider diperbaiki.

Backfill wajib: hanya menyentuh baris NULL, idempoten, dan — bila provider
masih tidak bisa embed — **melapor gagal tanpa mengubah satu baris pun**.
Kejujuran yang sama yang dituntut S-1 berlaku di sini.
"""
from __future__ import annotations

import pytest

import jarvis.agent.memory_store as ms


@pytest.fixture(autouse=True)
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(ms, "db_path", lambda: tmp_path / "agent.sqlite")
    yield


def _null_count() -> int:
    with ms._conn() as c:
        return c.execute(
            "SELECT COUNT(*) FROM memories WHERE embedding IS NULL"
        ).fetchone()[0]


def _seed(monkeypatch, *, with_vector: int, without_vector: int) -> None:
    """Tulis campuran baris bervektor dan tanpa vektor, seperti DB nyata."""
    monkeypatch.setattr(ms, "_embed", lambda texts: [[0.1, 0.2, 0.3]] * len(texts))
    for index in range(with_vector):
        ms.write("semantic", f"fakta bervektor {index}")
    monkeypatch.setattr(ms, "_embed", lambda texts: None)
    for index in range(without_vector):
        ms.write("reflective", f"pelajaran tanpa vektor {index}")


def test_backfill_hanya_mengisi_baris_yang_kosong(monkeypatch):
    _seed(monkeypatch, with_vector=2, without_vector=3)
    assert _null_count() == 3

    embedded_texts: list[str] = []

    def _embed(texts):
        embedded_texts.extend(texts)
        return [[0.4, 0.5, 0.6]] * len(texts)

    monkeypatch.setattr(ms, "_embed", _embed)
    report = ms.backfill_embeddings()

    assert report["embedded"] == 3
    assert report["failed"] is False
    assert _null_count() == 0
    # Baris yang sudah punya vektor tidak boleh ikut di-embed ulang.
    assert len(embedded_texts) == 3
    assert all("tanpa vektor" in text for text in embedded_texts)


def test_backfill_idempoten_pemanggilan_kedua_nol_embed(monkeypatch):
    _seed(monkeypatch, with_vector=1, without_vector=2)

    calls: list[int] = []

    def _embed(texts):
        calls.append(len(texts))
        return [[0.4, 0.5, 0.6]] * len(texts)

    monkeypatch.setattr(ms, "_embed", _embed)
    ms.backfill_embeddings()
    calls.clear()

    second = ms.backfill_embeddings()

    assert calls == []
    assert second["embedded"] == 0
    assert second["pending"] == 0
    assert second["failed"] is False


def test_backfill_melapor_gagal_dan_tidak_mengubah_apa_pun(monkeypatch):
    _seed(monkeypatch, with_vector=1, without_vector=2)
    before = _null_count()

    monkeypatch.setattr(ms, "_embed", lambda texts: None)
    report = ms.backfill_embeddings()

    assert report["failed"] is True
    assert report["embedded"] == 0
    assert report["reason"]
    # Jangan menulis vektor kosong dan jangan berpura-pura selesai.
    assert _null_count() == before


def test_backfill_batch_gagal_tidak_membatalkan_batch_yang_sudah_sukses(
    monkeypatch,
):
    _seed(monkeypatch, with_vector=0, without_vector=4)

    state = {"batches": 0}

    def _embed(texts):
        state["batches"] += 1
        if state["batches"] == 1:
            return [[0.4, 0.5, 0.6]] * len(texts)
        return None

    monkeypatch.setattr(ms, "_embed", _embed)
    report = ms.backfill_embeddings(batch_size=2)

    assert report["embedded"] == 2
    assert report["failed"] is True
    # Batch pertama yang sudah mendarat tidak boleh ikut hilang.
    assert _null_count() == 2
