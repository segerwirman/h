"""T1 — credential tidak boleh melintas polos tanpa ada yang memberitahu.

`config/providers.json` Takeda memakai `http://43.167.18.81:20128/v1`. Provider
kind `openai_compat` mengirim API key sebagai header `Authorization: Bearer`,
jadi kunci itu melintas internet publik dalam bentuk terbaca setiap panggilan.

Probe 2026-08-04 membuktikan host itu TIDAK menyediakan TLS sama sekali:

    port 20128  TCP ok, TLS  -> SSLError WRONG_VERSION_NUMBER (server bicara HTTP polos)
    port 443    ConnectionRefused
    port 8443   ConnectionRefused

Jadi ini tidak bisa diperbaiki dari sisi repo. Yang BISA — dan itulah yang
dikunci di sini — adalah memastikan keadaan ini tidak berlangsung diam-diam,
prinsip yang sama dengan Fase 4.

Endpoint lokal (loopback/privat/.local) sengaja TIDAK diperingatkan: di sana
plaintext wajar dan peringatan yang terlalu cerewet akan diabaikan orang.
"""
from __future__ import annotations

import pytest

from jarvis.agent.providers import insecure_plaintext_base_url


@pytest.mark.parametrize("url", [
    "http://43.167.18.81:20128/v1",          # kasus nyata Takeda
    "http://api.example.com/v1",
    "http://8.8.8.8:8080/v1",
])
def test_http_ke_host_publik_ditandai_bahaya(url):
    assert insecure_plaintext_base_url(url) is True, url


@pytest.mark.parametrize("url", [
    "https://43.167.18.81:20128/v1",         # TLS = aman walau IP publik
    "https://api.openai.com/v1",
])
def test_https_tidak_ditandai(url):
    assert insecure_plaintext_base_url(url) is False, url


@pytest.mark.parametrize("url", [
    "http://localhost:11434/v1",             # Ollama dsb.
    "http://127.0.0.1:8000/v1",
    "http://192.168.1.50:1234/v1",
    "http://10.0.0.7/v1",
    "http://workstation.local/v1",
])
def test_endpoint_lokal_tidak_dianggap_bahaya(url):
    assert insecure_plaintext_base_url(url) is False, url


@pytest.mark.parametrize("url", ["", "   ", None, "bukan-url", "ftp://x/y"])
def test_nilai_tak_berbentuk_tidak_menimbulkan_alarm_palsu(url):
    assert insecure_plaintext_base_url(url) is False, repr(url)


def test_klien_openai_compat_memperingatkan_saat_plaintext(monkeypatch):
    """Peringatan terbit tepat saat credential mulai mengalir."""
    from jarvis.agent import llm_client
    from jarvis.agent.providers import Provider

    warnings: list[tuple] = []
    monkeypatch.setattr(llm_client._logger, "warning",
                        lambda event, **kw: warnings.append((event, kw)))

    provider = Provider(name="custom", kind="openai_compat", label="Custom",
                        base_url="http://43.167.18.81:20128/v1",
                        api_key="rahasia", model="ds/deepseek-v4-flash")
    llm_client.LLMClient(provider)._client()

    events = [event for event, _ in warnings]
    assert "agent.llm.insecure_base_url" in events, events
    payload = dict(warnings[events.index("agent.llm.insecure_base_url")][1])
    # Peringatan tidak boleh ikut membocorkan kuncinya.
    assert "rahasia" not in str(payload), payload


def _sheet_with(monkeypatch, base_url: str):
    """Panel Settings dengan provider custom ber-base_url tertentu."""
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication, QWidget

    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.ui.settings_providers import ProviderSettingsSheet

    custom = Provider(name="custom", kind="openai_compat", label="Custom",
                      base_url=base_url, api_key="rahasia",
                      model="ds/deepseek-v4-flash", capabilities=("chat",))
    monkeypatch.setattr(providers, "list_names", lambda: ["custom"])
    monkeypatch.setattr(providers, "active_name", lambda: "custom")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: custom)

    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    host = QWidget()
    _UI_REFS.append(host)
    sheet = ProviderSettingsSheet(host)
    _UI_REFS.append(sheet)
    return sheet


# Qt memiliki widget lewat parent C++. DUA referensi wajib dipegang:
#   _APP_REF  — tanpa ini QApplication ter-GC saat widget masih hidup dan
#               proses mati exit 127 di teardown (terbukti di sesi ini);
#   _UI_REFS  — tanpa ini host ter-GC dan sheet dihapus di tengah test.
_APP_REF = None
_UI_REFS: list = []


def test_panel_settings_menampilkan_peringatan_plaintext(monkeypatch):
    sheet = _sheet_with(monkeypatch, "http://43.167.18.81:20128/v1")
    text = sheet._status.text()
    assert "TIDAK TERENKRIPSI" in text, text
    assert "rahasia" not in text, "status bocorkan credential"


def test_panel_settings_diam_untuk_endpoint_lokal(monkeypatch):
    sheet = _sheet_with(monkeypatch, "http://127.0.0.1:11434/v1")
    assert "TIDAK TERENKRIPSI" not in sheet._status.text()


def test_klien_https_tidak_memperingatkan(monkeypatch):
    from jarvis.agent import llm_client
    from jarvis.agent.providers import Provider

    warnings: list[tuple] = []
    monkeypatch.setattr(llm_client._logger, "warning",
                        lambda event, **kw: warnings.append((event, kw)))

    provider = Provider(name="openai", kind="openai_compat", label="OpenAI",
                        base_url="https://api.openai.com/v1",
                        api_key="rahasia", model="gpt-5.2")
    llm_client.LLMClient(provider)._client()

    assert not [e for e, _ in warnings if e == "agent.llm.insecure_base_url"]
