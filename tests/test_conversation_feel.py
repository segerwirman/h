"""DIAGNOSIS_2 MASALAH 4 — percakapan terasa kaku.

Yang bisa diuji mesin hanyalah MEKANIKANYA: fallback benar-benar jalan, ACK
benar-benar bervariasi, aturan keras proaktif benar-benar mengikat. Apakah
hasilnya *terasa* lebih hidup hanya bisa dinilai user — itu ditulis apa adanya
di laporan, bukan dipura-purakan lulus di sini.
"""
from __future__ import annotations

import hashlib
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.agent import ack_composer
from jarvis.agent.interaction import ConversationDelivery
from jarvis.core import proactive_signals as ps

ROOT = Path(__file__).resolve().parents[1]


def _client(text: str):
    class _C:
        def chat(self, *_a, **_k):
            return SimpleNamespace(ok=True, content=text)
    return _C()


def _slow_client(delay: float = 0.6):
    """Cukup lambat untuk melewati deadline, cukup cepat untuk melepas
    semaphore modul.

    ``response_composer._IN_FLIGHT`` dan ``ack_composer._IN_FLIGHT`` adalah
    BoundedSemaphore tingkat-MODUL yang baru dilepas saat worker selesai —
    bukan saat deadline lewat. Klien yang tidur 5 detik akan menahannya jauh
    setelah tes ini selesai dan membuat tes LAIN mendapat "skipped: busy".
    """
    class _C:
        def available(self):
            return True

        def chat(self, *_a, **_k):
            time.sleep(delay)
            return SimpleNamespace(ok=True, content="terlambat")
    return _C()


def _broken_client():
    class _C:
        def chat(self, *_a, **_k):
            raise RuntimeError("provider mati")
    return _C()


# ── Langkah 1: composer aktif, fallback tetap mengikat ───────────────────

def test_config_menyalakan_composer() -> None:
    from jarvis.core import config
    assert config.get("auxiliary.response_composer.enabled") is True
    assert config.get("release_controls.naturalizer") is True


def test_awareness_tetap_mati_karena_belum_ada_konsumen() -> None:
    """Menyalakannya tanpa subscriber hanya membakar CPU (DIAGNOSIS_2 4e)."""
    from jarvis.core import config
    assert config.get("awareness.enabled") is False


def test_composer_fallback_saat_provider_lambat() -> None:
    from jarvis.agent import response_composer as rc

    delivery = ConversationDelivery(
        display_text="Riset selesai.",
        speech_text="Riset lima laptop selesai, tuan.",
        factual_anchors=("lima",))
    t0 = time.monotonic()
    out = rc.compose(delivery, "riset laptop", enabled=True, timeout_s=0.3,
                     client_factory=_slow_client)
    elapsed = time.monotonic() - t0
    assert out.speech_text == delivery.speech_text, "menggantung, tidak fallback"
    assert elapsed < 2.0, f"deadline tidak mengikat: {elapsed:.2f}s"


def test_composer_menolak_yang_membuang_fakta() -> None:
    from jarvis.agent import response_composer as rc

    delivery = ConversationDelivery(
        display_text="Ada 5 hasil.", speech_text="Ada lima hasil, tuan.",
        factual_anchors=("lima",))
    out = rc.compose(delivery, "cari", enabled=True, timeout_s=1.0,
                     client_factory=lambda: _client("Sudah beres kok."))
    assert out.speech_text == delivery.speech_text


# ── Langkah 3: ACK kontekstual ───────────────────────────────────────────

TASK = "riset perbandingan lima laptop di bawah 15 juta"


def test_ack_menyebut_tugasnya() -> None:
    natural = "Oke, saya cari perbandingan lima laptop itu, sebentar ya."
    out = ack_composer.compose_ack(
        TASK, force=True, client_factory=lambda: _client(natural))
    assert out == natural


def test_ack_jatuh_ke_template_saat_provider_mati() -> None:
    out = ack_composer.compose_ack(
        TASK, force=True, client_factory=_broken_client)
    assert out
    assert "laptop" not in out.lower(), "seharusnya template, bukan kontekstual"


def test_ack_bounded_saat_provider_lambat() -> None:
    t0 = time.monotonic()
    out = ack_composer.compose_ack(
        TASK, force=True, client_factory=_slow_client)
    elapsed = time.monotonic() - t0
    assert out, "ACK kosong — user tidak tahu perintahnya diterima"
    assert elapsed < 3.0, f"ACK menggantung {elapsed:.2f}s"


