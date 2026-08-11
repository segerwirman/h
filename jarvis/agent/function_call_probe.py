"""Live FunctionCall capability probe for OpenAI-compatible providers.

The probe uses a synthetic echo tool and never executes a real Jarvis tool.
It verifies the complete two-step contract: the provider requests exactly one
tool call, then accepts a synthetic tool result without requesting it again.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from urllib.parse import urlparse
from uuid import uuid4

from jarvis.agent import providers
from jarvis.agent.llm_client import LLMClient


TOOL_NAME = "validation_echo"


@dataclass(frozen=True)
class FunctionCallProbeResult:
    ok: bool
    provider: str
    model: str
    transport: str
    first_call_count: int = 0
    followup_call_count: int = 0
    call_id_present: bool = False
    error: str = ""


def _tool_schema() -> list[dict[str, Any]]:
    return [{
        "type": "function",
        "function": {
            "name": TOOL_NAME,
            "description": "Return the supplied synthetic validation value.",
            "parameters": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
                "additionalProperties": False,
            },
        },
    }]


def _failure(result: FunctionCallProbeResult, message: str,
             *, first: int = 0, followup: int = 0,
             call_id_present: bool = False) -> FunctionCallProbeResult:
    return FunctionCallProbeResult(
        ok=False,
        provider=result.provider,
        model=result.model,
        transport=result.transport,
        first_call_count=first,
        followup_call_count=followup,
        call_id_present=call_id_present,
        error=message[:240],
    )


def validate_function_call(client: Any, *, provider_name: str,
                           model: str, transport: str,
                           nonce: str | None = None) -> FunctionCallProbeResult:
    """Validate one FunctionCall and its non-repeating follow-up."""
    value = nonce or f"probe-{uuid4().hex[:12]}"
    base = FunctionCallProbeResult(
        ok=False, provider=provider_name, model=model, transport=transport)
    tools = _tool_schema()
    messages: list[dict[str, Any]] = [
        {
            "role": "system",
            "content": (
                f"Call {TOOL_NAME} exactly once with value {value}. "
                "After its result arrives, answer briefly and do not call it again."
            ),
        },
        {"role": "user", "content": "Run the synthetic validation now."},
    ]

    first = client.chat(messages, tools=tools, temperature=0.0, max_tokens=128)
    if not first.ok:
        return _failure(base, f"first request failed: {first.error or 'unknown'}")
    calls = list(first.tool_calls or [])
    if len(calls) != 1:
        return _failure(base, "provider did not return exactly one FunctionCall",
                        first=len(calls))
    call = calls[0]
    call_id_present = bool(str(call.id or "").strip())
    if call.name != TOOL_NAME:
        return _failure(base, f"unexpected FunctionCall name: {call.name}",
                        first=1, call_id_present=call_id_present)
    if str((call.arguments or {}).get("value", "")) != value:
        return _failure(base, "FunctionCall arguments did not preserve nonce",
                        first=1, call_id_present=call_id_present)

    messages.extend([
        {
            "role": "assistant",
            "content": first.content,
            "tool_calls": [{
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(call.arguments, ensure_ascii=True),
                },
            }],
        },
        {
            "role": "tool",
            "tool_call_id": call.id,
            "name": call.name,
            "content": json.dumps({"ok": True, "echo": value}),
        },
    ])
    followup = client.chat(
        messages, tools=tools, temperature=0.0, max_tokens=128)
    if not followup.ok:
        return _failure(
            base, f"follow-up failed: {followup.error or 'unknown'}",
            first=1, call_id_present=call_id_present)
    repeated = list(followup.tool_calls or [])
    if repeated:
        return _failure(base, "FunctionCall repeated after tool result",
                        first=1, followup=len(repeated),
                        call_id_present=call_id_present)
    return FunctionCallProbeResult(
        ok=True,
        provider=provider_name,
        model=model,
        transport=transport,
        first_call_count=1,
        followup_call_count=0,
        call_id_present=call_id_present,
    )


def run_custom_probe(*, allow_insecure_http: bool = False,
                     nonce: str | None = None) -> FunctionCallProbeResult:
    """Run the live probe against the configured custom provider."""
    provider = providers.get_provider("custom")
    parsed = urlparse(provider.base_url)
    transport = parsed.scheme.lower() or "unknown"
    base = FunctionCallProbeResult(
        ok=False,
        provider=provider.name,
        model=provider.model,
        transport=transport,
    )
    if provider.kind != "openai_compat":
        return _failure(base, "custom provider is not OpenAI-compatible")
    if not provider.configured():
        return _failure(base, "custom provider is not fully configured")
    if providers.insecure_plaintext_base_url(provider.base_url) \
            and not allow_insecure_http:
        return _failure(base, "HTTP endpoint requires explicit opt-in")
    return validate_function_call(
        LLMClient(provider),
        provider_name=provider.name,
        model=provider.model,
        transport=transport,
        nonce=nonce,
    )


__all__ = [
    "FunctionCallProbeResult",
    "TOOL_NAME",
    "run_custom_probe",
    "validate_function_call",
]
