"""Fase 2 — provider policy eksplisit per role."""
from __future__ import annotations

from jarvis.agent import llm_client, model_routing
from jarvis.agent.providers import Provider
from jarvis.core import config


def _provider(name: str, *, model: str = "model-default") -> Provider:
    return Provider(name=name, kind="openai_compat", label=name,
                    api_key="test-key", base_url="http://test/v1", model=model,
                    capabilities=("chat",))


def test_conversation_auto_memakai_lane_light(monkeypatch):
    values = {
        "routing.light.provider": "gemini",
        "routing.light.model": "",
        "routing.conversation.provider": "auto",
        "routing.conversation.model": "",
    }
    original_get = config.get
    monkeypatch.setattr(
        config, "get", lambda key, default=None: values.get(key, original_get(key, default)))
    table = {"gemini": _provider("gemini", model="gemini-light")}
    monkeypatch.setattr(model_routing, "get_provider", lambda name=None: table[name])
    sentinel = object()
    monkeypatch.setattr(llm_client, "client", lambda name=None: sentinel)

    client, provider, reason = model_routing.conversation_resolution()

    assert client is sentinel
    assert provider == "gemini"
    assert "light" in reason


def test_capability_tidak_dikenal_dianggap_tidak_tersedia():
    provider = _provider("uji")
    provider.capabilities = ("chat", "TOOLS", "mystery")

    assert provider.supports("chat") is True
    assert provider.supports("tools") is True
    assert provider.supports("vision") is False
    assert provider.supports("mystery") is False
    assert provider.capability_details()["tools"]["label"] == "Tools"
    assert provider.capability_details()["vision"]["available"] is False


def test_role_statuses_membedakan_lima_role_dan_heavy_tidak_siap(monkeypatch):
    values = {
        "routing.light.provider": "gemini",
        "routing.light.model": "",
        "llm.live_model": "gemini-live-test",
    }
    original_get = config.get
    monkeypatch.setattr(
        config, "get", lambda key, default=None: values.get(key, original_get(key, default)))
    monkeypatch.setattr(model_routing, "get_provider",
                        lambda name=None: _provider(name or "gemini"))
    monkeypatch.setattr(model_routing, "heavy_resolution",
                        lambda: (None, "", "heavy belum dikonfigurasi"))
    monkeypatch.setattr(model_routing, "conversation_resolution",
                        lambda: (object(), "gemini", "conversation memakai light"))

    roles = model_routing.role_statuses()

    assert set(roles) == {"voice_transport", "light", "heavy", "conversation", "auxiliary"}
    assert roles["voice_transport"]["provider"] == "gemini_live"
    assert roles["light"]["configured"] is True
    assert roles["heavy"]["configured"] is False
    assert roles["heavy"]["reason"] == "heavy belum dikonfigurasi"
    assert roles["conversation"]["provider"] == "gemini"


def test_config_dan_settings_mengekspos_conversation_policy(monkeypatch):
    from jarvis.core import settings_service

    config.reload()
    assert config.get("routing.conversation.provider") == "auto"
    assert config.get("routing.conversation.model") == ""

    monkeypatch.setattr(model_routing, "role_statuses", lambda: {
        "voice_transport": {"provider": "gemini_live", "model": "live",
                            "configured": False, "reason": "runtime-managed"},
        "light": {"provider": "gemini", "model": "flash", "configured": True,
                  "reason": "light"},
        "heavy": {"provider": "", "model": "", "configured": False,
                  "reason": "belum dikonfigurasi"},
        "conversation": {"provider": "gemini", "model": "flash",
                         "configured": True, "reason": "light"},
        "auxiliary": {"provider": "auto", "model": "", "configured": False,
                      "reason": "per slot"},
    })
    fields = {field["key"] for section in settings_service.sections()
              for field in section["fields"]}

    assert {"routing.conversation.provider", "routing.conversation.model"} <= fields
    assert "HEAVY: not configured" in settings_service.provider_role_summary()


def test_event_provider_policy_hanya_memuat_metadata_aman(monkeypatch):
    from jarvis.core.bus import BUS

    events = []
    monkeypatch.setattr(BUS, "publish",
                        lambda topic, **data: events.append((topic, data)))

    model_routing.publish_provider_event(
        "heavy", "openai_oauth", "routing.heavy: openai_oauth", "selected")

    assert events == [("agent.provider_policy", {
        "role": "heavy", "provider": "openai_oauth",
        "reason": "routing.heavy: openai_oauth", "event": "selected",
    })]
