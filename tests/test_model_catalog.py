"""Account-scoped model catalog discovery, without persisting provider data."""
from __future__ import annotations

import sys
import types

from jarvis.agent.providers import Provider


class _Resp:
    status_code = 200

    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body


def test_openai_compat_catalog_uses_provider_models_endpoint(monkeypatch):
    from jarvis.agent import model_catalog

    provider = Provider(name="openai", kind="openai_compat", api_key="secret",
                        base_url="https://api.example/v1", model="",
                        capabilities=("chat",))

    def get(url, *, headers, timeout):
        assert url == "https://api.example/v1/models"
        assert headers == {"Authorization": "Bearer secret"}
        assert timeout == model_catalog.DEFAULT_TIMEOUT_S
        return _Resp({"data": [
            {"id": "gpt-chat"}, {"id": "gpt-chat"}, {"id": ""},
        ]})

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=get))

    catalog = model_catalog.discover(provider)

    assert catalog.models == ("gpt-chat",)
    assert catalog.source == "account"


def test_openai_oauth_catalog_delegates_to_oauth_backend(monkeypatch):
    from jarvis.agent import model_catalog
    from jarvis.integrations import openai_oauth

    provider = Provider(name="openai_oauth", kind="openai_oauth", auth="oauth",
                        model="", capabilities=("chat",))
    monkeypatch.setattr(openai_oauth, "available_models",
                        lambda timeout_s: ["gpt-codex-a", "gpt-codex-b"])

    catalog = model_catalog.discover(provider, timeout_s=9)

    assert catalog.models == ("gpt-codex-a", "gpt-codex-b")
    assert catalog.source == "account"


def test_gemini_catalog_filters_to_generate_content_models(monkeypatch):
    from jarvis.agent import model_catalog

    provider = Provider(name="gemini", kind="gemini", api_key="secret",
                        model="", capabilities=("chat",))

    def get(url, *, headers, timeout):
        assert url == "https://generativelanguage.googleapis.com/v1beta/models"
        assert headers == {"x-goog-api-key": "secret"}
        assert timeout == model_catalog.DEFAULT_TIMEOUT_S
        return _Resp({"models": [
            {"name": "models/gemini-chat", "supportedGenerationMethods":
             ["generateContent"]},
            {"name": "models/text-embedding", "supportedGenerationMethods":
             ["embedContent"]},
        ]})

    monkeypatch.setitem(sys.modules, "requests", types.SimpleNamespace(get=get))

    assert model_catalog.discover(provider).models == ("gemini-chat",)


def test_catalog_declares_unsupported_without_network(monkeypatch):
    from jarvis.agent import model_catalog

    provider = Provider(name="anthropic", kind="anthropic", api_key="secret",
                        model="claude", capabilities=("chat",))

    catalog = model_catalog.discover(provider)

    assert catalog.models == ()
    assert catalog.source == "unsupported"
