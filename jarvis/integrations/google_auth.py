"""Satu OAuth Google Desktop untuk Calendar, YouTube, Gmail, dan Drive.

Client credential dan token hanya berada di ``secrets_store``. Config YAML
menyimpan metadata/toggle API yang diminta, bukan material OAuth. Scope yang
benar-benar diberikan disimpan bersama token dan menjadi gate runtime.
"""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone

from jarvis.core import config, config_write, log, secrets_store
from jarvis.integrations import oauth_loopback

_logger = log.get("integrations.google_auth")
_lock = threading.RLock()

AUTHORIZE_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
CLIENT_ID_KEY = "jarvis/google/client_id"
CLIENT_SECRET_KEY = "jarvis/google/client_secret"
TOKEN_KEY = "jarvis/google/oauth_token"

SCOPES = {
    "calendar": {
        "read": "https://www.googleapis.com/auth/calendar.readonly",
        "write": "https://www.googleapis.com/auth/calendar.events",
    },
    "youtube": {
        "read": "https://www.googleapis.com/auth/youtube.readonly",
        # comments.insert secara resmi mensyaratkan youtube.force-ssl;
        # scope ini juga dapat membaca akun dan live chat.
        "write": "https://www.googleapis.com/auth/youtube.force-ssl",
    },
    "gmail": {
        "read": "https://www.googleapis.com/auth/gmail.readonly",
        "write": "https://www.googleapis.com/auth/gmail.send",
        "modify": "https://www.googleapis.com/auth/gmail.modify",
    },
    "drive": {
        "read": "https://www.googleapis.com/auth/drive.readonly",
        "write": "https://www.googleapis.com/auth/drive.file",
    },
}


class GoogleAuthError(RuntimeError):
    pass


def _load_token() -> dict:
    raw = secrets_store.get(TOKEN_KEY)
    if not raw:
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_token(data: dict) -> bool:
    return secrets_store.set(TOKEN_KEY, json.dumps(
        data, ensure_ascii=False, separators=(",", ":")))


def client_id() -> str:
    return secrets_store.get(CLIENT_ID_KEY) or ""


def client_secret() -> str:
    return secrets_store.get(CLIENT_SECRET_KEY) or ""


def client_configured() -> bool:
    return bool(client_id() and client_secret())


def save_client(client: str, secret: str) -> bool:
    """Simpan OAuth client hanya bila kedua nilai ada dan readback sukses."""
    client, secret = str(client or "").strip(), str(secret or "").strip()
    if not client or not secret:
        return False
    ok_client = secrets_store.set(CLIENT_ID_KEY, client)
    ok_secret = secrets_store.set(CLIENT_SECRET_KEY, secret)
    return bool(ok_client and ok_secret
                and secrets_store.get(CLIENT_ID_KEY) == client
                and secrets_store.get(CLIENT_SECRET_KEY) == secret)


def provider_enabled() -> bool:
    return bool(config.get("providers.google.enabled", False))


def api_enabled(api: str) -> bool:
    return provider_enabled() and bool(config.get(
        f"providers.google.apis.{api}.enabled", False))


def write_enabled(api: str) -> bool:
    return api_enabled(api) and bool(config.get(
        f"providers.google.apis.{api}.write", False))


def requested_scopes() -> list[str]:
    """Scope gabungan untuk seluruh API yang enabled pada consent berikut."""
    out: list[str] = []
    for api in ("calendar", "youtube", "gmail", "drive"):
        if not bool(config.get(f"providers.google.apis.{api}.enabled", False)):
            continue
        spec = SCOPES[api]
        if api in ("calendar", "youtube") and bool(config.get(
                f"providers.google.apis.{api}.write", False)):
            out.append(spec["write"])
        else:
            out.append(spec["read"])
            if api == "gmail" and bool(config.get(
                    "providers.google.apis.gmail.write", False)):
                out.append(spec["write"])
    return list(dict.fromkeys(out))


def token_scopes() -> set[str]:
    data = _load_token()
    raw = data.get("scopes", data.get("scope", []))
    if isinstance(raw, str):
        values = raw.replace(",", " ").split()
    elif isinstance(raw, (list, tuple, set)):
        values = raw
    else:
        values = []
    return {str(value).strip() for value in values if str(value).strip()}


def has_scope(scope: str) -> bool:
    return bool(scope) and scope in token_scopes()


def has_read_scope(api: str) -> bool:
    if api not in SCOPES or not api_enabled(api):
        return False
    granted = token_scopes()
    spec = SCOPES[api]
    if api in ("calendar", "youtube"):
        return bool(granted.intersection({spec["read"], spec["write"]}))
    if api == "gmail":
        return bool(granted.intersection(
            {spec["read"], spec["modify"]}))
    return spec["read"] in granted


def has_write_scope(api: str) -> bool:
    return bool(api in SCOPES and write_enabled(api)
                and SCOPES[api]["write"] in token_scopes())


def connected() -> bool:
    data = _load_token()
    return bool(provider_enabled()
                and (data.get("token") or data.get("access_token")
                     or data.get("refresh_token")))


def status() -> dict:
    """Status aman untuk UI/log; tidak pernah mengembalikan credential."""
    return {
        "connected": connected(),
        "client_configured": client_configured(),
        "backend": secrets_store.backend_label(),
        "scopes": sorted(token_scopes()),
        "apis": {api: {
            "enabled": api_enabled(api),
            "read": has_read_scope(api),
            "write": has_write_scope(api),
        } for api in SCOPES},
    }


