"""Fase 6 — immediate conversation context remains bounded and private."""
from __future__ import annotations

import importlib

from jarvis.agent.interaction import ConversationDelivery


def test_follow_up_lanjutkan_menggunakan_konteks_sesi_yang_sama():
    try:
        context_mod = importlib.import_module("jarvis.agent.conversation_context")
    except ModuleNotFoundError:
        context_mod = None

    assert context_mod is not None
    store = context_mod.ConversationContextStore()
    store.remember_success(
        "desktop-1",
        task="periksa build proyek Orion",
        delivery=ConversationDelivery(
            display_text="Build Orion #123 selesai. URL: https://example.test/private",
            speech_text="Build Orion 123 telah selesai, sir.",
            factual_anchors=("Orion", "123"),
        ),
    )

    resolved = store.augment("desktop-1", "lanjutkan")

    assert "periksa build proyek Orion" in resolved
    assert "Build Orion 123 telah selesai, sir." in resolved
    assert "https://" not in resolved
    assert "[KONTEKS PERCAKAPAN LANGSUNG]" in resolved


def test_follow_up_hanya_resolve_bila_session_memiliki_success_aman():
    context_mod = importlib.import_module("jarvis.agent.conversation_context")
    store = context_mod.ConversationContextStore()
    store.remember_success(
        "telegram-a",
        task="buat laporan Orion",
        delivery=ConversationDelivery(
            display_text=r"Laporan siap di C:\private\orion.txt",
            speech_text="Laporan Orion sudah siap, sir.",
            factual_anchors=("Orion",),
        ),
    )

    assert store.augment("telegram-b", "yang tadi") == "yang tadi"
    assert store.augment("telegram-a", "ambil yang tadi") == "ambil yang tadi"
    resolved = store.augment("telegram-a", "buka hasilnya")

    assert "buat laporan Orion" in resolved
    assert r"C:\\private" not in resolved


def test_follow_up_natural_mewarisi_context_tanpa_menumpuk_blok_lama():
    context_mod = importlib.import_module("jarvis.agent.conversation_context")
    store = context_mod.ConversationContextStore()
    delivery = ConversationDelivery(
        display_text="Build sudah selesai.",
        speech_text="Build sudah selesai, sir.",
        factual_anchors=("build",),
    )
    store.remember_success("voice", task="periksa build", delivery=delivery)

    first = store.augment("voice", "gunakan hasil sebelumnya untuk buat ringkasan")
    store.remember_success("voice", task=first, delivery=delivery)
    second = store.augment("voice", "teruskan")

    assert "periksa build" in second
    assert second.count("[KONTEKS PERCAKAPAN LANGSUNG]") == 1


def test_artifact_diingat_dan_dapat_dibuka_lewat_follow_up():
    context_mod = importlib.import_module("jarvis.agent.conversation_context")
    store = context_mod.ConversationContextStore()
    store.remember_artifact(
        "typed-desktop",
        path=r"E:\jarvis agent\h\data\generated\img_123.png",
        kind="image",
    )
    path, kind = store.last_artifact("typed-desktop")
    assert path.endswith("img_123.png")
    assert kind == "image"


def test_referensi_artefak_dikenali_untuk_beragam_frasa():
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    for phrase in (
        "buka gambar itu",
        "buka gambar tadi",
        "tampilkan hasilnya",
        "lihat file tadi",
        "tunjukkan gambar tersebut",
        "buka hasilnya",
    ):
        assert ctx.is_artifact_reference(phrase), phrase
    # Bukan referensi artefak: perintah biasa tanpa rujukan hasil.
    for phrase in ("buatkan gambar kucing", "cari berita AI terbaru", "halo"):
        assert not ctx.is_artifact_reference(phrase), phrase


def test_artifact_tidak_bocor_ke_blok_konteks_prompt():
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()
    store.remember_success(
        "typed-desktop",
        task="buatkan gambar kucing",
        delivery=ConversationDelivery(
            display_text="Gambar selesai.",
            speech_text="Gambar sudah selesai, sir.",
            factual_anchors=(),
        ),
    )
    store.remember_artifact(
        "typed-desktop", path=r"C:\secret\img.png", kind="image")
    block = store.augment("typed-desktop", "lanjutkan")
    # Path artefak TIDAK boleh muncul di blok konteks prompt (privacy).
    assert "img.png" not in block
    assert "secret" not in block
