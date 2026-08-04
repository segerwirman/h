"""Temuan S-10 — ``embed()`` wajib satu vektor per satu teks masukan.

Ditemukan saat menjalankan backfill Fase 13.0 pada DB nyata: jalur gemini
memanggil ``models.embed_content(contents=texts)`` dan mengembalikan apa pun
yang diberikan SDK apa adanya. Dengan google-genai 2.14.0 + model
``gemini-embedding-2``, 16 teks masukan menghasilkan **1** embedding.

Bahayanya bukan sekadar hasil kurang: pemanggil menyandingkan vektor dengan
teks berdasarkan posisi. Vektor yang lebih sedikit dari teks berarti memori
bisa mendapat vektor milik memori lain — pencarian semantik yang salah diam-diam.
Cacat ini tidak pernah terlihat karena ``write``/``update`` selalu mengirim
tepat satu teks.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from jarvis.agent import llm_client
from jarvis.agent.providers import Provider


def _client(kind: str) -> llm_client.LLMClient:
    return llm_client.LLMClient(
        Provider(name="t", kind=kind, label="t", base_url="http://x/v1",
                 api_key="k", model="m")
    )


def test_gemini_embed_returns_one_vector_per_text(monkeypatch):
    """SDK memberi 1 embedding untuk banyak teks — klien wajib menutupinya."""
    seen: list[list[str]] = []

    def _embed_content(*, model, contents, config=None):
        seen.append(list(contents))
        # Persis perilaku yang terukur di lapangan: satu embedding saja.
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.1, 0.2])])

    client = _client("gemini")
    monkeypatch.setattr(
        client, "_client",
        lambda: SimpleNamespace(models=SimpleNamespace(
            embed_content=_embed_content)),
    )

    vecs = client.embed(["satu", "dua", "tiga"])

    assert vecs is not None, "embedding tidak boleh menyerah diam-diam"
    assert len(vecs) == 3, f"paritas hilang: {len(vecs)} vektor untuk 3 teks"
    assert all(len(v) == 2 for v in vecs)


def test_gemini_embed_never_returns_fewer_vectors_than_texts(monkeypatch):
    """Bila paritas tetap mustahil, kembalikan None — jangan pernah sebagian."""

    def _embed_content(*, model, contents, config=None):
        return SimpleNamespace(embeddings=[])

    client = _client("gemini")
    monkeypatch.setattr(
        client, "_client",
        lambda: SimpleNamespace(models=SimpleNamespace(
            embed_content=_embed_content)),
    )

    assert client.embed(["satu", "dua"]) is None


def test_openai_compat_embed_parity_is_enforced(monkeypatch):
    """Jalur openai_compat memakai kontrak paritas yang sama."""
    batches: list[int] = []

    def _create(*, model, input):
        batches.append(len(input))
        # Selalu satu embedding, berapa pun masukannya.
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.3, 0.4])])

    client = _client("openai_compat")
    monkeypatch.setattr(
        client, "_client",
        lambda: SimpleNamespace(embeddings=SimpleNamespace(create=_create)),
    )

    vecs = client.embed(["satu", "dua"])

    assert vecs == [[0.3, 0.4], [0.3, 0.4]]
    # Batch gagal paritas, lalu dipulihkan satu-per-satu.
    assert batches == [2, 1, 1]


def test_partial_result_is_never_returned(monkeypatch):
    """Paritas yang tak terpulihkan → None, bukan sebagian.

    Provider di sini hanya sanggup melayani teks pertama. Mengembalikan satu
    vektor untuk dua memori akan menyandingkan vektor ke memori yang salah.
    """

    def _create(*, model, input):
        if list(input) == ["dua"]:
            return SimpleNamespace(data=[])
        return SimpleNamespace(data=[SimpleNamespace(embedding=[0.3, 0.4])])

    client = _client("openai_compat")
    monkeypatch.setattr(
        client, "_client",
        lambda: SimpleNamespace(embeddings=SimpleNamespace(create=_create)),
    )

    assert client.embed(["satu", "dua"]) is None


def test_single_text_embed_unchanged(monkeypatch):
    """Jalur satu teks — yang dipakai write/update — tidak berubah."""

    def _embed_content(*, model, contents, config=None):
        return SimpleNamespace(embeddings=[SimpleNamespace(values=[0.5])])

    client = _client("gemini")
    monkeypatch.setattr(
        client, "_client",
        lambda: SimpleNamespace(models=SimpleNamespace(
            embed_content=_embed_content)),
    )

    assert client.embed(["satu"]) == [[0.5]]


def test_empty_input_is_not_a_provider_call(monkeypatch):
    def _boom(**_):
        pytest.fail("provider tidak boleh dipanggil untuk masukan kosong")

    client = _client("gemini")
    monkeypatch.setattr(
        client, "_client",
        lambda: SimpleNamespace(models=SimpleNamespace(embed_content=_boom)),
    )

    assert client.embed([]) == []
