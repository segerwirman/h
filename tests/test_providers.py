"""Provider registry — roundtrip file, fallback env, sensor kunci."""
from __future__ import annotations

import pytest

import jarvis.agent.providers as prov


@pytest.fixture(autouse=True)
def isolated_file(tmp_path, monkeypatch):
    secret_data = {}
    monkeypatch.setattr(prov, "_path",
                        lambda: tmp_path / "providers.json")
    monkeypatch.setattr(prov, "_keyring_key",
                        lambda name: secret_data.get(name, ""))
    from jarvis.core import secrets_store
    monkeypatch.setattr(secrets_store, "set",
                        lambda key, value: (secret_data.__setitem__(
                            key.removeprefix("jarvis/llm/"), value), True)[1])
    monkeypatch.setattr(secrets_store, "delete",
                        lambda key: (secret_data.pop(
                            key.removeprefix("jarvis/llm/"), None), True)[1])
    monkeypatch.setattr(prov, "reset_clients", lambda: None)
    yield


def test_defaults_present():
    names = prov.list_names()
    for n in ("gemini", "openai", "openai_oauth", "anthropic",
              "anthropic_oauth", "local", "custom"):
        assert n in names


def test_openai_oauth_mengiklankan_capability_yang_didukung(monkeypatch):
    monkeypatch.setattr(prov, "_oauth_connected", lambda _name: True)
    provider = prov.get_provider("openai_oauth")

    assert {"chat", "tools", "streaming", "image"} <= set(provider.capabilities)
    assert "vision" not in provider.capabilities


def test_openai_oauth_baru_menunggu_katalog_model_akun(monkeypatch):
    monkeypatch.setattr(prov, "_oauth_connected", lambda _name: True)

    provider = prov.get_provider("openai_oauth")

    assert provider.model == ""
    assert provider.configured() is False


def test_save_and_get_roundtrip():
    assert prov.save_provider("local", base_url="http://127.0.0.1:11434/v1",
                              api_key="rahasia", model="qwen2.5:14b")
    p = prov.get_provider("local")
    assert p.kind == "openai_compat"
    assert p.base_url == "http://127.0.0.1:11434/v1"
    assert p.api_key == "rahasia"
    assert p.model == "qwen2.5:14b"
    assert p.configured()
    data = prov._read_file()
    assert "api_key" not in data["providers"]["local"]


def test_local_needs_base_url_and_model():
    p = prov.get_provider("custom")
    assert not p.configured()


def test_auth_none_local_rejects_public_internet_endpoint():
    prov.save_provider(
        "local",
        base_url="https://api.meta.ai/v1",
        model="muse-spark-1.1",
    )
    assert prov.get_provider("local").configured() is False


def test_auth_none_local_accepts_private_lan_endpoint():
    prov.save_provider(
        "local",
        base_url="http://192.168.1.25:1234/v1",
        model="qwen",
    )
    assert prov.get_provider("local").configured() is True


def test_env_fallback_for_key(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "dari-env")
    p = prov.get_provider("openai")
    assert p.api_key == "dari-env"


def test_active_switch():
    prov.save_provider("local", base_url="http://x/v1", model="m")
    assert prov.set_active("local")
    assert prov.active_name() == "local"
    p = prov.get_provider()
    assert p.name == "local"


def test_safe_dict_never_leaks_key():
    prov.save_provider("openai", api_key="sk-super-rahasia", model="gpt-5.2")
    p = prov.get_provider("openai")
    safe = p.safe_dict()
    flat = str(safe)
    assert "sk-super-rahasia" not in flat
    assert safe["api_key_set"] is True


def test_vision_provider_falls_back():
    # tidak ada yang dikonfigurasi → vision_provider tetap mengembalikan
    # objek Provider tanpa meledak
    p = prov.vision_provider()
    assert p is not None
    assert hasattr(p, "resolve_vision_model")
