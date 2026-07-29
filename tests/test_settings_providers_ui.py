"""Provider sheet exposes safe OAuth and routing controls."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget


_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def test_provider_sheet_exposes_openai_oauth_login_and_light_lane(monkeypatch):
    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.integrations import openai_oauth
    from jarvis.ui.settings_providers import ProviderSettingsSheet

    oauth = Provider(name="openai_oauth", kind="openai_oauth",
                     label="OpenAI OAuth", model="gpt-light", auth="oauth",
                     capabilities=("chat", "tools", "streaming"))
    monkeypatch.setattr(providers, "list_names", lambda: ["openai_oauth"])
    monkeypatch.setattr(providers, "active_name", lambda: "openai_oauth")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: oauth)
    monkeypatch.setattr(openai_oauth, "status", lambda: {
        "connected": False, "needs_reauth": False,
        "token_refresh_due": False, "last_error_code": "",
    })

    _app()
    host = QWidget()
    sheet = ProviderSettingsSheet(host)

    assert sheet._oauth_button.text() == "HUBUNGKAN OPENAI OAUTH"
    assert sheet._light_provider.findText("openai_oauth") >= 0


def test_provider_sheet_exposes_anthropic_oauth_login(monkeypatch):
    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.integrations import anthropic_oauth
    from jarvis.ui.settings_providers import ProviderSettingsSheet

    oauth = Provider(name="anthropic_oauth", kind="anthropic_oauth",
                     label="Anthropic OAuth", model="claude-test", auth="oauth",
                     capabilities=("chat", "vision"))
    monkeypatch.setattr(providers, "list_names", lambda: ["anthropic_oauth"])
    monkeypatch.setattr(providers, "active_name", lambda: "anthropic_oauth")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: oauth)
    monkeypatch.setattr(anthropic_oauth, "status", lambda: {
        "connected": False, "needs_reauth": False,
        "token_refresh_due": False, "last_error_code": "",
    })

    _app()
    host = QWidget()
    sheet = ProviderSettingsSheet(host)

    assert sheet._oauth_button.isHidden() is False
    assert sheet._oauth_button.text() == "HUBUNGKAN ANTHROPIC OAUTH"


def test_connected_provider_exposes_detected_models_as_choices(monkeypatch):
    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.integrations import openai_oauth
    from jarvis.ui.settings_providers import ProviderSettingsSheet

    oauth = Provider(name="openai_oauth", kind="openai_oauth",
                     label="OpenAI OAuth", model="", auth="oauth",
                     capabilities=("chat", "tools", "streaming"))
    monkeypatch.setattr(providers, "list_names", lambda: ["openai_oauth"])
    monkeypatch.setattr(providers, "active_name", lambda: "openai_oauth")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: oauth)
    monkeypatch.setattr(openai_oauth, "status", lambda: {
        "connected": True, "needs_reauth": False,
        "token_refresh_due": False, "last_error_code": "",
    })

    _app()
    host = QWidget()
    sheet = ProviderSettingsSheet(host)
    sheet._apply_model_catalog({
        "provider": "openai_oauth", "state": "models_detected",
        "source": "account", "models": ["gpt-codex-a", "gpt-codex-b"],
    })

    assert sheet._detect_models_button.isHidden() is False
    assert [sheet._detected_models.itemText(i)
            for i in range(sheet._detected_models.count())] == [
                "gpt-codex-a", "gpt-codex-b"]
    sheet._detected_models.setCurrentText("gpt-codex-b")
    assert sheet._model.text() == "gpt-codex-b"


def test_openai_oauth_connection_starts_model_detection(monkeypatch):
    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.integrations import openai_oauth
    from jarvis.ui.settings_providers import ProviderSettingsSheet

    oauth = Provider(name="openai_oauth", kind="openai_oauth",
                     label="OpenAI OAuth", model="", auth="oauth",
                     capabilities=("chat",))
    monkeypatch.setattr(providers, "list_names", lambda: ["openai_oauth"])
    monkeypatch.setattr(providers, "active_name", lambda: "openai_oauth")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: oauth)
    monkeypatch.setattr(openai_oauth, "status", lambda: {
        "connected": True, "needs_reauth": False,
        "token_refresh_due": False, "last_error_code": "",
    })

    _app()
    host = QWidget()
    sheet = ProviderSettingsSheet(host)
    calls: list[bool] = []
    monkeypatch.setattr(sheet, "_detect_models", lambda: calls.append(True))

    sheet._apply_oauth_update({"provider": "openai_oauth", "state": "connected"})

    assert calls == [True]


def test_saving_configured_provider_starts_model_detection(monkeypatch):
    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.ui.settings_providers import ProviderSettingsSheet

    provider = Provider(name="openai", kind="openai_compat", model="gpt-test",
                        base_url="https://api.example/v1", api_key="secret",
                        capabilities=("chat",))
    monkeypatch.setattr(providers, "list_names", lambda: ["openai"])
    monkeypatch.setattr(providers, "active_name", lambda: "openai")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: provider)
    monkeypatch.setattr(providers, "save_provider", lambda *_args, **_kwargs: True)

    _app()
    host = QWidget()
    sheet = ProviderSettingsSheet(host)
    calls: list[bool] = []
    monkeypatch.setattr(sheet, "_detect_models", lambda: calls.append(True))

    sheet._save()

    assert calls == [True]


def test_model_choice_sets_vision_support_and_autofills_vision_model(monkeypatch):
    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.ui.settings_providers import ProviderSettingsSheet

    vis = Provider(name="gemini", kind="gemini", model="gemini-3.5-flash",
                   api_key="g", capabilities=("chat", "vision", "image"))
    monkeypatch.setattr(providers, "list_names", lambda: ["gemini"])
    monkeypatch.setattr(providers, "active_name", lambda: "gemini")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: vis)

    _app()
    host = QWidget()
    sheet = ProviderSettingsSheet(host)
    monkeypatch.setattr(sheet, "_detect_models", lambda: None)
    sheet._vision_model.setText("")
    sheet._choose_detected_model("gemini-3.5-flash")

    assert "didukung" in sheet._vision_hint.text()
    assert sheet._vision_model.text() == "gemini-3.5-flash"


def test_non_vision_provider_marks_unsupported(monkeypatch):
    from jarvis.agent import providers
    from jarvis.agent.providers import Provider
    from jarvis.ui.settings_providers import ProviderSettingsSheet

    novis = Provider(name="openai", kind="openai_compat", model="m",
                     base_url="https://x/v1", api_key="k",
                     capabilities=("chat",))
    monkeypatch.setattr(providers, "list_names", lambda: ["openai"])
    monkeypatch.setattr(providers, "active_name", lambda: "openai")
    monkeypatch.setattr(providers, "get_provider", lambda _name=None: novis)

    _app()
    host = QWidget()
    sheet = ProviderSettingsSheet(host)
    monkeypatch.setattr(sheet, "_detect_models", lambda: None)
    sheet._update_vision_support("m")
    assert "tidak didukung" in sheet._vision_hint.text()