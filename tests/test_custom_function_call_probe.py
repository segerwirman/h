from __future__ import annotations

from jarvis.agent.function_call_probe import (
    TOOL_NAME,
    validate_function_call,
)
from jarvis.agent.llm_client import ChatResponse, ToolCall


class _Client:
    def __init__(self, *responses: ChatResponse):
        self.responses = list(responses)
        self.requests = []

    def chat(self, messages, **kwargs):
        self.requests.append((messages, kwargs))
        return self.responses.pop(0)


def _call(value="probe-fixed", *, name=TOOL_NAME, call_id="call-1"):
    return ToolCall(id=call_id, name=name, arguments={"value": value})


def test_probe_accepts_one_call_then_no_repeat():
    client = _Client(
        ChatResponse(tool_calls=[_call()]),
        ChatResponse(content="done"),
    )

    result = validate_function_call(
        client,
        provider_name="custom",
        model="model-x",
        transport="http",
        nonce="probe-fixed",
    )

    assert result.ok is True
    assert result.first_call_count == 1
    assert result.followup_call_count == 0
    assert result.call_id_present is True
    assert len(client.requests) == 2
    followup_messages = client.requests[1][0]
    assert followup_messages[-1]["role"] == "tool"
    assert followup_messages[-1]["tool_call_id"] == "call-1"


def test_probe_rejects_unexpected_call_name():
    client = _Client(ChatResponse(tool_calls=[_call(name="wrong_tool")]))

    result = validate_function_call(
        client,
        provider_name="custom",
        model="model-x",
        transport="http",
        nonce="probe-fixed",
    )

    assert result.ok is False
    assert "unexpected FunctionCall name" in result.error


def test_probe_rejects_repeat_after_tool_result():
    client = _Client(
        ChatResponse(tool_calls=[_call()]),
        ChatResponse(tool_calls=[_call(call_id="call-2")]),
    )

    result = validate_function_call(
        client,
        provider_name="custom",
        model="model-x",
        transport="http",
        nonce="probe-fixed",
    )

    assert result.ok is False
    assert result.followup_call_count == 1
    assert result.error == "FunctionCall repeated after tool result"
