from __future__ import annotations

from types import SimpleNamespace

from jarvis.agent import llm_client
from jarvis.agent.providers import Provider


def test_embedding_failure_has_latency_circuit_breaker(monkeypatch):
    provider = Provider(
        name="custom",
        kind="openai_compat",
        base_url="https://example.invalid/v1",
        api_key="secret",
        model="chat",
        enabled=True,
        capabilities=("chat",),
    )
    client = llm_client.LLMClient(provider)
    calls = []

    class Embeddings:
        @staticmethod
        def create(**kwargs):
            calls.append(kwargs)
            raise RuntimeError("embedding endpoint unavailable")

    monkeypatch.setattr(
        client,
        "_client",
        lambda: SimpleNamespace(embeddings=Embeddings()),
    )
    clock = {"now": 100.0}
    monkeypatch.setattr(llm_client.time, "monotonic", lambda: clock["now"])
    original_get = llm_client.config.get

    def fake_get(key, default=None):
        if key == "agent.embedding_failure_cooldown_s":
            return 900
        return original_get(key, default)

    monkeypatch.setattr(llm_client.config, "get", fake_get)
    assert client.embed(["one"]) is None
    assert client.embed(["two"]) is None
    assert len(calls) == 1

    clock["now"] += 901
    assert client.embed(["three"]) is None
    assert len(calls) == 2
