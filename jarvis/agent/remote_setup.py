"""Fase 15S: secure remote setup queue (metadata-only, local-approval-gated).

Remote (Telegram) may upload an allowlisted provider setup artifact. The raw
secret bytes never enter logs, audit, LLM context, or the SetupRequest metadata.
Only a local desktop approval may import a validated payload into the secret
store; staging is encrypted at rest and lifecycle-cleaned.
"""
from __future__ import annotations

import hashlib
import json
import threading
import time
import uuid
from dataclasses import dataclass, field

from jarvis.core import log

_logger = log.get("agent.remote_setup")

_DEFAULT_TTL_S = 600.0
_MAX_BYTES = 512 * 1024
_ALLOWED_EXT = frozenset({".json"})
_SUPPORTED_PROVIDERS = frozenset({"google_oauth_client"})


def attachment_allowed(filename: str, size: int) -> tuple[bool, str]:
    """Gate a remote attachment by extension and size before any staging."""
    name = str(filename or "").strip().lower()
    dot = name.rfind(".")
    ext = name[dot:] if dot >= 0 else ""
    if ext not in _ALLOWED_EXT:
        return False, "setup_attachment_type_rejected"
    if int(size) <= 0 or int(size) > _MAX_BYTES:
        return False, "setup_attachment_size_rejected"
    return True, ""


def validate_setup_payload(provider: str, payload: bytes) -> tuple[bool, str, str]:
    """Return (ok, kind, reason). Reason/kind never contain secret material."""
    if str(provider) not in _SUPPORTED_PROVIDERS:
        return False, "", "setup_provider_unsupported"
    if str(provider) == "google_oauth_client":
        return _validate_google_oauth_client(payload)
    return False, "", "setup_provider_unsupported"


def _validate_google_oauth_client(payload: bytes) -> tuple[bool, str, str]:
    try:
        data = json.loads(payload.decode("utf-8"))
    except Exception:
        return False, "", "setup_payload_malformed"
    if not isinstance(data, dict):
        return False, "", "setup_payload_malformed"
    if "web" in data:
        return False, "", "setup_payload_not_desktop_client"
    if data.get("type") == "service_account":
        return False, "", "setup_payload_service_account_rejected"
    installed = data.get("installed")
    if not isinstance(installed, dict):
        return False, "", "setup_payload_not_desktop_client"
    required = ("client_id", "client_secret", "token_uri")
    if any(not isinstance(installed.get(key), str) or not installed[key].strip()
           for key in required):
        return False, "", "setup_payload_incomplete_oauth_client"
    return True, "google_oauth_client", ""


@dataclass
class SetupRequest:
    """Immutable-style metadata only; secret bytes are never stored here."""
    id: str
    provider: str
    requester: str
    hash_suffix: str
    status: str
    created_at: float


@dataclass
class _Staged:
    request: SetupRequest
    cipher: bytes = field(repr=False)


def _encrypt_staging(raw: bytes) -> bytes:
    """Encrypt staging bytes at rest via the existing secret backend seam."""
    from cryptography.fernet import Fernet

    key = _staging_key()
    return b"setupenc:" + Fernet(key).encrypt(raw)


def _decrypt_staging(cipher: bytes) -> bytes:
    from cryptography.fernet import Fernet

    key = _staging_key()
    return Fernet(key).decrypt(cipher.removeprefix(b"setupenc:"))


_KEY_LOCK = threading.Lock()


def _staging_key() -> bytes:
    from cryptography.fernet import Fernet
    from jarvis.core import secrets_store

    with _KEY_LOCK:
        existing = secrets_store.get("jarvis/remote_setup/staging_key")
        if existing:
            return existing.encode("ascii")
        key = Fernet.generate_key()
        secrets_store.set("jarvis/remote_setup/staging_key", key.decode("ascii"))
        return key


def _import_to_secret_store(provider: str, payload: bytes) -> bool:
    """Import a validated payload into the encrypted secret store, local only."""
    if provider == "google_oauth_client":
        try:
            data = json.loads(payload.decode("utf-8"))
            installed = data.get("installed") if isinstance(data, dict) else None
            if not isinstance(installed, dict):
                return False
            client_id = str(installed.get("client_id", "")).strip()
            client_secret = str(installed.get("client_secret", "")).strip()
        except Exception:
            return False
        if not client_id or not client_secret:
            return False
        from jarvis.integrations import google_auth
        return bool(google_auth.save_client(client_id, client_secret))
    return False


class SetupQueue:
    def __init__(self, *, ttl_s: float = _DEFAULT_TTL_S):
        self._ttl_s = max(0.1, float(ttl_s))
        self._items: dict[str, _Staged] = {}
        self._lock = threading.RLock()
        self._stop = threading.Event()
        interval = max(0.05, min(1.0, self._ttl_s / 2))
        self._sweeper = threading.Thread(
            target=self._sweep_loop, name="remote-setup-sweeper", daemon=True,
            kwargs={"interval": interval},
        )
        self._sweeper.start()

    def close(self) -> None:
        """Stop the autonomous sweeper; staging cleanup stops too."""
        self._stop.set()

    def _sweep_loop(self, *, interval: float) -> None:
        while not self._stop.wait(interval):
            with self._lock:
                self._prune()

    def stage(self, *, provider: str, requester: str, filename: str,
              payload: bytes) -> SetupRequest:
        allowed, reason = attachment_allowed(filename, len(payload))
        if not allowed:
            raise ValueError(reason)
        ok, _kind, reason = validate_setup_payload(provider, payload)
        if not ok:
            raise ValueError(reason)
        digest = hashlib.sha256(payload).hexdigest()
        request = SetupRequest(
            id=uuid.uuid4().hex,
            provider=str(provider),
            requester=str(requester),
            hash_suffix=digest[:12],
            status="pending",
            created_at=time.monotonic(),
        )
        cipher = _encrypt_staging(payload)
        with self._lock:
            self._prune()
            self._items[request.id] = _Staged(request=request, cipher=cipher)
        _logger.info("remote_setup.staged", provider=request.provider,
                     requester=request.requester, hash=request.hash_suffix)
        return request

    def get(self, request_id: str) -> SetupRequest | None:
        with self._lock:
            self._prune()
            staged = self._items.get(str(request_id))
            return staged.request if staged else None

    def approve_local(self, request_id: str) -> bool:
        """Import a staged setup after LOCAL approval; one-shot, then cleaned."""
        with self._lock:
            self._prune()
            staged = self._items.get(str(request_id))
            if staged is None or staged.request.status != "pending":
                return False
            staged.request.status = "importing"
            cipher = staged.cipher
            provider = staged.request.provider
        try:
            payload = _decrypt_staging(cipher)
            ok = bool(_import_to_secret_store(provider, payload))
        except Exception as exc:
            _logger.error("remote_setup.import_failed", error=type(exc).__name__)
            ok = False
        finally:
            del cipher
        with self._lock:
            self._items.pop(str(request_id), None)
        return ok

    def cancel(self, request_id: str) -> None:
        with self._lock:
            self._items.pop(str(request_id), None)

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [rid for rid, staged in self._items.items()
                   if now - staged.request.created_at >= self._ttl_s]
        for rid in expired:
            self._items.pop(rid, None)


__all__ = ["SetupQueue", "SetupRequest", "validate_setup_payload", "attachment_allowed"]
