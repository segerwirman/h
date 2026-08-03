"""Phase WA0 — WhatsApp readiness gate.

Gate boolean murni: dependency check, credential absence check, toggle
config, dan allowlist policy placeholder. Tidak ada kredensial nyata,
jaringan, atau live client — hanya status boolean yang jujur.
"""
from __future__ import annotations

import importlib.util

TOKEN_KEY = "jarvis/whatsapp/token"
PHONE_ID_KEY = "jarvis/whatsapp/phone_id"
_ENABLED_KEY = "integrations.whatsapp.enabled"
_ALLOWED_IDS_KEY = "integrations.whatsapp.allowed_ids"
# Paket resmi Meta untuk WhatsApp Business/Cloud API.
_DEPENDENCY_MODULES = ("whatsapp", "whatsapp_business_python")


def _dependency_available() -> bool:
    return any(importlib.util.find_spec(module) is not None
               for module in _DEPENDENCY_MODULES)


def _has_secret(key: str) -> bool:
    """Keberadaan secret sebagai boolean; nilai tidak pernah dipertahankan."""
    try:
        from jarvis.core import secrets_store
        return bool(secrets_store.get(key))
    except Exception:  # noqa: BLE001
        return False


def _config_flag(key: str) -> bool:
    try:
        from jarvis.core import config
        return bool(config.get(key, False))
    except Exception:  # noqa: BLE001
        return False


def _config_allowlist() -> bool:
    try:
        from jarvis.core import config
        value = config.get(_ALLOWED_IDS_KEY, None)
        return bool(value)
    except Exception:  # noqa: BLE001
        return False


def dependency_available() -> bool:
    """SDK WhatsApp terpasang? (official API shape: boolean)."""
    return _dependency_available()


def credentials_ready() -> bool:
    """Token + phone id tersimpan? Absence → False, bukan crash."""
    return _has_secret(TOKEN_KEY) and _has_secret(PHONE_ID_KEY)


def toggle_enabled() -> bool:
    return _config_flag(_ENABLED_KEY)


def allowlist_configured() -> bool:
    """Policy placeholder: allowlist non-kosong di config."""
    return _config_allowlist()


def client_available() -> bool:
    """Dependency + kredensial siap (official API shape: boolean)."""
    return dependency_available() and credentials_ready()


def service_available() -> bool:
    """Client siap + toggle aktif + allowlist placeholder terisi."""
    return client_available() and toggle_enabled() and allowlist_configured()


def readiness() -> dict[str, bool]:
    """Rincian gate per check — metadata-only, tanpa nilai secret."""
    return {
        "dependency_available": dependency_available(),
        "credentials_ready": credentials_ready(),
        "toggle_enabled": toggle_enabled(),
        "allowlist_configured": allowlist_configured(),
        "client_available": client_available(),
        "service_available": service_available(),
    }


def readiness_summary() -> str:
    report = readiness()
    return "\n".join(f"{name}: {status}" for name, status in report.items())


__all__ = [
    "dependency_available", "credentials_ready", "toggle_enabled",
    "allowlist_configured", "client_available", "service_available",
    "readiness", "readiness_summary",
]
