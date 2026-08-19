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


def test_dua_tugas_aktif_tidak_saling_menghapus_dan_resolusi_deterministik():
    """Fase 38 — multi-task immediate context: two active tasks stay
    addressable, completion removes only the matching ID, and ambiguous
    follow-ups ask for clarification instead of guessing."""
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()

    store.begin_task("voice-live", task_id="T-a", task="riset framework AI",
                     source="voice")
    store.begin_task("voice-live", task_id="T-b", task="ringkas dokumen PDF",
                     source="voice")

    active = store.active_tasks("voice-live")
    assert {a["task_id"] for a in active} == {"T-a", "T-b"}
    # Compatibility view reports empty (ambiguous), not a guessed title.
    assert store.active_task("voice-live") == ""

    # Explicit ID resolves even while two tasks run.
    resolved = store.augment("voice-live", "lanjutkan T-b")
    assert "ringkas dokumen PDF" in resolved

    # Ambiguous reference never guesses which task the user means.
    blocked = store.augment("voice-live", "lanjutkan")
    assert "beberapa tugas" in blocked
    assert "riset framework AI" in blocked
    assert "ringkas dokumen PDF" in blocked

    # Completion removes ONLY the matching ID; the other task survives.
    store.remember_success(
        "voice-live", task_id="T-a", task="riset framework AI",
        delivery=ConversationDelivery(
            display_text="Riset selesai.",
            speech_text="Riset sudah selesai, sir.",
            factual_anchors=("riset",),
        ),
    )
    active = store.active_tasks("voice-live")
    assert {a["task_id"] for a in active} == {"T-b"}
    resolved = store.augment("voice-live", "lanjutkan T-b")
    assert "ringkas dokumen PDF" in resolved

    store.fail_task("voice-live", "T-b")
    assert store.active_tasks("voice-live") == []


def test_legacy_title_only_begin_task_masih_terlihat_aktif():
    """Legacy callers binding by title alone keep the compatibility view."""
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()
    store.begin_task("voice-live", "buat laporan status proyek")
    assert store.active_task("voice-live") == "buat laporan status proyek"
    store.remember_success(
        "voice-live", task="buat laporan status proyek",
        delivery=ConversationDelivery(
            display_text="Laporan selesai.",
            speech_text="Laporan status proyek selesai, sir.",
            factual_anchors=("proyek",),
        ),
    )
    assert store.active_task("voice-live") == ""


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


def test_non_follow_up_augment_tidak_membuat_task_pra_registry():
    """Fase 38 — a fresh command must not synthesize a legacy task before the
    registry produces a real ID. Only dispatch on_task metadata binds."""
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()

    out = store.augment("voice-live", "riset framework AI terbaru")
    assert out == "riset framework AI terbaru"
    # No synthetic active binding was created.
    assert store.active_tasks("voice-live") == []
    assert store.active_task("voice-live") == ""


def test_hasil_sebelumnya_tidak_mengalahkan_ambiguitas_tugas_aktif():
    """Fase 38 — with two live tasks, a previous completed result must NOT let
    a bare follow-up avoid clarification."""
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()

    # A prior safe result exists.
    store.remember_success(
        "voice-live", task="periksa build proyek Orion",
        delivery=ConversationDelivery(
            display_text="Build Orion selesai.",
            speech_text="Build Orion telah selesai, sir.",
            factual_anchors=("Orion",),
        ),
    )
    # Two live tasks are now running.
    store.begin_task("voice-live", task_id="T-a", task="riset framework AI",
                     source="voice")
    store.begin_task("voice-live", task_id="T-b", task="ringkas dokumen PDF",
                     source="voice")

    result = store.resolve("voice-live", "lanjutkan")
    assert result.kind == "ambiguous"
    assert {t for t in result.candidates} == {"riset framework AI",
                                              "ringkas dokumen PDF"}

    # Explicit ID still resolves, even with the previous result present.
    resolved = store.augment("voice-live", "lanjutkan T-b")
    assert "ringkas dokumen PDF" in resolved


