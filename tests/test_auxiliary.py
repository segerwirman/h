"""§7.1 — auxiliary model router: resolusi per slot, fallback, wiring."""
from __future__ import annotations

import pytest

from jarvis.agent import auxiliary, llm_client
from jarvis.agent.providers import Provider
from jarvis.core import config


def _prov(name, kind="openai_compat", api_key="k", base_url="u", model="m"):
    return Provider(name=name, kind=kind, label=name, api_key=api_key,
                    base_url=base_url, model=model)


@pytest.fixture()
def cfg(monkeypatch):
    values: dict = {}
    orig = config.get

    def fake(key, default=None):
        if key in values:
            return values[key]
        if key.startswith("auxiliary."):
            return default
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    return values


def test_slot_ids_delapan():
    assert len(auxiliary.SLOTS) == 8
    assert {"vision", "reflect", "compression", "web_extract", "title_gen",
            "approval", "curator_review", "embedding"} == \
        set(auxiliary.SLOT_IDS)


def test_resolve_auto_ikut_utama(cfg, monkeypatch):
    main = _prov("gemini", kind="gemini", model="gemini-3.5-flash")
    monkeypatch.setattr(auxiliary, "get_provider",
                        lambda name=None: main)
    p, model = auxiliary.resolve("reflect")
    assert p.name == "gemini" and model == "gemini-3.5-flash"


def test_resolve_override_provider_dan_model(cfg, monkeypatch):
    cfg["auxiliary.reflect.provider"] = "local"
    cfg["auxiliary.reflect.model"] = "muse-spark-1.1"
    provs = {"local": _prov("local"), None: _prov("gemini", kind="gemini")}
    monkeypatch.setattr(auxiliary, "get_provider",
                        lambda name=None: provs[name])
    p, model = auxiliary.resolve("reflect")
    assert p.name == "local" and model == "muse-spark-1.1"


def test_resolve_override_tak_tersedia_fallback_utama(cfg, monkeypatch):
    cfg["auxiliary.vision.provider"] = "openai"
    provs = {"openai": _prov("openai", api_key="", base_url=""),
             None: _prov("gemini", kind="gemini", model="g")}
    monkeypatch.setattr(auxiliary, "get_provider",
                        lambda name=None: provs[name])
    p, model = auxiliary.resolve("vision")
    assert p.name == "gemini" and model == "g"


def test_resolve_utama_mati_fallback_provider_lain(cfg, monkeypatch):
    provs = {None: _prov("gemini", kind="gemini", api_key=""),
             "gemini": _prov("gemini", kind="gemini", api_key=""),
             "openai": _prov("openai", api_key="sk"),
             "anthropic": _prov("anthropic", kind="anthropic", api_key=""),
             "local": _prov("local", api_key="", base_url=""),
             "custom": _prov("custom", api_key="", base_url="")}
    monkeypatch.setattr(auxiliary, "get_provider",
                        lambda name=None: provs[name])
    monkeypatch.setattr(auxiliary, "list_names",
                        lambda: ["gemini", "openai", "anthropic", "local",
                                 "custom"])
    p, _ = auxiliary.resolve("title_gen")
    assert p.name == "openai"


def test_client_for_auto_pakai_jalur_lama(cfg, monkeypatch):
    sentinel_vision = object()
    sentinel_main = object()
    monkeypatch.setattr(llm_client, "vision_client",
                        lambda: sentinel_vision)
    monkeypatch.setattr(llm_client, "client",
                        lambda name=None: sentinel_main)
    assert auxiliary.client_for("vision") is sentinel_vision
    assert auxiliary.client_for("reflect") is sentinel_main


def test_client_for_override_model(cfg, monkeypatch):
    cfg["auxiliary.reflect.provider"] = "local"
    cfg["auxiliary.reflect.model"] = "model-lain"
    monkeypatch.setattr(auxiliary, "get_provider",
                        lambda name=None: _prov("local", model="m-default"))
    cl = auxiliary.client_for("reflect")
    assert isinstance(cl, llm_client.LLMClient)
    assert cl.provider.model == "model-lain"


def test_seksi_settings_auxiliary():
    from jarvis.core import settings_service
    secs = {s["id"]: s for s in settings_service.sections()}
    fields = {f["key"]: f for f in secs["auxiliary"]["fields"]}
    assert "auxiliary.vision.provider" in fields
    assert fields["auxiliary.vision.provider"]["choices"][0] == "auto"
    assert "(aktif)" in fields["auxiliary.vision.provider"]["label"]
    assert "(aktif)" not in fields["auxiliary.title_gen.provider"]["label"]
    assert fields["auxiliary.response_composer.enabled"]["type"] == "bool"
    assert fields["auxiliary.response_composer.provider"]["choices"][0] == "auto"
    assert fields["auxiliary.response_composer.model"]["type"] == "text"
    assert fields["auxiliary.response_composer.timeout_s"]["type"] == "float"
    # embedding terkunci
    assert fields["auxiliary.embedding.provider"]["type"] == "readonly"
    assert "auxiliary.embedding.model" not in fields


def test_config_write_slot_auxiliary(tmp_path, monkeypatch):
    from jarvis.core import config_write
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text(
        "auxiliary:\n  vision:\n    provider: \"auto\"\n    model: \"\"\n"
        "  reflect:\n    provider: \"auto\"\n    model: \"\"\n",
        encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg_file)
    config.reload()
    assert config_write.set_scalar("auxiliary.reflect.model",
                                   "muse-spark-1.1")
    assert config.get("auxiliary.reflect.model") == "muse-spark-1.1"
    assert config.get("auxiliary.vision.model") == ""       # slot lain utuh
    monkeypatch.undo()
    config.reload()
