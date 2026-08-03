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


def test_simple_provider_flow_hides_advanced_routing_by_default(monkeypatch):
    sheet, _ = _sheet(monkeypatch)

    assert sheet._combo.isHidden() is False
    assert sheet._base_url.isHidden() is False
    assert sheet._api_key.isHidden() is False
    assert sheet._detect_models_button.isHidden() is False
    assert sheet._active_btn.isHidden() is False
    for widget in (sheet._light_provider, sheet._light_model, sheet._save_lane,
                   sheet._heavy_provider, sheet._heavy_model, sheet._save_heavy,
                   sheet._roles_lbl):
        assert widget.isHidden() is True


def test_advanced_routing_disclosure_is_closed_then_opens_only_on_local_toggle(monkeypatch):
    sheet, _ = _sheet(monkeypatch)

    assert sheet._advanced_toggle.text() == "TAMPILKAN ROUTING LANJUTAN"
    assert sheet._advanced_visible is False
    assert all(widget.isHidden() for widget in sheet._advanced_widgets)

    sheet._toggle_advanced_routing()
    assert sheet._advanced_visible is True
    assert sheet._advanced_toggle.text() == "SEMBUNYIKAN ROUTING LANJUTAN"
    assert all(widget.isHidden() is False for widget in sheet._advanced_widgets)

    sheet._toggle_advanced_routing()
    assert sheet._advanced_visible is False
    assert all(widget.isHidden() for widget in sheet._advanced_widgets)


def test_advanced_disclosure_does_not_write_provider_routing(monkeypatch):
    sheet, _ = _sheet(monkeypatch)
    from jarvis.core import settings_service

    writes = []
    monkeypatch.setattr(settings_service, "set_value", lambda *args: writes.append(args) or (True, ""))
    sheet._toggle_advanced_routing()
    sheet._toggle_advanced_routing()
    assert writes == []


def test_connection_error_is_classified_without_draft_or_raw_error_text(monkeypatch):
    sheet, _ = _sheet(monkeypatch)
    secret = "draft-secret-do-not-display"
    sheet._api_key.setText(secret)

    sheet._apply_model_catalog({"provider": "openai", "state": "models_failed",
                                "error": f"HTTP 401 token={secret}", "manual": False})

    assert secret not in sheet._status.text()
    assert "Koneksi provider belum tersedia" in sheet._status.text()
    assert sheet._detected_models.isEnabled() is False
    assert sheet._model.isHidden() is True


def test_oauth_and_agent_probe_failures_do_not_echo_raw_error(monkeypatch):
    sheet, _ = _sheet(monkeypatch)
    secret = "access_token=not-for-ui"

    sheet._apply_oauth_update({"provider": "openai", "state": "failed", "error": secret})
    assert secret not in sheet._status.text()
    assert "belum lengkap" in sheet._status.text()

    result = type("Probe", (), {"ready": False, "chat_ok": False, "detail": secret})()
    sheet._apply_model_catalog({"provider": "openai", "state": "agent_probe", "result": result})
    assert secret not in sheet._status.text()
    assert "Tes model belum berhasil" in sheet._status.text()


def test_theme_styles_only_read_theme_tokens(monkeypatch):
    sheet, _ = _sheet(monkeypatch)
    css = sheet.styleSheet() + sheet._detected_models.styleSheet()
    from jarvis.ui import theme
    assert theme.PAL.panel in css
    assert theme.PAL.base in css
    # Token warna diekspansi menjadi hex saat stylesheet dirender; yang penting
    # nilai berasal dari PAL, bukan literal panel baru.
    assert "color: red" not in css