def test_ack_menolak_yang_mengarang_hasil() -> None:
    """ACK adalah janji mengerjakan, bukan laporan selesai."""
    out = ack_composer.compose_ack(
        TASK, force=True,
        client_factory=lambda: _client("Selesai, hasilnya sudah saya temukan."))
    assert "selesai" not in out.lower()


def test_ack_menolak_paragraf() -> None:
    panjang = "Baik " + " ".join(["kata"] * 30)
    out = ack_composer.compose_ack(
        TASK, force=True, client_factory=lambda: _client(panjang))
    assert len(out.split()) < 18


def test_ack_mati_memakai_template_lama() -> None:
    out = ack_composer.compose_ack(TASK, force=False)
    assert out
    assert "laptop" not in out.lower()


def test_ack_tidak_pernah_kosong() -> None:
    for factory in (_broken_client, lambda: _client(""), lambda: _client("   ")):
        assert ack_composer.compose_ack(TASK, force=True,
                                        client_factory=factory).strip()


# ── Langkah 4: section persona ───────────────────────────────────────────

def test_persona_ditambahkan_tanpa_mengubah_prompt_txt() -> None:
    from jarvis.integrations import voice_persona

    prompt_path = ROOT / "core" / "prompt.txt"
    before = hashlib.sha256(prompt_path.read_bytes()).hexdigest()

    legacy = SimpleNamespace(_load_system_prompt=lambda: "PERSONA MILIK USER")
    voice_persona.install(legacy)
    prompt = legacy._load_system_prompt()

    assert prompt.startswith("PERSONA MILIK USER"), "persona ditulis ulang"
    for marker in ("[GAYA BICARA]", "[NADA ADAPTIF]", "[INISIATIF]"):
        assert marker in prompt, marker
    assert legacy._load_system_prompt().count("[GAYA BICARA]") == 1

    after = hashlib.sha256(prompt_path.read_bytes()).hexdigest()
    assert before == after, "core/prompt.txt (FROZEN) berubah"


def test_persona_memuat_aturan_nada_kegagalan() -> None:
    from jarvis.integrations import voice_persona
    text = voice_persona.PERSONA_SECTIONS
    assert "Jangan pernah ceria saat melaporkan kegagalan" in text
    assert "Kalau ditolak, jangan tawarkan lagi" in text


# ── Langkah 5: aturan keras proaktif ─────────────────────────────────────

@pytest.fixture(autouse=True)
def _fresh_signals():
    ps.reset_for_tests()
    yield
    ps.reset_for_tests()


def _make_idle() -> None:
    """Geser aktivitas user ke masa lalu supaya tidak dianggap sibuk."""
    with ps._lock:
        ps._state.last_user_activity = time.monotonic() - 1000
        ps._state.last_triggered = time.monotonic() - 10_000


def test_focus_mode_nol_interupsi(monkeypatch) -> None:
    from jarvis.core.focus_mode import FocusMode

    _make_idle()
    FocusMode._reset_for_tests()
    FocusMode.get().activate(60)
    try:
        assert ps.blocked_reason() == "focus_mode aktif"
        allowed, reason = ps.decide()
        assert allowed is False and reason == "focus_mode aktif"
    finally:
        FocusMode.get().deactivate()


def test_tidak_menyela_saat_user_bicara() -> None:
    _make_idle()
    ps._on_state({"state": "LISTENING"})
    assert ps.blocked_reason() is not None
    allowed, _ = ps.decide()
    assert allowed is False


def test_tidak_menyela_saat_user_baru_beraktivitas() -> None:
    _make_idle()
    ps.note_user_activity()
    assert "baru saja beraktivitas" in (ps.blocked_reason() or "")


def test_jarak_minimum_ditegakkan() -> None:
    _make_idle()
    ps.mark_triggered()
    assert "jarak minimum" in (ps.blocked_reason() or "")


def test_dua_diabaikan_menggandakan_jarak() -> None:
    base = ps.effective_gap()
    ps.mark_ignored()
    assert ps.effective_gap() == base, "turun terlalu cepat"
    ps.mark_ignored()
    assert ps.effective_gap() == base * 2, "frekuensi tidak turun"
    ps.mark_acknowledged()
    assert ps.effective_gap() == base, "tidak pulih setelah ditanggapi"


