"""Helper tipis Google API client; auth dan error tetap terpusat."""
from __future__ import annotations

from jarvis.integrations import google_auth


def service(api: str, version: str, scopes: list[str]):
    try:
        from googleapiclient.discovery import build
    except ImportError as exc:
        raise google_auth.GoogleAuthError(
            "google-api-python-client belum terpasang") from exc
    credentials = google_auth.credentials(scopes)
    return build(api, version, credentials=credentials,
                 cache_discovery=False)


def safe_error(exc: Exception) -> str:
    """Pesan user tanpa body HTTP/token yang mungkin sensitif."""
    if isinstance(exc, google_auth.GoogleAuthError):
        return str(exc)[:220]
    if isinstance(exc, ValueError):
        return str(exc)[:220]
    try:
        from googleapiclient.errors import HttpError
        if isinstance(exc, HttpError):
            status = getattr(getattr(exc, "resp", None), "status", "?")
            return f"Google API menolak permintaan (HTTP {status})"
    except ImportError:
        pass
    return f"Google API gagal: {type(exc).__name__}"
