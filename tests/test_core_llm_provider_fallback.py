"""W4 — provider seam: jarvis.core.llm fallback ke provider aktif agent.

Latar: `jarvis/core/llm.py` dikunci ke Gemini (genai). Bila kunci Gemini tidak
tersedia tetapi provider aktif agent (custom/local/openrouter) siap, jalur
legacy (ringkasan dokumen, router LLM fallback) harus tetap berfungsi melalui
registry agent — bukan diam gagal. Kunci Gemini tetap jalur utama bila ada.
"""
from __future__ import annotations

import types


def test_generate_falls_back_to_active_provider_when_gemini_unavailable(
    monkeypatch,
):
    from jarvis.core import llm

    calls: dict[str, str] = {}

    class FakeClient:
        def available(self) -> bool:
            return True

        def generate(self, prompt, system=None, json_mode=False) -> str:
            calls["prompt"] = prompt
            calls["system"] = system
            return "jawaban provider aktif"

    monkeypatch.setattr(llm, "_get_client", lambda: None)
    import jarvis.agent.llm_client as lc

    monkeypatch.setattr(lc, "client", lambda name=None: FakeClient())

    out = llm.generate("tes prompt", system="sistem x")
    assert out == "jawaban provider aktif"
    assert calls == {"prompt": "tes prompt", "system": "sistem x"}


def test_generate_fallback_stays_honest_when_provider_unavailable(monkeypatch):
    from jarvis.core import llm

    class Unavailable:
        def available(self) -> bool:
            return False

        def generate(self, prompt, system=None, json_mode=False) -> str:
            raise AssertionError("tidak boleh dipanggil")

    monkeypatch.setattr(llm, "_get_client", lambda: None)
    import jarvis.agent.llm_client as lc

    monkeypatch.setattr(lc, "client", lambda name=None: Unavailable())

    assert llm.generate("apa pun") == ""


def test_generate_uses_gemini_when_client_exists_and_not_the_fallback(
    monkeypatch,
):
    from jarvis.core import llm

    class Models:
        def generate_content(self, model=None, contents=None, config=None):
            return types.SimpleNamespace(text="jawaban gemini")

    monkeypatch.setattr(
        llm, "_get_client", lambda: types.SimpleNamespace(models=Models())
    )
    import jarvis.agent.llm_client as lc

    fallback_calls: list[int] = []
    monkeypatch.setattr(
        lc, "client", lambda name=None: fallback_calls.append(1) or object()
    )

    assert llm.generate("halo") == "jawaban gemini"
    assert fallback_calls == []  # fallback TIDAK dipanggil saat Gemini ada
