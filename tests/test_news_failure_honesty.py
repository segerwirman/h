"""Berita: jangan menutupi quota/jaringan/no-result sebagai error STT."""
from __future__ import annotations

from types import SimpleNamespace

from jarvis.agent.router import Tier
from jarvis.agent.voice_gate import VoiceToolGate
from actions import web_search as news


def _route(*_args):
    from jarvis.agent.router import Route
    return Route(Tier.AGENT, "heavy", "heavy", "test", 1.0)


def test_voice_tool_call_news_mempertahankan_query_saat_transkrip_kosong():
    gate = VoiceToolGate(_route)
    call = SimpleNamespace(
        id="news-1", name="web_search",
        args={"query": "berita teknologi terbaru", "mode": "news"},
    )
    gate.queue_calls([call])
    gate.timeout()
    # Bukan None/error transkripsi: argumen tool adalah fallback task jujur.
    assert gate.claim_agent_task() == "berita teknologi terbaru"


def test_news_quota_dan_jaringan_memiliki_pesan_berbeda():
    assert "Kuota API berita habis" in news._news_failure_message(
        [RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")])
    assert "Tidak bisa menjangkau sumber berita" in news._news_failure_message(
        [ConnectionError("network unreachable")])


def test_news_tidak_ada_hasil_pesan_jujur(monkeypatch):
    monkeypatch.setattr(news, "_gemini_search", lambda _q: "")
    monkeypatch.setattr(news, "_ddg_news", lambda _q, max_results=8: [])
    out = news._news("berita topik yang tidak ada")
    assert out == "Tidak menemukan berita untuk itu, sir."
    assert "transkripsi" not in out.lower()


def test_news_kedua_backend_jaringan_putus_melaporkan_jaringan(monkeypatch):
    def offline(_q, **_kwargs):
        raise ConnectionError("network unreachable")

    monkeypatch.setattr(news, "_gemini_search", offline)
    monkeypatch.setattr(news, "_ddg_news", offline)
    out = news._news("berita hari ini")
    assert out == "Tidak bisa menjangkau sumber berita. Koneksi bermasalah."
    assert "transkripsi" not in out.lower()


def test_news_kedua_backend_quota_melaporkan_quota(monkeypatch):
    def quota(_q, **_kwargs):
        raise RuntimeError("429 RESOURCE_EXHAUSTED quota exceeded")

    monkeypatch.setattr(news, "_gemini_search", quota)
    monkeypatch.setattr(news, "_ddg_news", quota)
    out = news._news("berita hari ini")
    assert out == "Kuota API berita habis, sir. Perlu perpanjangan."
    assert "transkripsi" not in out.lower()


def test_router_menandai_berita_dan_informasi_sebagai_lookup_bukan_browser():
    from jarvis.core.router import Intent, IntentRouter

    news_route = IntentRouter().classify("berita teknologi terbaru")
    assert news_route.intent is Intent.SEARCH_WEB
    assert news_route.slots == {"query": "berita teknologi terbaru", "mode": "news"}

    info_route = IntentRouter().classify("cari informasi tentang AI")
    assert info_route.intent is Intent.SEARCH_WEB
    assert info_route.slots["mode"] == "search"


def test_news_quota_gemini_ddg_berhasil_tetap_mengembalikan_hasil(monkeypatch):
    def quota(_q):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(news, "_gemini_search", quota)
    monkeypatch.setattr(news, "_ddg_news", lambda _q, max_results=8: [{
        "title": "Berita valid", "snippet": "Ringkasan", "url": "https://example.test",
    }])
    out = news._news("berita teknologi terbaru")
    assert "Berita valid" in out
    assert "Kuota API" not in out
    assert "transkripsi" not in out.lower()
