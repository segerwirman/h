"""Phase 25 — credential-free canary probe.

Menghasilkan status boolean per provider (ready/absent/disabled/skipped/
unknown) TANPA menyimpan, meng-log, mengirim, atau mengembalikan nilai
kredensial apa pun. Nilai secret hanya dibaca untuk diubah menjadi bool
lalu dibuang; probe tidak pernah menulis ke secrets store.
"""
from __future__ import annotations

import os

VALID_STATUS = ("ready", "absent", "disabled", "skipped", "unknown")


def _has_secret(key: str) -> bool:
    """Keberadaan secret sebagai boolean; nilai tidak pernah dipertahankan."""
    try:
        from jarvis.core import secrets_store
        return bool(secrets_store.get(key))
    except Exception:  # noqa: BLE001
        return False


def probe_telegram() -> str:
    try:
        from jarvis.integrations import telegram_control
        if not telegram_control.master_enabled():
            return "disabled"
        token_ok = _has_secret("jarvis/telegram/bot_token")
        allow_ok = _has_secret("jarvis/telegram/allowed_ids")
        return "ready" if (token_ok and allow_ok) else "absent"
    except Exception:  # noqa: BLE001
        return "unknown"


def probe_google() -> str:
    client_ok = _has_secret("jarvis/google/client_id")
    secret_ok = _has_secret("jarvis/google/client_secret")
    return "ready" if (client_ok and secret_ok) else "absent"


def probe_llm() -> str:
    stored = _has_secret("jarvis/llm/gemini")
    env = bool(os.environ.get("GEMINI_API_KEY")
               or os.environ.get("GOOGLE_API_KEY"))
    return "ready" if (stored or env) else "absent"


def probe_voice(*, no_voice: bool) -> str:
    if no_voice:
        return "skipped"
    return "ready" if probe_llm() == "ready" else "absent"


def probe_providers(*, no_voice: bool = False) -> dict[str, str]:
    """Status boolean per provider; hanya label, tidak pernah nilai secret."""
    return {
        "telegram": probe_telegram(),
        "google": probe_google(),
        "llm": probe_llm(),
        "voice": probe_voice(no_voice=no_voice),
        "image": "unknown",      # belum ada probe aman tanpa menyentuh nilai
        "whatsapp": "unknown",   # belum ada integrasi
    }


def probe_summary(*, no_voice: bool = False) -> str:
    """Ringkasan metadata-only per provider (tanpa nilai apa pun)."""
    report = probe_providers(no_voice=no_voice)
    return "\n".join(f"{name}: {status}" for name, status in report.items())


__all__ = ["probe_providers", "probe_summary", "VALID_STATUS"]
