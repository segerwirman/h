"""ACK kontekstual: natural, task-aware, cepat, fallback aman."""
from __future__ import annotations

import time
from types import SimpleNamespace

from jarvis.agent import ack_composer


class _Client:
    def __init__(self, content: str, delay: float = 0.0):
        self.content, self.delay = content, delay
        self.messages = []

    def available(self):
        return True

    def chat(self, messages, **_kwargs):
        self.messages = messages
        if self.delay:
            time.sleep(self.delay)
        return SimpleNamespace(ok=True, content=self.content)


def test_ack_prompt_mengarahkan_task_jenis_nada_dan_variation():
    prompt = ack_composer._SYSTEM_PROMPT_ID
    for phrase in (
        "Sebut apa yang dikerjakan",
        "cepat",
        "cari/riset",
        "tugas panjang",
        "Ambigu",
        "Variasikan",
        "Cocokkan energi user",
    ):
        assert phrase in prompt


def test_ack_model_menyebut_task_cepat():
    client = _Client("Buka Spotify, sir.")
    out = ack_composer.compose_ack(
        "buka Spotify", force=True, client_factory=lambda: client)
    assert out == "Buka Spotify, sir."
    assert "buka Spotify" in client.messages[-1]["content"]


def test_ack_model_menyebut_topik_riset_panjang():
    out = ack_composer.compose_ack(
        "riset berita teknologi terbaru", force=True,
        client_factory=lambda: _Client(
            "Saya carikan berita teknologi terbaru, sebentar ya."))
    assert "berita teknologi" in out.lower()


def test_ack_fallback_lambat_tidak_menunggu_lebih_dari_300ms():
    t0 = time.monotonic()
    out = ack_composer.compose_ack(
        "buka Spotify", force=True,
        client_factory=lambda: _Client("Buka Spotify, sir.", delay=0.6))
    assert out
    assert (time.monotonic() - t0) < 0.30


def test_ack_fallback_templates_banyak_dan_tidak_seragam():
    from jarvis.core import config
    templates = config.get("agent.interaction.ack_templates.id")
    assert len(templates) >= 8
    assert len(set(templates)) == len(templates)


def test_interactive_dispatch_memakai_ack_composer(monkeypatch):
    from jarvis.agent import interactive_dispatch

    seen = []
    monkeypatch.setattr(interactive_dispatch.dispatch, "dispatch_async",
                        lambda _task, **kw: kw["on_ack"]("legacy") or True)
    monkeypatch.setattr("jarvis.agent.ack_composer.compose_ack",
                        lambda task, **_kw: f"KONTEKSTUAL: {task}")
    assert interactive_dispatch.start("buka Spotify", on_ack=lambda _raw, text: seen.append(text))
    assert seen == ["KONTEKSTUAL: buka Spotify"]