def test_tanpa_sinyal_maka_diam() -> None:
    """Kalau tidak bisa menjawab 'kenapa aku bilang ini sekarang' → diam."""
    _make_idle()
    ps._on_state({"state": "IDLE"})
    allowed, reason = ps.decide()
    assert reason, "keputusan tanpa alasan"
    if not allowed:
        assert reason


def test_error_di_layar_jadi_sinyal_beralasan() -> None:
    _make_idle()
    ps._on_state({"state": "IDLE"})
    ps._on_awareness({"model": SimpleNamespace(
        window_title="build failed - terminal", summary="Traceback")})
    signals = {s.kind for s in ps.collect()}
    assert "screen" in signals
    allowed, reason = ps.decide()
    assert allowed is True
    assert "error" in reason.lower() or "gagal" in reason.lower()


def test_sinyal_layar_kedaluwarsa() -> None:
    _make_idle()
    ps._on_awareness({"model": SimpleNamespace(
        window_title="error", summary="failed")})
    with ps._lock:
        ps._state.screen_at = time.monotonic() - 999
    assert "screen" not in {s.kind for s in ps.collect()}


def test_layar_bersih_bukan_sinyal() -> None:
    ps._on_awareness({"model": SimpleNamespace(
        window_title="Notepad - catatan.txt", summary="halo")})
    assert "screen" not in {s.kind for s in ps.collect()}


def test_engine_memakai_sinyal_dan_menjelaskan() -> None:
    from actions.proactive import ProactiveEngine

    engine = ProactiveEngine()
    _make_idle()
    ps._on_state({"state": "IDLE"})
    ps._on_awareness({"model": SimpleNamespace(
        window_title="build failed", summary="Traceback")})

    assert engine.should_trigger(time.monotonic()) is True, \
        "sinyal nyata diabaikan"
    assert engine.last_reason, "bicara tanpa alasan"
    assert "Why now" in engine.build_prompt({})


def test_engine_diam_saat_focus_mode() -> None:
    from actions.proactive import ProactiveEngine
    from jarvis.core.focus_mode import FocusMode

    engine = ProactiveEngine()
    _make_idle()
    ps._on_awareness({"model": SimpleNamespace(
        window_title="build failed", summary="Traceback")})
    FocusMode._reset_for_tests()
    FocusMode.get().activate(60)
    try:
        assert engine.should_trigger(time.monotonic() - 10_000) is False
        assert engine.last_reason == ""
    finally:
        FocusMode.get().deactivate()


def test_perilaku_lama_diam_lama_tetap_ada() -> None:
    from actions.proactive import ProactiveEngine

    engine = ProactiveEngine()
    _make_idle()
    ps._on_state({"state": "IDLE"})
    long_ago = time.monotonic() - 10_000
    assert engine.should_trigger(long_ago) is True
    assert engine.last_reason


def test_ack_tidak_melanggar_anggaran_latensi() -> None:
    """Batas user: latensi tidak bertambah > 300 ms.

    ACK ada di jalur kritis — dispatch_async menjanjikan ACK instan, jadi
    biaya TERBURUK (provider menggantung) harus tetap di bawah batas itu.
    """
    class _Slow:
        def available(self):
            return True

        def chat(self, *_a, **_k):
            time.sleep(0.6)
            return SimpleNamespace(ok=True, content="terlambat")

    worst = 0.0
    for _ in range(3):
        t0 = time.monotonic()
        ack_composer.compose_ack("riset laptop", force=True,
                                 client_factory=_Slow)
        worst = max(worst, (time.monotonic() - t0) * 1000)
        time.sleep(0.7)          # biarkan semaphore modul terlepas
    assert worst < 300, f"ACK menambah {worst:.0f} ms"


def test_ack_tidak_menyentuh_jaringan_saat_provider_tak_siap() -> None:
    """Provider mati harus terdeteksi LOKAL, bukan dengan membakar deadline."""
    class _Dead:
        def available(self):
            return False

        def chat(self, *_a, **_k):
            raise AssertionError("chat dipanggil padahal provider tak siap")

    t0 = time.monotonic()
    out = ack_composer.compose_ack("riset", force=True, client_factory=_Dead)
    assert out
    assert (time.monotonic() - t0) < 0.05
