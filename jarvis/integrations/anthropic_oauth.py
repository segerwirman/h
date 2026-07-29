"""Anthropic Claude OAuth PKCE + loopback (subscription chat/vision)."""
from __future__ import annotations

import json
import threading
import time

from jarvis.core import log, secrets_store
from jarvis.integrations import oauth_loopback

_logger = log.get("integrations.anthropic_oauth")
_lock = threading.Lock()
_status_lock = threading.Lock()
_last_error_code = ""

CLIENT_ID = "9d1c250a-e61b-44d9-88ed-5944d1962f5e"
AUTHORIZE_URL = "https://claude.com/cai/oauth/authorize"
TOKEN_URLS = ("https://platform.claude.com/v1/oauth/token",
              "https://console.anthropic.com/v1/oauth/token")
SCOPES = "org:create_api_key user:profile user:inference"
_STORE_KEY = "jarvis/oauth/anthropic"
_TOKEN_UA = "axios/1.7.9"
_REFRESH_SKEW_S = 60


class OAuthError(RuntimeError):
    """Kesalahan OAuth aman untuk ditampilkan sebagai status umum UI."""

    def __init__(self, message: str, code: str = "unknown"):
        super().__init__(message)
        self.code = code


def _set_last_error(code: str) -> None:
    global _last_error_code
    with _status_lock:
        _last_error_code = code


def _error(message: str, code: str = "unknown") -> OAuthError:
    _set_last_error(code)
    return OAuthError(message, code)


def _load_tokens() -> dict:
    raw = secrets_store.get(_STORE_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_tokens(tokens: dict) -> bool:
    return secrets_store.set(_STORE_KEY, json.dumps(
        tokens, ensure_ascii=False, separators=(",", ":")))


def status() -> dict[str, bool | str]:
    """Status minimal OAuth yang tidak membocorkan token atau detail provider."""
    tokens = _load_tokens()
    access = str(tokens.get("access_token") or "")
    refresh = str(tokens.get("refresh_token") or "")
    try:
        expiring = time.time() >= float(tokens.get("expires_at", 0)) - _REFRESH_SKEW_S
    except (TypeError, ValueError):
        expiring = True
    with _status_lock:
        last_error = _last_error_code
    return {
        "connected": bool(access or refresh) and not (bool(access) and expiring and not refresh),
        "needs_reauth": bool(access) and expiring and not refresh,
        "token_refresh_due": bool(refresh and (not access or expiring)),
        "last_error_code": last_error,
    }


def connected() -> bool:
    return bool(status()["connected"])


def logout() -> None:
    secrets_store.delete(_STORE_KEY)
    _set_last_error("")
    _logger.info("oauth.logout", provider="anthropic_oauth")


def _post_token(payload: dict, *, use_json: bool) -> dict:
    import requests
    last_status = 0
    for endpoint in TOKEN_URLS:
        try:
            kwargs = {"json": payload} if use_json else {"data": payload}
            response = requests.post(endpoint, **kwargs, headers={
                "Content-Type": "application/json" if use_json else
                "application/x-www-form-urlencoded",
                "User-Agent": _TOKEN_UA}, timeout=20)
        except Exception:
            continue
        last_status = response.status_code
        if response.status_code == 200:
            return response.json()
    raise _error(f"token Anthropic ditolak (HTTP {last_status or 'network'})",
                 "provider_rejected" if last_status else "network")


def _exchange(code: str, verifier: str, redirect_uri: str) -> dict:
    data = _post_token({
        "grant_type": "authorization_code", "client_id": CLIENT_ID,
        "code": code, "redirect_uri": redirect_uri,
        "code_verifier": verifier,
    }, use_json=True)
    if not data.get("access_token"):
        raise _error("token exchange tanpa access_token", "provider_rejected")
    return data


def start_login(open_browser: bool = True, timeout_s: int = 300) -> dict:
    if not secrets_store.available():
        raise _error("backend penyimpanan terenkripsi tidak tersedia",
                     "provider_rejected")
    try:
        tokens = oauth_loopback.authorize(
            authorize_url=AUTHORIZE_URL, client_id=CLIENT_ID, scope=SCOPES,
            exchange=_exchange, ports=(0,), callback_path="/callback",
            timeout_s=timeout_s, open_browser=open_browser,
            extra_params={"code": "true"})
    except oauth_loopback.LoopbackOAuthError as exc:
        raise _error(str(exc), "provider_rejected") from exc
    stored = {
        "access_token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token", ""),
        "expires_at": time.time() + float(tokens.get("expires_in", 3600)),
        "scope": tokens.get("scope", SCOPES),
    }
    if not _save_tokens(stored):
        raise _error("token tidak dapat disimpan terenkripsi", "provider_rejected")
    _set_last_error("")
    _logger.info("oauth.connected", provider="anthropic_oauth")
    return {"provider": "anthropic_oauth", "connected": True}


def access_token() -> str:
    with _lock:
        tokens = _load_tokens()
        access = str(tokens.get("access_token") or "")
        try:
            fresh = time.time() < float(tokens.get("expires_at", 0)) \
                - _REFRESH_SKEW_S
        except (TypeError, ValueError):
            fresh = False
        if access and fresh:
            return access
        refresh = str(tokens.get("refresh_token") or "")
        if not refresh:
            raise _error("belum terhubung atau token kedaluwarsa; sign in ulang",
                         "reauth_required")
        data = _post_token({"grant_type": "refresh_token",
                            "refresh_token": refresh,
                            "client_id": CLIENT_ID}, use_json=False)
        if not data.get("access_token"):
            raise _error("refresh tanpa access_token; sign in ulang", "reauth_required")
        tokens["access_token"] = data["access_token"]
        tokens["refresh_token"] = data.get("refresh_token", refresh)
        tokens["expires_at"] = time.time() + float(data.get("expires_in", 3600))
        if not _save_tokens(tokens):
            raise _error("token refresh tidak dapat disimpan terenkripsi",
                     "provider_rejected")
        return str(tokens["access_token"])


def client_kwargs() -> dict:
    """Argumen SDK terverifikasi untuk bearer OAuth Claude Code."""
    return {
        "auth_token": access_token(),
        "default_headers": {
            "anthropic-beta": "claude-code-20250219,oauth-2025-04-20",
            "user-agent": "claude-code/2.1.126 (external, cli)",
            "x-app": "cli",
        },
    }
