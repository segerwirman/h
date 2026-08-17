"""Text-mode LLM client (google-genai) for summarization, routing and NLP.

The live audio pipeline (Gemini Live, voice Charon) stays in the legacy
``main.JarvisLive`` — this client is for non-audio calls only. Every call is
blocking and must run off the UI thread.
"""
from __future__ import annotations

import os
import threading
from typing import Callable, Iterator

from jarvis.core import config
from jarvis.core import log

_logger = log.get("llm")
_client = None
_client_lock = threading.Lock()


def api_key() -> str | None:
    try:
        from jarvis.core import secrets_store
        return secrets_store.get("jarvis/llm/gemini") \
            or os.environ.get("GEMINI_API_KEY") \
            or os.environ.get("GOOGLE_API_KEY") \
            or None
    except Exception:
        return None


def _request_timeout_ms() -> int:
    try:
        seconds = float(config.get("llm.request_timeout_s", 6))
    except (TypeError, ValueError):
        seconds = 6.0
    seconds = max(0.1, min(seconds, 120.0))
    return int(seconds * 1000)


def _get_client():
    global _client
    with _client_lock:
        if _client is None:
            key = api_key()
            if not key:
                return None
            from google import genai
            from google.genai import types
            _client = genai.Client(
                api_key=key,
                http_options=types.HttpOptions(timeout=_request_timeout_ms()))
        return _client


def reset_client() -> None:
    """Drop the cached client — next call rebuilds with the current API key.
    Used by the settings sheet so a key change applies without restart."""
    global _client
    with _client_lock:
        _client = None
    _logger.info("llm.client_reset")


def available() -> bool:
    return _get_client() is not None


def probe() -> tuple[bool, str]:
    """Perform a bounded-by-caller provider request, not just client creation."""
    client = _get_client()
    if client is None:
        return False, "credential tidak tersedia"
    model = config.get("llm.text_model", "gemini-3.5-flash")
    try:
        response = client.models.generate_content(
            model=model,
            contents="Reply with OK only.",
        )
    except Exception as exc:                                # noqa: BLE001
        _logger.warning("llm.probe_failed", error=type(exc).__name__)
        return False, "provider tidak merespons"
    if not (getattr(response, "text", "") or "").strip():
        return False, "provider memberi respons kosong"
    return True, "provider responded"


def _agent_provider_generate(prompt: str, system: str | None = None) -> str:
    """Fallback ke provider aktif agent bila kunci Gemini tidak tersedia.

    Menjaga jalur legacy (ringkasan dokumen, router LLM) tetap hidup saat
    Settings memakai provider non-Gemini; mengembalikan '' bila provider
    aktif pun tidak siap — bukan klaim sukses.
    """
    try:
        from jarvis.agent import llm_client
        client = llm_client.client(None)
        if client is None or not client.available():
            return ""
        return str(client.generate(prompt, system=system) or "").strip()
    except Exception:                                        # noqa: BLE001
        return ""


def generate(prompt: str, system: str | None = None,
             model: str | None = None) -> str:
    """Blocking single-shot generation. Returns '' on failure."""
    client = _get_client()
    if client is None:
        return _agent_provider_generate(prompt, system=system)
    model = model or config.get("llm.text_model", "gemini-3.5-flash")
    try:
        from google.genai import types
        cfg = types.GenerateContentConfig(system_instruction=system) if system else None
        resp = client.models.generate_content(model=model, contents=prompt, config=cfg)
        return (resp.text or "").strip()
    except Exception as e:
        _logger.error("llm.generate_failed", error=str(e)[:200])
        return ""


def stream(prompt: str, system: str | None = None,
           model: str | None = None) -> Iterator[str]:
    """Yield text chunks. Yields nothing on failure."""
    client = _get_client()
    if client is None:
        return
    model = model or config.get("llm.text_model", "gemini-3.5-flash")
    try:
        from google.genai import types
        cfg = types.GenerateContentConfig(system_instruction=system) if system else None
        for chunk in client.models.generate_content_stream(
                model=model, contents=prompt, config=cfg):
            if chunk.text:
                yield chunk.text
    except Exception as e:
        _logger.error("llm.stream_failed", error=str(e)[:200])


def generate_async(prompt: str, on_done: Callable[[str], None],
                   system: str | None = None, model: str | None = None) -> None:
    """Fire-and-forget generation on a worker thread."""
    threading.Thread(
        target=lambda: on_done(generate(prompt, system, model)),
        daemon=True, name="llm-generate",
    ).start()