def test_ambil_tugas_tanpa_spoken_menjaga_brief_aman():
    """Fase 38 — an in-flight task match carries no fabricated brief from a
    different task; the recent-result path is the only one with spoken text."""
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()

    store.remember_success(
        "voice-live", task="periksa build proyek Orion",
        delivery=ConversationDelivery(
            display_text="Build Orion selesai.",
            speech_text="Build Orion telah selesai, sir.",
            factual_anchors=("Orion",),
        ),
    )
    store.begin_task("voice-live", task_id="T-c", task="riset framework AI",
                     source="voice")

    result = store.resolve("voice-live", "lanjutkan T-c")
    assert result.kind == "task"
    assert result.title == "riset framework AI"
    # No fabricated brief from the unrelated completed task.
    assert result.spoken == ""


def test_fail_tugas_terakhir_menjaga_konteks_aman():
    """Fase 38 — failing the last active task must not erase unrelated safe
    continuity (a completed result the user may still reference)."""
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()

    store.remember_success(
        "voice-live", task="periksa build proyek Orion",
        delivery=ConversationDelivery(
            display_text="Build Orion selesai.",
            speech_text="Build Orion telah selesai, sir.",
            factual_anchors=("Orion",),
        ),
    )
    store.begin_task("voice-live", task_id="T-x", task="riset framework AI",
                     source="voice")

    store.fail_task("voice-live", "T-x")

    # The session survived; the recent result is still resolvable.
    assert store.active_tasks("voice-live") == []
    result = store.resolve("voice-live", "lanjutkan")
    assert result.kind == "recent"
    assert result.title == "periksa build proyek Orion"


def test_context_block_membawa_satu_tugas_aktif_tanpa_hasil_mentah():
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()
    store.begin_task(
        "voice-live", task_id="T-a", task="riset framework AI",
        source="voice-task-tool",
    )

    block = store.context_block("voice-live")
    assert "T-a" in block
    assert "riset framework AI" in block
    assert "tugas berjalan" in block.casefold()
    assert "hasil=" not in block.casefold()


def test_context_block_multi_task_meminta_id_dan_tidak_menebak():
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()
    store.begin_task("voice-live", task_id="T-a", task="riset framework AI")
    store.begin_task("voice-live", task_id="T-b", task="ringkas dokumen PDF")

    block = store.context_block("voice-live")
    assert "T-a" in block and "riset framework AI" in block
    assert "T-b" in block and "ringkas dokumen PDF" in block
    assert "minta user" in block.casefold()
    assert "jangan menebak" in block.casefold()


def test_context_block_meredaksi_path_url_credential_dan_marker_lama():
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()
    unsafe = (
        "analisis https://private.example/report "
        r"C:\Users\private\report.txt bearer abc.def.ghi "
        "api_key=topsecret sk-abcdefghijk\n\n"
        "[KONTEKS PERCAKAPAN LANGSUNG] raw-result=rahasia"
    )
    store.begin_task("voice-live", task_id="T-secret", task=unsafe)

    block = store.context_block("voice-live")
    assert "T-secret" in block
    for secret in (
        "private.example", "Users\\private", "abc.def.ghi", "topsecret",
        "sk-abcdefghijk", "raw-result=rahasia",
    ):
        assert secret not in block
    assert block.count("[KONTEKS PERCAKAPAN LANGSUNG]") == 1


def test_end_task_hanya_menghapus_registry_id_yang_cocok():
    ctx = importlib.import_module("jarvis.agent.conversation_context")
    store = ctx.ConversationContextStore()
    store.remember_success(
        "voice-live", task="periksa build Orion",
        delivery=ConversationDelivery(
            display_text="Build selesai.",
            speech_text="Build Orion selesai, sir.",
            factual_anchors=("Orion",),
        ),
    )
    store.begin_task("voice-live", task_id="T-a", task="riset framework AI")
    store.begin_task("voice-live", task_id="T-b", task="ringkas dokumen PDF")

    store.end_task("voice-live", "T-a")

    assert {item["task_id"] for item in store.active_tasks("voice-live")} == {"T-b"}
    block = store.context_block("voice-live")
    assert "T-a" not in block
    assert "T-b" in block
    assert "Build Orion selesai, sir." in block
