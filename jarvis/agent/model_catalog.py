"""Credential-safe, opt-in model catalog discovery for configured providers.

Catalog responses are used only to populate a local settings selector.  They are
never persisted, logged, or sent to the agent prompt.
"""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.agent.providers import Provider

DEFAULT_TIMEOUT_S = 20


class ModelCatalogError(RuntimeError):
    """Safe error class; ``code`` is suitable for the UI, not raw provider text."""

    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


@dataclass(frozen=True)
class ModelCatalog:
    models: tuple[str, ...]
    source: str  # account | unsupported


def _names(payload: object) -> tuple[str, ...]:
    if isinstance(payload, dict):
        entries = payload.get("data", payload.get("models", []))
    else:
        entries = payload
    if not isinstance(entries, list):
        raise ModelCatalogError("invalid_catalog")
    models: list[str] = []
    for entry in entries:
        if isinstance(entry, str):
            name = entry
        elif isinstance(entry, dict):
            name = str(entry.get("id") or entry.get("name") or
                       entry.get("slug") or entry.get("model") or "")
        else:
            continue
        if name and name not in models:
            models.append(name)
    return tuple(models)


def _openai_compat(provider: Provider, timeout_s: float) -> ModelCatalog:
    if not provider.base_url:
        raise ModelCatalogError("catalog_not_configured")
    import requests
    headers = ({"Authorization": f"Bearer {provider.api_key}"}
               if provider.api_key else {})
    try:
        response = requests.get(provider.base_url.rstrip("/") + "/models",
                                headers=headers, timeout=timeout_s)
    except Exception as exc:                                # noqa: BLE001
        raise ModelCatalogError("catalog_network") from exc
    if response.status_code in (401, 403):
        raise ModelCatalogError("catalog_auth_rejected")
    if response.status_code != 200:
        raise ModelCatalogError("catalog_unavailable")
    try:
        return ModelCatalog(_names(response.json()), "account")
    except ModelCatalogError:
        raise
    except Exception as exc:                                # noqa: BLE001
        raise ModelCatalogError("invalid_catalog") from exc


def _gemini(provider: Provider, timeout_s: float) -> ModelCatalog:
    if not provider.api_key:
        raise ModelCatalogError("catalog_not_configured")
    import requests
    try:
        response = requests.get(
            "https://generativelanguage.googleapis.com/v1beta/models",
            headers={"x-goog-api-key": provider.api_key}, timeout=timeout_s)
    except Exception as exc:                                # noqa: BLE001
        raise ModelCatalogError("catalog_network") from exc
    if response.status_code in (401, 403):
        raise ModelCatalogError("catalog_auth_rejected")
    if response.status_code != 200:
        raise ModelCatalogError("catalog_unavailable")
    try:
        payload = response.json()
        entries = payload.get("models", []) if isinstance(payload, dict) else []
        chat_entries = [
            {"id": str(entry.get("name") or "").removeprefix("models/")}
            for entry in entries if isinstance(entry, dict)
            and "generateContent" in entry.get("supportedGenerationMethods", [])
        ]
        return ModelCatalog(_names({"models": chat_entries}), "account")
    except ModelCatalogError:
        raise
    except Exception as exc:                                # noqa: BLE001
        raise ModelCatalogError("invalid_catalog") from exc


def discover(provider: Provider, timeout_s: float = DEFAULT_TIMEOUT_S) -> ModelCatalog:
    """Return selectable models from a provider's documented catalog seam.

    Anthropic does not publish a general account-model listing endpoint, so it
    stays explicit/manual rather than inventing a model list.  GPT Image is
    deliberately not treated as a chat model here.
    """
    if provider.name == "openai_oauth":
        from jarvis.integrations import openai_oauth
        return ModelCatalog(tuple(openai_oauth.available_models(timeout_s)), "account")
    if provider.kind == "gemini":
        return _gemini(provider, timeout_s)
    if provider.kind == "openai_compat":
        return _openai_compat(provider, timeout_s)
    return ModelCatalog((), "unsupported")
