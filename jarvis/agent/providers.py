"""Registry provider LLM: metadata di JSON, secret di ``secrets_store``.

``config/providers.json`` hanya menyimpan metadata (model/base URL/pilihan
aktif). API key dan token OAuth tidak pernah ditulis ke sana. Entri plaintext
lama dimigrasikan oleh :mod:`jarvis.core.secret_migration`.
"""
from __future__ import annotations

import json
import ipaddress
import os
import threading
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from jarvis.core import config, log

_logger = log.get("agent.providers")
_lock = threading.Lock()

PROVIDERS_FILE = "config/providers.json"

CAPABILITY_LABELS: dict[str, str] = {
    "chat": "Chat",
    "tools": "Tools",
    "streaming": "Streaming",
    "vision": "Vision",
    "image": "Image generation",
    "embeddings": "Embeddings",
}


def _trusted_local_base_url(value: str) -> bool:
    """Return True only for loopback, private-IP, or ``.local`` endpoints.

    A provider with ``auth: none`` must never silently turn an arbitrary
    internet URL into a trusted "local" heavy provider.  This check is
    deliberately metadata-only; the cached runtime health probe remains the
    place to establish whether a valid OpenAI-compatible server is listening.
    """

    try:
        parsed = urlparse(str(value or "").strip())
        host = (parsed.hostname or "").rstrip(".").casefold()
    except (TypeError, ValueError):
        return False
    if parsed.scheme not in {"http", "https"} or not host:
        return False
    if host == "localhost" or host.endswith(".local"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return False
    return bool(address.is_loopback or address.is_private)


def insecure_plaintext_base_url(value: str) -> bool:
    """True bila credential akan melintas TANPA enkripsi ke host non-lokal.

    Provider ``openai_compat`` mengirim API key sebagai header
    ``Authorization: Bearer``. Di atas ``http://`` polos ke host publik, kunci
    itu terbaca oleh siapa pun di jalurnya.

    Endpoint lokal (loopback, IP privat, ``.local``) sengaja dikecualikan:
    plaintext wajar di sana, dan peringatan yang terlalu cerewet akan
    diabaikan orang justru saat ia benar-benar penting.
    """
    try:
        parsed = urlparse(str(value or "").strip())
    except (TypeError, ValueError):
        return False
    if parsed.scheme != "http":
        return False
    return not _trusted_local_base_url(value)


DEFAULTS: dict[str, dict] = {
    "gemini": {
        "kind": "gemini", "label": "Google Gemini", "base_url": "",
        "api_key": "", "model": "gemini-3.5-flash",
        "vision_model": "gemini-3.5-flash", "env_key": "GEMINI_API_KEY",
        "auth": "api_key", "capabilities": ["chat", "vision", "image"],
    },
    "openai": {
        "kind": "openai_compat", "label": "OpenAI",
        "base_url": "https://api.openai.com/v1", "api_key": "",
        "model": "gpt-5.2", "vision_model": "gpt-5.2",
        "env_key": "OPENAI_API_KEY", "auth": "api_key",
        "capabilities": ["chat", "image", "vision"],
    },
    "openai_oauth": {
        "kind": "openai_oauth",
        "label": "OpenAI ChatGPT/Codex (OAuth)",
        "base_url": "https://chatgpt.com/backend-api/codex",
        # Katalog Codex bersifat account/rollout-specific. Jangan mengirim
        # fallback statis yang dapat berubah menjadi HTTP 404 setelah login.
        "api_key": "", "model": "", "vision_model": "",
        "auth": "oauth", "capabilities": ["chat", "tools", "streaming", "image"],
    },
    "anthropic": {
        "kind": "anthropic", "label": "Anthropic Claude", "base_url": "",
        "api_key": "", "model": "claude-sonnet-5",
        "vision_model": "claude-sonnet-5", "env_key": "ANTHROPIC_API_KEY",
        "auth": "api_key", "capabilities": ["chat", "vision"],
    },
    "anthropic_oauth": {
        "kind": "anthropic_oauth",
        "label": "Anthropic Claude (OAuth)",
        "base_url": "https://api.anthropic.com", "api_key": "",
        "model": "claude-sonnet-5", "vision_model": "claude-sonnet-5",
        "auth": "oauth", "capabilities": ["chat", "vision"],
    },
    "openrouter": {
        "kind": "openai_compat", "label": "OpenRouter",
        "base_url": "https://openrouter.ai/api/v1", "api_key": "",
        "model": "", "vision_model": "", "env_key": "OPENROUTER_API_KEY",
        "auth": "api_key", "capabilities": ["chat"],
    },
    "local": {
        "kind": "openai_compat", "label": "Local (OpenAI-compatible)",
        "base_url": "http://localhost:1234/v1",
        # Placeholder publik, bukan credential. Banyak server lokal menuntut
        # string non-kosong meskipun tidak melakukan autentikasi.
        "api_key": "lm-studio", "model": "", "vision_model": "",
        "env_key": "LLM_API_KEY", "env_base_url": "LLM_BASE_URL",
        "auth": "none", "capabilities": ["chat"],
    },
    "custom": {
        "kind": "openai_compat", "label": "Custom (OpenAI-compatible)",
        "base_url": "", "api_key": "", "model": "", "vision_model": "",
        "env_key": "CUSTOM_LLM_API_KEY", "auth": "api_key",
        "capabilities": ["chat"],
    },
}


@dataclass
class Provider:
    name: str
    kind: str
    label: str = ""
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    vision_model: str = ""
    auth: str = "api_key"
    enabled: bool = False
    capabilities: tuple[str, ...] = ()
    extra: dict = field(default_factory=dict)

    def supports(self, capability: str) -> bool:
        """Capability hanya tersedia bila dikenal dan dideklarasikan eksplisit."""
        key = str(capability or "").strip().lower()
        return key in CAPABILITY_LABELS and key in {
            str(item).strip().lower() for item in self.capabilities}

    def capability_details(self) -> dict[str, dict[str, bool | str]]:
        """Status capability aman untuk UI/policy; unknown tidak dipromosikan."""
        return {
            key: {"label": label, "available": self.supports(key)}
            for key, label in CAPABILITY_LABELS.items()
        }

    def configured(self) -> bool:
        if self.auth == "oauth":
            return self.enabled and bool(self.model) \
                and self.supports("chat")
        if self.auth == "none":
            return bool(self.model) and _trusted_local_base_url(self.base_url)
        if self.kind == "openai_compat":
            return bool(self.api_key) and bool(self.base_url) \
                and bool(self.model)
        return bool(self.api_key) and bool(self.model)

    def resolve_vision_model(self) -> str:
        return self.vision_model or self.model

    def safe_dict(self) -> dict:
        return {
            "name": self.name, "kind": self.kind, "label": self.label,
            "base_url": self.base_url, "model": self.model,
            "vision_model": self.vision_model, "auth": self.auth,
            "enabled": self.enabled, "capabilities": list(self.capabilities),
            "capability_details": self.capability_details(),
            "api_key_set": bool(self.api_key),
        }


def _path() -> Path:
    return config.resolve_path(config.get("agent.providers_file",
                                           PROVIDERS_FILE))


def _read_file() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as exc:
        _logger.error("providers.read_failed", error=str(exc)[:120])
        return {}


def _write_file(data: dict) -> bool:
    try:
        path = _path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        return True
    except Exception as exc:
        _logger.error("providers.write_failed", error=str(exc)[:120])
        return False


def _keyring_key(name: str) -> str:
    """Nama historis dipertahankan agar seam/test lama tidak pecah."""
    try:
        from jarvis.core import secrets_store
        return secrets_store.get(f"jarvis/llm/{name}") or ""
    except Exception:
        return ""


def _oauth_connected(name: str) -> bool:
    try:
        if name == "openai_oauth":
            from jarvis.integrations import openai_oauth
            return openai_oauth.connected()
        if name == "anthropic_oauth":
            from jarvis.integrations import anthropic_oauth
            return anthropic_oauth.connected()
    except Exception:
        return False
    return False


def list_names() -> list[str]:
    data = _read_file()
    names = list(DEFAULTS)
    for extra in (data.get("providers") or {}):
        if extra not in names:
            names.append(extra)
    return names


def active_name() -> str:
    data = _read_file()
    name = data.get("active") or str(config.get("agent.provider", "gemini"))
    return name if name in list_names() else "gemini"


def get_provider(name: str | None = None) -> Provider:
    """Provider tergabung: defaults <- metadata JSON <- secret store/env."""
    with _lock:
        data = _read_file()
        name = name or data.get("active") \
            or str(config.get("agent.provider", "gemini"))
        base = dict(DEFAULTS.get(name, DEFAULTS["custom"]))
        stored = (data.get("providers") or {}).get(name) or {}
        # api_key dari file sengaja tidak pernah dikonsumsi; startup migration
        # memindahkannya hanya jika backend terenkripsi berhasil.
        merged = {**base, **{k: v for k, v in stored.items()
                             if k != "api_key" and v not in (None, "")}}
        p = Provider(
            name=name,
            kind=str(merged.get("kind", "openai_compat")),
            label=str(merged.get("label", name)),
            base_url=str(merged.get("base_url", "")),
            api_key=str(base.get("api_key", "")),
            model=str(merged.get("model", "")),
            vision_model=str(merged.get("vision_model", "")),
            auth=str(merged.get("auth", "api_key")),
            enabled=bool(merged.get("enabled", False)),
            capabilities=tuple(str(x).strip().lower() for x in
                               (merged.get("capabilities") or ())),
            extra={k: v for k, v in merged.items()
                   if k not in ("kind", "label", "base_url", "api_key",
                                "model", "vision_model", "auth", "enabled",
                                "capabilities", "env_key", "env_base_url")},
        )
        if p.auth == "oauth":
            p.enabled = _oauth_connected(name)
            return p
        stored_key = _keyring_key(name)
        if stored_key:
            p.api_key = stored_key
        if not p.api_key:
            env_key = str(merged.get("env_key", ""))
            if env_key:
                p.api_key = os.environ.get(env_key, "")
        if not p.api_key and p.kind == "gemini":
            p.api_key = os.environ.get("GOOGLE_API_KEY", "")
        if not p.base_url:
            env_base = str(merged.get("env_base_url", ""))
            if env_base:
                p.base_url = os.environ.get(env_base, "")
        p.enabled = p.configured()
        return p


def vision_provider() -> Provider:
    data = _read_file()
    name = data.get("vision_active") or ""
    p = get_provider(name or None)
    if name and not p.configured():
        p = get_provider(None)
    if not p.configured():
        gemini = get_provider("gemini")
        if gemini.configured():
            return gemini
    return p


def save_provider(name: str, *, kind: str | None = None,
                  base_url: str | None = None, api_key: str | None = None,
                  model: str | None = None, vision_model: str | None = None,
                  label: str | None = None) -> bool:
    """Simpan metadata provider; API key hanya ke backend terenkripsi."""
    with _lock:
        data = _read_file()
        providers = data.setdefault("providers", {})
        entry = providers.setdefault(name, {})
        for key, value in (("kind", kind), ("base_url", base_url),
                           ("model", model),
                           ("vision_model", vision_model), ("label", label)):
            if value is not None:
                entry[key] = value
        if api_key is not None:
            try:
                from jarvis.core import secrets_store
                saved = secrets_store.set(f"jarvis/llm/{name}", api_key) \
                    if api_key else secrets_store.delete(f"jarvis/llm/{name}")
            except Exception:
                saved = False
            if not saved:
                _logger.error("providers.secret_save_failed", provider=name)
                return False
        entry.pop("api_key", None)
        ok = _write_file(data)
    if ok:
        _logger.info("providers.saved", provider=name)
        reset_clients()
    return ok


def set_active(name: str, vision: bool = False) -> bool:
    with _lock:
        data = _read_file()
        data["vision_active" if vision else "active"] = name
        ok = _write_file(data)
    if ok:
        _logger.info("providers.active_changed", provider=name,
                     for_vision=vision)
        reset_clients()
    return ok


def delete_provider(name: str) -> bool:
    """Hapus metadata dan credential provider tersimpan secara aman."""
    with _lock:
        data = _read_file()
        data.setdefault("providers", {}).pop(name, None)
        if data.get("active") == name:
            data["active"] = "gemini" if name != "gemini" else "openai"
        if data.get("vision_active") == name:
            data.pop("vision_active", None)
        try:
            from jarvis.core import secrets_store
            secret_ok = secrets_store.delete(f"jarvis/llm/{name}")
        except Exception:
            secret_ok = False
        if not secret_ok:
            return False
        ok = _write_file(data)
    if ok:
        reset_clients()
        _logger.info("providers.deleted", provider=name)
    return ok


def chat_provider_names(only_enabled: bool = False) -> list[str]:
    out: list[str] = []
    for name in list_names():
        try:
            provider = get_provider(name)
        except Exception:
            continue
        if provider.supports("chat") and (not only_enabled or provider.configured()):
            out.append(name)
    return out


def reset_clients() -> None:
    try:
        from jarvis.agent import llm_client
        llm_client.reset()
    except Exception:
        pass
