from __future__ import annotations

from types import SimpleNamespace

from jarvis.agent import provider_probe
from jarvis.agent.providers import Provider


def _provider() -> Provider:
    return Provider(
        name="custom",
        kind="openai_compat",
        base_url="https://example.invalid/v1",
        api_key="secret",
        model="work-model",
        capabilities=("chat",),
        enabled=True,
    )


def test_probe_requires_function_call_not_only_chat(monkeypatch):
    class Client:
        def __init__(self, _provider):
            self.timeout_s = 0

        @staticmethod
        def chat(*_args, **_kwargs):
            return SimpleNamespace(ok=True, tool_calls=[], error=None)

    monkeypatch.setattr("jarvis.agent.llm_client.LLMClient", Client)
    result = provider_probe.probe(_provider())
    assert result.chat_ok
    assert not result.tools_ok
    assert not result.ready


def test_probe_accepts_exact_noop_tool_call(monkeypatch):
    class Client:
        def __init__(self, _provider):
            self.timeout_s = 0

        @staticmethod
        def chat(*_args, **_kwargs):
            call = SimpleNamespace(name="jarvis_connection_probe")
            return SimpleNamespace(ok=True, tool_calls=[call], error=None)

    monkeypatch.setattr("jarvis.agent.llm_client.LLMClient", Client)
    result = provider_probe.probe(_provider())
    assert result.ready


def test_probe_error_is_safe_and_specific(monkeypatch):
    class Client:
        def __init__(self, _provider):
            self.timeout_s = 0

        @staticmethod
        def chat(*_args, **_kwargs):
            return SimpleNamespace(
                ok=False,
                tool_calls=[],
                error="404 model work-model not found at private endpoint",
            )

    monkeypatch.setattr("jarvis.agent.llm_client.LLMClient", Client)
    result = provider_probe.probe(_provider())
    assert not result.ready
    assert result.detail == "model atau endpoint tidak ditemukan"
    assert "private" not in result.detail
