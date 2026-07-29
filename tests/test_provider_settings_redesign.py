"""LLM provider sheet: satu dropdown discovery, fallback, save/activate/delete."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _sheet(monkeypatch):
    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.ui.settings_providers import ProviderSettingsSheet
    p = Provider(name="openai", kind="openai_compat", label="OpenAI",
                 base_url="https://api.test/v1", api_key="[REDACTED]", model="",
                 capabilities=("chat", "tools"))
    monkeypatch.setattr(providers, "list_names", lambda: ["openai"])
    monkeypatch.setattr(providers, "active_name", lambda: "openai")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: p)
    _app()
    host = QWidget()
    sheet = ProviderSettingsSheet(host)
    # Parent Qt harus tetap direferensikan selama assertion.
    sheet._test_host = host
    return sheet, p


def test_model_dropdown_disabled_sebelum_discovery(monkeypatch):
    sheet, _ = _sheet(monkeypatch)
    assert sheet._detected_models.isEnabled() is False
    assert sheet._model.isHidden() is True


def test_discovery_memilih_model_tools_dan_context_label(monkeypatch):
    from jarvis.agent.providers_discovery import ModelInfo
    sheet, _ = _sheet(monkeypatch)
    sheet._apply_model_catalog({"provider": "openai", "state": "models_detected",
                                "models": (ModelInfo("slow", "Slow", 32000, False),
                                           ModelInfo("tools", "Tools", 128000, True))})
    assert sheet._detected_models.isEnabled() is True
    assert sheet._detected_models.currentData() == "tools"
    assert sheet._model.text() == "tools"
    assert "128k" in sheet._detected_models.itemText(1)
    assert "2 model" in sheet._status.text()


def test_failed_format_shows_manual_only(monkeypatch):
    sheet, _ = _sheet(monkeypatch)
    sheet._apply_model_catalog({"provider": "openai", "state": "models_failed",
                                "error": "format katalog tidak dikenali", "manual": True})
    assert sheet._detected_models.isEnabled() is False
    assert sheet._model.isHidden() is False
    assert "Gagal" in sheet._status.text()


def test_test_connection_memakai_draft_tanpa_persist_key(monkeypatch):
    from jarvis.agent import providers_discovery
    sheet, _ = _sheet(monkeypatch)
    sheet._base_url.setText("http://localhost:1234/v1")
    sheet._api_key.setText("draft-secret")
    seen = []
    monkeypatch.setattr(providers_discovery, "discover",
                        lambda draft: seen.append(draft) or ())
    # Jalankan worker synchronously untuk memastikan draft, bukan registry.
    import threading
    monkeypatch.setattr(threading.Thread, "start", lambda self: self.run())
    sheet._detect_models()
    assert seen[0].base_url == "http://localhost:1234/v1"
    assert seen[0].api_key == "draft-secret"


def test_key_failure_keeps_dropdown_disabled_dan_manual_tersembunyi(monkeypatch):
    sheet, _ = _sheet(monkeypatch)
    sheet._apply_model_catalog({"provider": "openai", "state": "models_failed",
                                "error": "kredensial ditolak", "manual": False})
    assert sheet._detected_models.isEnabled() is False
    assert sheet._model.isHidden() is True


def test_delete_memanggil_provider_secure_delete(monkeypatch):
    from jarvis.agent import providers
    sheet, _ = _sheet(monkeypatch)
    calls = []
    monkeypatch.setattr(providers, "delete_provider", lambda name: calls.append(name) or True)
    monkeypatch.setattr(sheet, "_reload_names", lambda: None)
    sheet._delete_provider()
    assert calls == ["openai"]
    assert "dihapus" in sheet._status.text()


def test_theme_styles_only_read_theme_tokens(monkeypatch):
    sheet, _ = _sheet(monkeypatch)
    css = sheet.styleSheet() + sheet._detected_models.styleSheet()
    from jarvis.ui import theme
    assert theme.PAL.panel in css
    assert theme.PAL.base in css
    # Token warna diekspansi menjadi hex saat stylesheet dirender; yang penting
    # nilai berasal dari PAL, bukan literal panel baru.
    assert "color: red" not in css
