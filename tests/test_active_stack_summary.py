"""Ringkasan stack aktif provider: sekali-lihat + aturan auto-switch."""
from __future__ import annotations

from jarvis.core import settings_service as S


def test_stack_summary_openai_terhubung_gemini_off(monkeypatch):
    monkeypatch.setattr(S, "_openai_oauth_connected", lambda: True)
    out = S.active_stack_summary()
    assert "STACK AKTIF" in out
    assert "OpenAI (Codex auth)" in out
    assert "Gemini Live OFF" in out
    # Ketiga peran memakai OpenAI saat terhubung.
    assert out.count("OpenAI (Codex auth)") >= 3


def test_stack_summary_openai_putus_gemini_on(monkeypatch):
    monkeypatch.setattr(S, "_openai_oauth_connected", lambda: False)
    out = S.active_stack_summary()
    assert "Gemini Live (native audio)" in out
    assert "Gemini ON" in out
    assert "Voice :" in out and "LLM   :" in out and "Image :" in out


def test_stack_summary_tidak_pernah_bocorkan_credential(monkeypatch):
    monkeypatch.setattr(S, "_openai_oauth_connected", lambda: True)
    out = S.active_stack_summary().lower()
    for leak in ("sk-", "bearer", "token", "api_key", "password"):
        assert leak not in out