def _exchange(code: str, verifier: str, redirect_uri: str) -> dict:
    import requests

    try:
        response = requests.post(TOKEN_URL, data={
            "client_id": client_id(),
            "client_secret": client_secret(),
            "code": code,
            "code_verifier": verifier,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20)
    except Exception as exc:
        raise GoogleAuthError(
            f"token exchange Google gagal: {type(exc).__name__}") from exc
    if response.status_code != 200:
        raise GoogleAuthError(
            f"token Google ditolak (HTTP {response.status_code})")
    try:
        data = response.json()
    except Exception as exc:
        raise GoogleAuthError("respons token Google bukan JSON") from exc
    if not data.get("access_token"):
        raise GoogleAuthError("respons Google tidak membawa access_token")
    return data


def start_login(open_browser: bool = True, timeout_s: int = 300) -> dict:
    if not secrets_store.available():
        raise GoogleAuthError("backend penyimpanan terenkripsi tidak tersedia")
    if not client_configured():
        raise GoogleAuthError(
            "OAuth client ID/client secret Google belum disimpan di Settings")
    scopes = requested_scopes()
    if not scopes:
        raise GoogleAuthError(
            "aktifkan minimal satu API Google lalu simpan Settings")
    try:
        tokens = oauth_loopback.authorize(
            authorize_url=AUTHORIZE_URL,
            client_id=client_id(),
            scope=" ".join(scopes),
            exchange=_exchange,
            ports=(0,),
            callback_path="/",
            redirect_host="127.0.0.1",
            timeout_s=timeout_s,
            open_browser=open_browser,
            extra_params={"access_type": "offline", "prompt": "consent"},
        )
    except oauth_loopback.LoopbackOAuthError as exc:
        raise GoogleAuthError(str(exc)) from exc

    previous = _load_token()
    granted_raw = tokens.get("scope") or " ".join(scopes)
    granted = (granted_raw.split() if isinstance(granted_raw, str)
               else list(granted_raw or []))
    stored = {
        "token": tokens["access_token"],
        "refresh_token": tokens.get("refresh_token")
        or previous.get("refresh_token", ""),
        "token_uri": TOKEN_URL,
        "scopes": list(dict.fromkeys(str(s) for s in granted if s)),
        "expiry": datetime.fromtimestamp(
            time.time() + float(tokens.get("expires_in", 3600)),
            timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    if not _save_token(stored):
        raise GoogleAuthError("token Google tidak dapat disimpan terenkripsi")
    if not config_write.set_scalar("providers.google.enabled", True):
        secrets_store.delete(TOKEN_KEY)
        raise GoogleAuthError("metadata provider Google gagal disimpan")
    refresh_registry()
    _logger.info("google.oauth_connected", scopes=len(stored["scopes"]))
    return {"provider": "google", "connected": True,
            "scopes": stored["scopes"]}


def logout() -> bool:
    deleted = secrets_store.delete(TOKEN_KEY)
    disabled = config_write.set_scalar("providers.google.enabled", False)
    refresh_registry()
    _logger.info("google.oauth_logout")
    return bool(deleted and disabled)


def credentials(required_scopes: list[str] | tuple[str, ...] | None = None):
    """Credential valid/refresh otomatis, atau raise pesan aman dan jelas."""
    with _lock:
        return _credentials_unlocked(required_scopes)


def _credentials_unlocked(
        required_scopes: list[str] | tuple[str, ...] | None = None):
    required = [str(s) for s in (required_scopes or []) if str(s)]
    if not connected():
        raise GoogleAuthError("akun Google belum terhubung di Settings")
    missing = sorted(set(required) - token_scopes())
    if missing:
        raise GoogleAuthError(
            "scope Google belum diberikan; aktifkan API lalu Connect ulang")
    info = dict(_load_token())
    if info.get("access_token") and not info.get("token"):
        info["token"] = info.pop("access_token")
    if isinstance(info.get("expiry"), (int, float)):
        info["expiry"] = datetime.fromtimestamp(
            float(info["expiry"]), timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ")
    info.update({"client_id": client_id(),
                 "client_secret": client_secret(),
                 "token_uri": TOKEN_URL})
    try:
        from google.auth.transport.requests import Request
        from google.oauth2.credentials import Credentials
        creds = Credentials.from_authorized_user_info(
            info, scopes=sorted(token_scopes()))
        if creds.expired:
            if not creds.refresh_token:
                raise GoogleAuthError(
                    "token Google kedaluwarsa tanpa refresh token; Connect ulang")
            creds.refresh(Request())
            refreshed = json.loads(creds.to_json(
                strip=["client_id", "client_secret"]))
            refreshed["scopes"] = sorted(token_scopes())
            if not _save_token(refreshed):
                raise GoogleAuthError(
                    "refresh berhasil tetapi token baru gagal disimpan")
        return creds
    except GoogleAuthError:
        raise
    except ImportError as exc:
        raise GoogleAuthError(
            "library Google belum terpasang; instal requirements.txt") from exc
    except Exception as exc:
        raise GoogleAuthError(
            f"autentikasi Google gagal: {type(exc).__name__}") from exc


def access_token(required_scopes: list[str] | None = None) -> str:
    creds = credentials(required_scopes)
    if not getattr(creds, "token", None):
        raise GoogleAuthError("credential Google tidak membawa access token")
    return str(creds.token)


def refresh_registry() -> None:
    """Terapkan scope/toggle ke schema tool sesi baru tanpa registry kedua."""
    try:
        from jarvis.agent import registry
        registry.all_tools(refresh=True)
    except Exception as exc:
        _logger.debug("google.registry_refresh_failed",
                      error=type(exc).__name__)
    try:
        from jarvis.integrations import voice_native_tools
        voice_native_tools.sync_google_declarations()
    except Exception:
        pass
