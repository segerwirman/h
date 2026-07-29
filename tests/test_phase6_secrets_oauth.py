"""Checklist master §9.4: fallback encrypted, OAuth loopback, Settings."""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request

import pytest

from jarvis.core import secret_migration, secrets_store
from jarvis.integrations import anthropic_oauth, oauth_loopback


@pytest.fixture()
def isolated_fernet(tmp_path, monkeypatch):
    monkeypatch.setattr(secrets_store, "_jarvis_dir", lambda: tmp_path / ".jarvis")
    monkeypatch.setattr(secrets_store, "_backend",
                        secrets_store._FernetBackend())
    monkeypatch.setattr(secrets_store, "_initialized", True)
    return tmp_path / ".jarvis"


def test_fernet_tanpa_keyring_encrypted_dan_permission(isolated_fernet):
    secret = "token-yang-tidak-boleh-plaintext"
    assert secrets_store.set("oauth/test", secret)
    assert secrets_store.get("oauth/test") == secret
    keyfile = isolated_fernet / ".keyfile"
    datafile = isolated_fernet / "secrets.dat"
    assert secret.encode() not in datafile.read_bytes()
    assert secrets_store.permissions_strict(keyfile)
    assert secrets_store.permissions_strict(datafile)
    assert secrets_store.permissions_strict(isolated_fernet)


def test_loopback_pkce_browser_dan_state(monkeypatch):
    opened = threading.Event()
    captured = {}

    def browser(url):
        captured["url"] = url
        opened.set()
        return True

    monkeypatch.setattr(oauth_loopback.webbrowser, "open", browser)
    result = {}

    def run():
        result.update(oauth_loopback.authorize(
            authorize_url="https://auth.example/authorize", client_id="client",
            scope="chat", ports=(0,), callback_path="/callback",
            exchange=lambda code, verifier, redirect: {
                "code": code, "verifier": verifier, "redirect": redirect},
            timeout_s=5))

    thread = threading.Thread(target=run)
    thread.start()
    assert opened.wait(2)
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(captured["url"]).query)
    callback = (f"{query['redirect_uri'][0]}?code=authorization-code&"
                f"state={query['state'][0]}")
    with urllib.request.urlopen(callback, timeout=2) as response:
        assert response.status == 200
    thread.join(3)
    assert result["code"] == "authorization-code"
    assert result["redirect"].startswith("http://localhost:")
    assert query["code_challenge_method"] == ["S256"]
    assert "code_challenge" in query


def test_loopback_menolak_state_yang_salah(monkeypatch):
    opened = threading.Event()
    captured = {}
    errors = []

    def browser(url):
        captured["url"] = url
        opened.set()
        return True

    monkeypatch.setattr(oauth_loopback.webbrowser, "open", browser)

    def run():
        try:
            oauth_loopback.authorize(
                authorize_url="https://auth.example/authorize",
                client_id="client", scope="chat", ports=(0,),
                exchange=lambda *_args: {"unexpected": True}, timeout_s=5)
        except oauth_loopback.LoopbackOAuthError as exc:
            errors.append(str(exc))

    thread = threading.Thread(target=run)
    thread.start()
    assert opened.wait(2)
    query = urllib.parse.parse_qs(
        urllib.parse.urlparse(captured["url"]).query)
    callback = f"{query['redirect_uri'][0]}?code=x&state=wrong"
    with pytest.raises(urllib.error.HTTPError) as response:
        urllib.request.urlopen(callback, timeout=2)
    assert response.value.code == 400
    thread.join(3)
    assert errors and "state OAuth tidak cocok" in errors[0]


def test_anthropic_login_token_store_dan_client_bearer(monkeypatch):
    store = {}
    monkeypatch.setattr(secrets_store, "available", lambda: True)
    monkeypatch.setattr(secrets_store, "get", lambda key: store.get(key))
    monkeypatch.setattr(secrets_store, "set",
                        lambda key, value: (store.__setitem__(key, value), True)[1])
    monkeypatch.setattr(anthropic_oauth.oauth_loopback, "authorize",
                        lambda **kwargs: {"access_token": "cc-access",
                                          "refresh_token": "refresh",
                                          "expires_in": 3600})
    assert anthropic_oauth.start_login(open_browser=False)["connected"]
    assert anthropic_oauth.connected()
    kwargs = anthropic_oauth.client_kwargs()
    assert kwargs["auth_token"] == "cc-access"
    assert "oauth-2025-04-20" in \
        kwargs["default_headers"]["anthropic-beta"]


