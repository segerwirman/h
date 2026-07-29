"""Image Generation service seam (Capabilities → Tools selector).

Menguji daftar provider + status siap, katalog model, tier gpt-image-2, dan
penulisan config yang aman — tanpa menyentuh config.yaml nyata atau network.
"""
from __future__ import annotations

import pytest

from jarvis.agent import image_gen_service as svc
from jarvis.agent.providers import Provider


@pytest.fixture()
def fake_writes(monkeypatch):
    written: dict[str, str] = {}
    from jarvis.core import config_write
    monkeypatch.setattr(config_write, "set_scalar",
                        lambda key, value: (written.__setitem__(key, value), True)[1])
    return written


def _prov(name, kind, *, api_key="", base_url="", auth="api_key",
          caps=("image",)):
    return Provider(name=name, kind=kind, api_key=api_key, base_url=base_url,
                    auth=auth, label=name, model="m", capabilities=caps)


def test_tiers_are_low_medium_high():
    assert [t["quality"] for t in svc.GPT_IMAGE_TIERS] == ["low", "medium", "high"]


def test_list_providers_marks_ready_and_tags(monkeypatch):
    from jarvis.agent import providers
    from jarvis.integrations import openai_oauth
    catalog = {
        "gemini": _prov("gemini", "gemini", api_key="g"),
        "openai": _prov("openai", "openai_compat",
                        base_url="https://api.openai.com/v1"),      # no key → not ready
        "openai_oauth": _prov("openai_oauth", "openai_oauth", auth="oauth",
                              caps=("chat", "image")),
        "anthropic": _prov("anthropic", "anthropic", api_key="a", caps=("chat",)),
    }
    monkeypatch.setattr(providers, "list_names", lambda: list(catalog))
    monkeypatch.setattr(providers, "get_provider", lambda n=None: catalog[n])
    monkeypatch.setattr(openai_oauth, "image_generation_supported", lambda: True)

    out = {p.name: p for p in svc.list_providers()}
    assert "anthropic" not in out                    # tidak punya capability image
    assert out["gemini"].ready is True and out["gemini"].tag == "paid"
    assert out["openai"].ready is False              # remote OpenAI tanpa key
    assert out["openai_oauth"].tag == "free"
    assert out["openai_oauth"].ready is True


def test_oauth_provider_not_ready_when_logged_out(monkeypatch):
    from jarvis.agent import providers
    from jarvis.integrations import openai_oauth
    catalog = {"openai_oauth": _prov("openai_oauth", "openai_oauth", auth="oauth",
                                     caps=("chat", "image"))}
    monkeypatch.setattr(providers, "list_names", lambda: list(catalog))
    monkeypatch.setattr(providers, "get_provider", lambda n=None: catalog[n])
    monkeypatch.setattr(openai_oauth, "image_generation_supported", lambda: False)
    out = {p.name: p for p in svc.list_providers()}
    assert out["openai_oauth"].ready is False
    assert "sign in" in out["openai_oauth"].reason


def test_models_for_static_defaults():
    assert "imagen-4.0-generate-001" in svc.models_for("gemini")
    assert svc.models_for("openai_oauth") == ["gpt-image-2"]
    assert svc.models_for("unknown") == []


def test_detect_models_falls_back_to_static(monkeypatch):
    from jarvis.agent import providers, model_catalog
    monkeypatch.setattr(providers, "get_provider",
                        lambda n=None: _prov("gemini", "gemini", api_key="g"))

    def boom(_p, timeout_s=20):
        raise model_catalog.ModelCatalogError("catalog_network")

    monkeypatch.setattr(model_catalog, "discover", boom)
    assert svc.detect_models("gemini") == svc.models_for("gemini")


def test_detect_models_uses_catalog(monkeypatch):
    from jarvis.agent import providers, model_catalog
    monkeypatch.setattr(providers, "get_provider",
                        lambda n=None: _prov("openai", "openai_compat",
                                             api_key="k",
                                             base_url="https://x/v1"))
    monkeypatch.setattr(model_catalog, "discover",
                        lambda _p, timeout_s=20: model_catalog.ModelCatalog(
                            ("gpt-image-2", "dall-e-3"), "account"))
    assert svc.detect_models("openai") == ["gpt-image-2", "dall-e-3"]


def test_set_provider_model_quality_writes_config(fake_writes):
    assert svc.set_provider("gemini") is True
    assert svc.set_model("imagen-4.0-generate-001") is True
    assert svc.set_quality("high") is True
    assert fake_writes == {
        "image_generation.provider": "gemini",
        "image_generation.model": "imagen-4.0-generate-001",
        "image_generation.quality": "high",
    }


def test_set_quality_rejects_unknown(fake_writes):
    assert svc.set_quality("ultra") is False
    assert "image_generation.quality" not in fake_writes


def test_select_gpt_image_tier_sets_model_and_quality(fake_writes):
    assert svc.select_gpt_image_tier("medium") is True
    assert fake_writes["image_generation.model"] == "gpt-image-2"
    assert fake_writes["image_generation.quality"] == "medium"


def test_select_gpt_image_tier_rejects_bad_tier(fake_writes):
    assert svc.select_gpt_image_tier("instant") is False
