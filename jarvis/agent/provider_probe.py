"""Side-effect-free readiness probe for an agent work model."""
from __future__ import annotations

import re
from dataclasses import dataclass

from jarvis.agent.providers import Provider


@dataclass(frozen=True)
class AgentProbeResult:
    chat_ok: bool
    tools_ok: bool
    detail: str

    @property
    def ready(self) -> bool:
        return self.chat_ok and self.tools_ok


_PROBE_TOOL = {
    "type": "function",
    "function": {
        "name": "jarvis_connection_probe",
        "description": (
            "No-op connection probe. Call this exactly once to prove that "
            "the selected model supports native agent tool calling."
        ),
        "parameters": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
}


def probe(provider: Provider, *, timeout_s: float = 12.0) -> AgentProbeResult:
    """Verify both chat and function calling without executing a real tool."""

    if not provider.configured():
        return AgentProbeResult(False, False, "provider belum lengkap")
    try:
        from jarvis.agent.llm_client import LLMClient

        client = LLMClient(provider)
        client.timeout_s = max(2.0, min(20.0, float(timeout_s)))
        response = client.chat(
            [
                {
                    "role": "system",
                    "content": (
                        "This is a connection test. Call the supplied "
                        "jarvis_connection_probe tool exactly once. Do not "
                        "perform any other action and do not answer in text."
                    ),
                },
                {
                    "role": "user",
                    "content": "Run the no-op agent connection probe now.",
                },
            ],
            tools=[_PROBE_TOOL],
            temperature=0,
            max_tokens=64,
        )
    except Exception as exc:                                # noqa: BLE001
        return AgentProbeResult(False, False, _safe_error(str(exc)))

    if not response.ok:
        return AgentProbeResult(
            False, False, _safe_error(str(response.error or "")))
    tools_ok = any(
        call.name == "jarvis_connection_probe"
        for call in response.tool_calls
    )
    if tools_ok:
        return AgentProbeResult(
            True, True, "chat dan native tool calling siap")
    return AgentProbeResult(
        True,
        False,
        "chat tersambung, tetapi model tidak menghasilkan function call",
    )


def _safe_error(value: str) -> str:
    """Convert provider errors to a credential-safe UI message."""

    text = str(value or "").casefold()
    if re.search(r"\b(?:401|403)\b|unauthori[sz]ed|forbidden|api.?key", text):
        return "autentikasi provider ditolak"
    if re.search(r"\b404\b|not.?found|unknown.?model", text):
        return "model atau endpoint tidak ditemukan"
    if "tool" in text or "function" in text:
        if "support" in text or "invalid" in text:
            return "model tidak mendukung native tool calling"
    if "timeout" in text or "timed out" in text:
        return "provider melewati batas waktu"
    if "connect" in text or "network" in text:
        return "provider tidak dapat dijangkau"
    return "tes agent gagal pada provider"


__all__ = ["AgentProbeResult", "probe"]
