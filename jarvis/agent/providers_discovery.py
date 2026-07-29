"""Discovery model provider yang ketat, aman, dan tidak memblokir UI.

Katalog hanya berada di memori proses. Credential tidak pernah dicache, dilog,
atau dipersisten; cache-key memakai fingerprint SHA-256 satu arah.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import threading
import time
from typing import Any

DEFAULT_TIMEOUT_S = 5.0
CACHE_TTL_S = 300.0


@dataclass(frozen=True)
class ModelInfo:
    id: str
    label: str
    context_window: int | None = None
    supports_tools: bool = False

    def display_label(self) -> str:
        suffix = f" — {self.context_window // 1000}k" if self.context_window else ""
        return f"{self.label}{suffix}"


class DiscoveryError(RuntimeError):
    """Pesan singkat, aman ditampilkan ke user; tanpa payload/provider secret."""


_cache: dict[tuple[str, str, str], tuple[float, tuple[ModelInfo, ...]]] = {}
_lock = threading.RLock()


def clear_cache() -> None:
    with _lock:
        _cache.clear()


def _credential_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _cache_key(provider) -> tuple[str, str, str]:
    return (str(provider.name), str(provider.base_url).rstrip("/"),
            _credential_fingerprint(str(getattr(provider, "api_key", ""))))


def _get(url: str, *, headers: dict[str, str], params: dict[str, str] | None = None,
         timeout: float = DEFAULT_TIMEOUT_S):
    import requests
    return requests.get(url, headers=headers, params=params, timeout=timeout)


def _error_for_status(status: int) -> DiscoveryError:
    if status in (401, 403):
        return DiscoveryError("kredensial ditolak")
    if status == 429:
        return DiscoveryError("kuota provider sedang habis")
    return DiscoveryError("provider tidak dapat mengembalikan katalog model")


def _as_int(value: Any) -> int | None:
    try:
        parsed = int(value)
        return parsed if parsed > 0 else None
    except (TypeError, ValueError):
        return None


def _model(entry: Any) -> ModelInfo | None:
    if isinstance(entry, str):
        return ModelInfo(entry, entry)
    if not isinstance(entry, dict):
        return None
    ident = str(entry.get("id") or entry.get("name") or entry.get("slug")
                or entry.get("model") or "").removeprefix("models/")
    if not ident:
        return None
    label = str(entry.get("display_name") or entry.get("displayName")
                or entry.get("label") or ident)
    context = _as_int(entry.get("context_window") or entry.get("context_length")
                      or entry.get("inputTokenLimit") or entry.get("max_context_length"))
    tools = bool(entry.get("supports_tools") or entry.get("tools")
                 or entry.get("function_calling"))
    return ModelInfo(ident, label, context, tools)


def _models(payload: Any, *, gemini: bool = False) -> tuple[ModelInfo, ...]:
    entries = payload.get("data", payload.get("models", [])) if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        raise DiscoveryError("format katalog tidak dikenali")
    out: list[ModelInfo] = []
    for entry in entries:
        if gemini:
            if not isinstance(entry, dict) or "generateContent" not in entry.get("supportedGenerationMethods", []):
                continue
        item = _model(entry)
        if item and item.id not in {x.id for x in out}:
            out.append(item)
    return tuple(out)


def _request(provider, timeout_s: float):
    kind = str(provider.kind)
    base = str(getattr(provider, "base_url", "")).rstrip("/")
    key = str(getattr(provider, "api_key", ""))
    if str(getattr(provider, "auth", "")) == "oauth":
        if str(provider.name) == "openai_oauth":
            from jarvis.integrations import openai_oauth
            try:
                names = openai_oauth.available_models(timeout_s=timeout_s)
            except Exception as exc:  # OAuth module already keeps errors safe.
                raise DiscoveryError("OAuth tidak dapat mengambil katalog model") from exc
            return tuple(ModelInfo(str(name), str(name)) for name in names if name)
        # Anthropic OAuth uses its stored token as the API credential seam.
        try:
            from jarvis.core import secrets_store
            key = secrets_store.get(f"jarvis/oauth/{provider.name}") or key
        except Exception:
            pass
    if kind == "gemini":
        if not key:
            raise DiscoveryError("API key belum diisi")
        url = "https://generativelanguage.googleapis.com/v1beta/models"
        headers, params, is_gemini = {}, {"key": key}, True
    elif kind == "anthropic" or str(provider.name).startswith("anthropic"):
        if not key:
            raise DiscoveryError("API key belum diisi")
        url = (base or "https://api.anthropic.com") + "/v1/models"
        headers, params, is_gemini = {"x-api-key": key, "anthropic-version": "2023-06-01"}, None, False
    else:
        if not base:
            raise DiscoveryError("Base URL belum diisi")
        url = base + "/models"
        headers = {"Authorization": f"Bearer {key}"} if key else {}
        params, is_gemini = None, False
    try:
        response = _get(url, headers=headers, params=params, timeout=timeout_s)
    except Exception as exc:  # noqa: BLE001
        raise DiscoveryError("tidak bisa menjangkau provider") from exc
    if response.status_code != 200:
        raise _error_for_status(response.status_code)
    try:
        return _models(response.json(), gemini=is_gemini)
    except DiscoveryError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DiscoveryError("format katalog tidak dikenali") from exc


def discover(provider, *, timeout_s: float = DEFAULT_TIMEOUT_S) -> tuple[ModelInfo, ...]:
    """Ambil katalog provider. Maksimum lima detik; hasil cache per credential."""
    timeout_s = min(DEFAULT_TIMEOUT_S, max(0.1, float(timeout_s)))
    cache_key = _cache_key(provider)
    now = time.monotonic()
    with _lock:
        cached = _cache.get(cache_key)
        if cached and now - cached[0] < CACHE_TTL_S:
            return cached[1]
    models = _request(provider, timeout_s)
    with _lock:
        _cache[cache_key] = (now, models)
    return models


def manual_fallback_allowed(error: DiscoveryError) -> bool:
    return "format katalog" in str(error) or "katalog model" in str(error)


__all__ = ["CACHE_TTL_S", "DEFAULT_TIMEOUT_S", "DiscoveryError", "ModelInfo",
           "clear_cache", "discover", "manual_fallback_allowed"]
