"""Adapter YouTube lama ke satu OAuth Google MK50.

Tidak ada token OAuth YouTube kedua. API key publik tetap secret terpisah;
operasi authenticated memakai ``google_auth`` beserta gate scope/toggle nyata.
"""
from __future__ import annotations

from jarvis.core import config, secrets_store
from jarvis.integrations import google_auth

SCOPES = [google_auth.SCOPES["youtube"]["write"]]


def creds_file():
    """Path legacy hanya untuk migrasi/audit; tidak pernah dibaca/ditulis."""
    return config.resolve_path("config/youtube_oauth.json")


def _api_key_name() -> str:
    return str(config.get("integrations.youtube.api_key_secret_name",
                          "jarvis/youtube/data_api_v3"))


def api_key() -> str | None:
    """YouTube API key read-only; Gemini key bukan substitusi."""
    return secrets_store.get(_api_key_name())


def access_token() -> str | None:
    """Token OAuth Google terpadu, hanya jika YouTube write benar-benar aktif."""
    if not google_auth.has_write_scope("youtube"):
        return None
    try:
        return google_auth.access_token(SCOPES)
    except google_auth.GoogleAuthError:
        return None


def is_authorized() -> bool:
    return access_token() is not None