def test_migrasi_plaintext_hanya_hapus_setelah_store_sukses(
        tmp_path, monkeypatch):
    providers = tmp_path / "providers.json"
    api_keys = tmp_path / "api_keys.json"
    youtube = tmp_path / "youtube_oauth.json"
    google = tmp_path / "google_token.json"
    providers.write_text(json.dumps({"providers": {"openai": {
        "api_key": "provider-secret", "model": "m"}}}), encoding="utf-8")
    api_keys.write_text(json.dumps({"gemini_api_key": "gemini-secret",
                                    "os_system": "windows"}), encoding="utf-8")
    youtube.write_text(json.dumps({"refresh_token": "refresh-secret"}),
                       encoding="utf-8")
    original_resolve = secret_migration.config.resolve_path

    def resolve(path):
        mapping = {"config/providers.json": providers,
                   "config/api_keys.json": api_keys,
                   "config/youtube_oauth.json": youtube,
                   "google_token.json": google}
        return mapping.get(str(path), original_resolve(path))

    monkeypatch.setattr(secret_migration.config, "resolve_path", resolve)
    from jarvis.agent import paths as agent_paths
    monkeypatch.setattr(agent_paths, "data_dir", lambda: tmp_path)
    values = {}
    monkeypatch.setattr(secrets_store, "set",
                        lambda key, value: (values.__setitem__(key, value), True)[1])
    monkeypatch.setattr(secrets_store, "get", lambda key: values.get(key))
    report = secret_migration.migrate_legacy()
    assert report.ok and len(report.migrated) == 3
    assert "api_key" not in json.loads(
        providers.read_text(encoding="utf-8"))["providers"]["openai"]
    assert json.loads(api_keys.read_text(encoding="utf-8")) == {
        "os_system": "windows"}
    assert json.loads(youtube.read_text(encoding="utf-8")) == {}


def test_settings_menampilkan_backend_dan_heavy_provider(monkeypatch):
    from jarvis.agent import providers
    from jarvis.core import settings_service
    monkeypatch.setattr(providers, "chat_provider_names",
                        lambda only_enabled=False: ["openai_oauth",
                                                    "anthropic_oauth"])
    sections = {s["id"]: s for s in settings_service.resolve()}
    safety = {f["key"]: f for f in sections["safety"]["fields"]}
    assert safety["security.secrets_backend"]["value"] in (
        "Keyring OS", "DPAPI", "File terenkripsi")
    model = {f["key"]: f for f in sections["model"]["fields"]}
    assert "openai_oauth" in model["routing.heavy.provider"]["choices"]


def test_pilihan_settings_provider_berat_dipakai_t2(tmp_path, monkeypatch):
    from jarvis.agent import llm_client, model_routing, providers
    from jarvis.agent.providers import Provider
    from jarvis.core import config, settings_service

    original_path = config.CONFIG_PATH
    cfg = tmp_path / "config.yaml"
    cfg.write_text("routing:\n  light:\n    provider: gemini\n"
                   "  heavy:\n    provider: \"\"\n    fallback: []\n",
                   encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    config.reload()
    monkeypatch.setattr(providers, "chat_provider_names",
                        lambda only_enabled=False: ["openai_oauth"])
    oauth_provider = Provider(
        name="openai_oauth", kind="openai_oauth", model="gpt-test",
        auth="oauth", enabled=True, capabilities=("chat",))
    monkeypatch.setattr(model_routing, "get_provider",
                        lambda name: oauth_provider)
    sentinel = object()
    monkeypatch.setattr(llm_client, "client", lambda name=None: sentinel)

    ok, _ = settings_service.set_value(
        "routing.heavy.provider", "openai_oauth", "choice")
    assert ok is True
    client, name, _ = model_routing.heavy_resolution()
    assert client is sentinel and name == "openai_oauth"
    monkeypatch.setattr(config, "CONFIG_PATH", original_path)
    config.reload()


def test_legacy_config_manager_tidak_menulis_secret_plaintext(
        tmp_path, monkeypatch):
    from memory import config_manager

    config_file = tmp_path / "api_keys.json"
    config_file.write_text('{"os_system":"windows"}', encoding="utf-8")
    monkeypatch.setattr(config_manager, "CONFIG_FILE", config_file)
    stored = {}
    monkeypatch.setattr(secrets_store, "set",
                        lambda key, value: (stored.__setitem__(key, value),
                                            True)[1])
    monkeypatch.setattr(secrets_store, "get", lambda key: stored.get(key))

    config_manager.save_api_keys("gemini-secret")
    assert "gemini_api_key" not in config_file.read_text(encoding="utf-8")
    assert config_manager.get_gemini_key() == "gemini-secret"
