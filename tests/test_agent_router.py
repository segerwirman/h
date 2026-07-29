"""MK50 phase 1: automatic light/heavy tier classifier."""
from __future__ import annotations

import threading
import time

import pytest

from jarvis.agent import router
from jarvis.agent.router import Tier


@pytest.mark.parametrize(
    ("command", "tier"),
    [
        ("naikkan volume", Tier.REFLEX),
        ("atur brightness ke 40", Tier.REFLEX),
        ("matikan mikrofon", Tier.REFLEX),
        ("nyalakan lampu ruang tamu", Tier.REFLEX),
        ("buka Spotify", Tier.REFLEX),
        ("Jarvis, coba buka WhatsApp", Tier.REFLEX),
        ("tutup Spotify", Tier.REFLEX),
        ("buka browser", Tier.REFLEX),
        ("Jarvis buka kamera", Tier.REFLEX),
        ("coba tutup kamera", Tier.REFLEX),
        ("kembali", Tier.REFLEX),
        ("buka browser agent", Tier.REFLEX),
        ("tutup browser agent", Tier.REFLEX),
        ("klik tombol kirim", Tier.SINGLE),
        ("buka https://example.com/docs", Tier.SINGLE),
        ("buka youtube", Tier.SINGLE),
        ("halo", Tier.SINGLE),
        ("jam berapa sekarang?", Tier.SINGLE),
        ("bagaimana cuaca hari ini?", Tier.SINGLE),
        ("putar lagu Yellow", Tier.SINGLE),
        ("cari video YouTube tentang sejarah Majapahit", Tier.SINGLE),
        ("buatkan gambar kucing astronaut bergaya sinematik", Tier.SINGLE),
        ("kirim pesan ke telegram: halo", Tier.SINGLE),
        ("acara kalender hari ini", Tier.SINGLE),
        ("ada email baru?", Tier.SINGLE),
        ("apa itu volume?", Tier.SINGLE),
        ("Apakah kamu bisa membantu saya?", Tier.SINGLE),
        ("Bisakah kamu melihat aku?", Tier.SINGLE),
        ("apa berita terbaru hari ini?", Tier.SINGLE),
        ("video terbaru dari channel langgananku", Tier.SINGLE),
        ("riset pasar kendaraan listrik", Tier.AGENT),
        ("cari laporan lalu buat tabel", Tier.AGENT),
        ("bandingkan tiga provider ini", Tier.AGENT),
        ("perbaiki file config yang rusak", Tier.AGENT),
        ("jalankan perintah ini di terminal", Tier.AGENT),
        ("suruh hermes cek proyek ini", Tier.AGENT),
    ],
)
def test_deterministic_tier_rules(command, tier, monkeypatch):
    def must_not_call(_text):
        raise AssertionError("deterministic rule unexpectedly called Gemini")

    monkeypatch.setattr(router, "_call_gemini_classifier", must_not_call)
    route = router.classify(command, {})
    assert route.tier is tier
    assert route.lane == ("light" if tier <= Tier.SINGLE else "heavy")
    assert route.model_profile == route.lane
    assert route.confidence >= 0.7


def test_key_youtube_latest_command_is_t2(monkeypatch):
    monkeypatch.setattr(
        router,
        "_call_gemini_classifier",
        lambda _text: pytest.fail("YouTube rule must not call Gemini"),
    )
    route = router.classify(
        "buka dan putar youtube deddy corbuzier terbaru", {"source": "voice"}
    )
    assert route.tier is Tier.AGENT
    assert route.lane == "heavy"
    assert route.model_profile == "heavy"


def test_retired_browser_provider_phrase_defaults_safe_heavy(monkeypatch):
    """Provider browser lama tidak lagi mendapat jalur ringan khusus."""
    monkeypatch.setattr(router, "_call_gemini_classifier", lambda _text: "")
    route = router.classify("buka youtube di tabbit", {})
    assert route.tier is Tier.AGENT
    assert route.lane == "heavy"


def test_context_can_select_delegate_and_autonomous():
    assert router.classify("kerjakan bagian ini", {"delegated": True}).tier is Tier.DELEGATE
    assert router.classify("laporan harian", {"source": "cron"}).tier is Tier.AUTONOMOUS


