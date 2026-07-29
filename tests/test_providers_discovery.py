"""Discovery provider: cepat, credential-safe, cache, capability metadata."""
from __future__ import annotations

from types import SimpleNamespace

import pytest


def _provider(**overrides):
    defaults = dict(name="openai", kind="openai_compat", base_url="https://api.test/v1",
                    api_key="secret", auth="api_key", capabilities=("chat", "tools"))
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_openai_compat_mengembalikan_modelinfo_dan_cache(monkeypatch):
    from jarvis.agent import providers_discovery as discovery
    discovery.clear_cache()
    calls = []

    class Response:
        status_code = 200
        def json(self):
            return {"data": [{"id": "gpt-4o", "context_window": 128000,
                              "supports_tools": True}, {"id": "gpt-4o-mini"}]}

    monkeypatch.setattr(discovery, "_get", lambda *a, **k: calls.append((a, k)) or Response())
    first = discovery.discover(_provider())
    second = discovery.discover(_provider())

    assert [m.id for m in first] == ["gpt-4o", "gpt-4o-mini"]
    assert first[0].context_window == 128000
    assert first[0].supports_tools is True
    assert second == first
    assert len(calls) == 1
    assert calls[0][0][0] == "https://api.test/v1/models"
    assert calls[0][1]["timeout"] == 5.0


def test_gemini_filter_generatecontent_dan_hapus_prefix(monkeypatch):
    from jarvis.agent import providers_discovery as discovery
    discovery.clear_cache()

    class Response:
        status_code = 200
        def json(self):
            return {"models": [
                {"name": "models/gemini-ok", "displayName": "Gemini OK",
                 "supportedGenerationMethods": ["generateContent"],
                 "inputTokenLimit": 1048576},
                {"name": "models/embed", "supportedGenerationMethods": ["embedContent"]},
            ]}

    monkeypatch.setattr(discovery, "_get", lambda *a, **k: Response())
    models = discovery.discover(_provider(name="gemini", kind="gemini", base_url=""))
    assert len(models) == 1
    assert models[0].id == "gemini-ok"
    assert models[0].label == "Gemini OK"
    assert models[0].context_window == 1048576


def test_auth_network_dan_format_mengembalikan_error_aman(monkeypatch):
    from jarvis.agent import providers_discovery as discovery
    discovery.clear_cache()

    class Unauthorized:
        status_code = 401
        def json(self): return {}
    monkeypatch.setattr(discovery, "_get", lambda *a, **k: Unauthorized())
    with pytest.raises(discovery.DiscoveryError, match="kredensial"):
        discovery.discover(_provider())

    def offline(*_a, **_k):
        raise OSError("network unavailable")
    monkeypatch.setattr(discovery, "_get", offline)
    with pytest.raises(discovery.DiscoveryError, match="menjangkau"):
        discovery.discover(_provider(base_url="https://other.test/v1"))


def test_anthropic_uses_models_endpoint(monkeypatch):
    from jarvis.agent import providers_discovery as discovery
    discovery.clear_cache()
    seen = {}

    class Response:
        status_code = 200
        def json(self): return {"data": [{"id": "claude-test", "display_name": "Claude Test"}]}
    def fake(url, **kwargs):
        seen.update(url=url, **kwargs)
        return Response()
    monkeypatch.setattr(discovery, "_get", fake)

    models = discovery.discover(_provider(name="anthropic", kind="anthropic", base_url="https://api.anthropic.com"))
    assert models[0].id == "claude-test"
    assert seen["url"].endswith("/v1/models")
    assert seen["headers"]["x-api-key"] == "secret"


def test_manual_fallback_hanya_untuk_error_discovery():
    from jarvis.agent import providers_discovery as discovery
    assert discovery.manual_fallback_allowed(
        discovery.DiscoveryError("format katalog tidak dikenali"))
    assert not discovery.manual_fallback_allowed(
        discovery.DiscoveryError("kredensial ditolak"))
