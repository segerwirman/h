"""§7.3.3 opsi 2 — jalur API key image generation: gate available(),
resolusi model/quality, seksi settings."""
from __future__ import annotations

import pytest

from jarvis.agent import providers
from jarvis.agent.providers import Provider
from jarvis.agent.tools import image_gen
from jarvis.core import config, settings_service


@pytest.fixture()
def fake_cfg(monkeypatch):
    values: dict = {}
    orig = config.get

    def fake(key, default=None):
        if key in values:
            return values[key]
        if key.startswith(("image_generation.", "agent.image")):
            return default
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    return values


def _provider(kind, api_key="", base_url="", auth="api_key"):
    return Provider(name="x", kind=kind, api_key=api_key, base_url=base_url,
                    label="x", model="m", auth=auth,
                    capabilities=("image",) if kind in ("gemini", "openai_compat")
                    else ())


# ── gate available() ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("kind,key,url,auth,expect", [
    ("openai_compat", "sk-x", "https://api.openai.com/v1", "api_key", True),
    ("openai_compat", "", "http://localhost:1234/v1", "none", True),
    ("openai_compat", "", "", "api_key", False),
    ("gemini", "g-key", "", "api_key", True),
    ("gemini", "", "", "api_key", False),
    ("anthropic", "a-key", "", "api_key", False),  # tidak ada endpoint image
])
def test_available_gate(fake_cfg, monkeypatch, kind, key, url, auth, expect):
    monkeypatch.setattr(providers, "get_provider",
                        lambda name=None: _provider(kind, key, url, auth))
    assert image_gen.available() is expect


def test_available_tidak_pernah_raise(fake_cfg, monkeypatch):
    def boom(name=None):
        raise RuntimeError("meledak")
    monkeypatch.setattr(providers, "get_provider", boom)
    assert image_gen.available() is False


def test_available_menolak_provider_tanpa_capability_image(fake_cfg, monkeypatch):
    provider = _provider("openai_compat", api_key="sk-x")
    provider.capabilities = ()
    monkeypatch.setattr(providers, "get_provider", lambda name=None: provider)

    assert image_gen.available() is False


def test_available_menolak_openai_remote_tanpa_api_key(fake_cfg, monkeypatch):
    remote = _provider("openai_compat", base_url="https://api.openai.com/v1")
    monkeypatch.setattr(providers, "get_provider", lambda name=None: remote)

    assert image_gen.available() is False


def test_available_oauth_image_aktif_saat_terhubung(fake_cfg, monkeypatch):
    from jarvis.integrations import openai_oauth
    oauth = Provider(name="openai_oauth", kind="openai_oauth", auth="oauth",
                     label="OAuth", model="", capabilities=("chat", "image"))
    monkeypatch.setattr(providers, "get_provider", lambda name=None: oauth)
    monkeypatch.setattr(openai_oauth, "image_generation_supported",
                        lambda: True)
    assert image_gen.available() is True


def test_available_oauth_image_ditolak_saat_belum_login(fake_cfg, monkeypatch):
    from jarvis.integrations import openai_oauth
    oauth = Provider(name="openai_oauth", kind="openai_oauth", auth="oauth",
                     label="OAuth", model="", capabilities=("chat", "image"))
    monkeypatch.setattr(providers, "get_provider", lambda name=None: oauth)
    monkeypatch.setattr(openai_oauth, "image_generation_supported",
                        lambda: False)
    assert image_gen.available() is False


# ── resolusi model + quality ─────────────────────────────────────────────────

def test_resolve_default_gpt_image_2(fake_cfg):
    req = image_gen.resolve_openai_request()
    assert req == {"model": "gpt-image-2", "size": "1024x1024",
                   "quality": "instant"}


def test_resolve_quality_hanya_gpt_image_2(fake_cfg):
    fake_cfg["image_generation.model"] = "flux-dev"
    req = image_gen.resolve_openai_request()
    assert req["model"] == "flux-dev"
    assert "quality" not in req                # server lain: tanpa param asing


def test_resolve_config_dan_arg(fake_cfg):
    fake_cfg["image_generation.model"] = "gpt-image-2-2026-04-21"
    fake_cfg["image_generation.quality"] = "thinking"
    fake_cfg["image_generation.size"] = "2048x2048"
    assert image_gen.resolve_openai_request() == {
        "model": "gpt-image-2-2026-04-21", "size": "2048x2048",
        "quality": "thinking"}
    # argumen tool menang atas default config
    assert image_gen.resolve_openai_request("512x512")["size"] == "512x512"


def test_resolve_legacy_fallback(fake_cfg):
    fake_cfg["agent.image_model_openai"] = "gpt-image-1"
    req = image_gen.resolve_openai_request()
    assert req["model"] == "gpt-image-1" and "quality" not in req


def test_provider_name_prioritas(fake_cfg):
    fake_cfg["agent.image_provider"] = "gemini"
    assert image_gen._image_provider_name() == "gemini"
    fake_cfg["image_generation.provider"] = "custom"
    assert image_gen._image_provider_name() == "custom"


# ── seksi settings ───────────────────────────────────────────────────────────

def test_seksi_image_ada_dan_valid(monkeypatch):
    from jarvis.integrations import openai_oauth
    # Deterministik: paksa OAuth belum login agar tidak bocor dari test lain.
    monkeypatch.setattr(openai_oauth, "image_generation_supported",
                        lambda: False)
    secs = {s["id"]: s for s in settings_service.sections()}
    fields = {f["key"]: f for f in secs["image"]["fields"]}
    assert fields["image_generation.quality"]["choices"] == \
        ["instant", "thinking", "low", "medium", "high"]
    assert "" in fields["image_generation.provider"]["choices"]
    assert "anthropic" not in fields["image_generation.provider"]["choices"]
    # OAuth belum login → tidak boleh muncul.
    assert "openai_oauth" not in fields["image_generation.provider"]["choices"]
    assert "API key" in secs["image"]["hint"]