def test_ambiguous_command_uses_defensive_json_fallback(monkeypatch):
    real_get = router.config.get
    monkeypatch.setattr(
        router.config,
        "get",
        lambda path, default=None: (
            True if path == "router.llm_fallback" else real_get(path, default)
        ),
    )
    monkeypatch.setattr(
        router,
        "_call_gemini_classifier",
        lambda _text: '```json\n{"tier": 1, "reason": "satu aksi"}\n```',
    )
    route = router.classify("urus yang ini", {})
    assert route.tier is Tier.SINGLE
    assert route.lane == "light"
    assert route.confidence == 0.75
    assert "satu aksi" in route.reason


def test_unknown_conversation_stays_light_without_network(monkeypatch):
    monkeypatch.setattr(router, "_call_gemini_classifier", lambda _text: "")
    route = router.classify("bisa bantu yang ini?", {})
    assert route.tier is Tier.SINGLE
    assert route.confidence > 0.0


@pytest.mark.parametrize(
    "response",
    [
        "",
        "not json",
        "{}",
        '{"tier": 7, "reason": "unsupported"}',
        '{"tier": 1.5, "reason": "fractional"}',
        '[{"tier": 1}]',
    ],
)
def test_bad_opt_in_llm_output_uses_local_conversation_default(
    monkeypatch, response
):
    real_get = router.config.get
    monkeypatch.setattr(
        router.config,
        "get",
        lambda path, default=None: (
            True if path == "router.llm_fallback" else real_get(path, default)
        ),
    )
    monkeypatch.setattr(router, "_call_gemini_classifier", lambda _text: response)
    route = router.classify("urus yang ini", {})
    assert route.tier is Tier.SINGLE
    assert route.lane == "light"


def test_classifier_exception_never_escapes(monkeypatch):
    def explode(_text):
        raise RuntimeError("provider unavailable")

    monkeypatch.setattr(router, "_call_gemini_classifier", explode)
    route = router.classify("urus yang ini", None)
    assert route.tier is Tier.SINGLE
    assert route.model_profile == "light"


def test_ambiguous_classifier_respects_sync_budget(monkeypatch):
    release = threading.Event()
    finished = threading.Event()

    def slow_classifier(_text):
        release.wait(1.0)
        finished.set()
        return '{"tier": 1, "reason": "too late"}'

    real_get = router.config.get

    def fast_budget(path, default=None):
        if path == "router.classify_budget_ms":
            return 10
        if path == "router.llm_fallback":
            return True
        return real_get(path, default)

    monkeypatch.setattr(router.config, "get", fast_budget)
    monkeypatch.setattr(router, "_call_gemini_classifier", slow_classifier)
    started = time.monotonic()
    route = router.classify("urus yang ini", {})
    elapsed = time.monotonic() - started
    release.set()
    assert finished.wait(0.5)

    assert elapsed < 0.2
    assert route.tier is Tier.SINGLE


def test_non_string_input_never_raises(monkeypatch):
    monkeypatch.setattr(router, "_call_gemini_classifier", lambda _text: "")
    assert router.classify(None, {}).tier is Tier.SINGLE


def test_unknown_action_still_defaults_safe_heavy(monkeypatch):
    monkeypatch.setattr(router, "_call_gemini_classifier", lambda _text: "")
    route = router.classify("hapus yang kemarin", {})
    assert route.tier is Tier.AGENT
    assert route.lane == "heavy"


def test_whatsapp_call_always_uses_approved_agent_lane(monkeypatch):
    monkeypatch.setattr(router, "_call_gemini_classifier", lambda _text: "")
    route = router.classify("telepon Ibu lewat WhatsApp", {})
    assert route.tier is Tier.AGENT
    assert route.confidence >= 0.9


def test_whatsapp_send_always_uses_approved_agent_lane(monkeypatch):
    monkeypatch.setattr(router, "_call_gemini_classifier", lambda _text: "")
    route = router.classify("kirim pesan WhatsApp ke Ibu: saya terlambat", {})
    assert route.tier is Tier.AGENT
    assert route.confidence >= 0.9


def test_followup_diagnosis_command_uses_native_agent(monkeypatch):
    monkeypatch.setattr(router, "_call_gemini_classifier", lambda _text: "")
    route = router.classify("Iya, coba cari penyebabnya.", {})
    assert route.tier is Tier.AGENT
    assert route.model_profile == "heavy"
