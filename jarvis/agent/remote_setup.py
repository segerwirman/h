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
        self._sweep_interval = interval   # Phase 24: dipakai close() join
        # S-14: sweeper TIDAK dijalankan di sini. Antrean yang belum pernah
        # dipakai tidak punya apa pun untuk disapu, tetapi threadnya dulu hidup
        # sampai proses berakhir. Suite membangun 21 queue dan menutup
        # sebagian, sehingga belasan thread bangun tiap <=0,5 detik hingga
        # akhir — muncul sebagai crash access violation di ujung suite (S-13)
        # dan sebagai test timing yang gagal acak.
        self._sweeper: threading.Thread | None = None

    def close(self) -> None:
        """Stop the autonomous sweeper dan join thread (bounded, Phase 24)."""
        self._stop.set()
        with self._lock:
            sweeper = self._sweeper
        if (sweeper is not None and sweeper.is_alive()
                and sweeper is not threading.current_thread()):
            sweeper.join(timeout=self._sweep_interval + 1.0)

    def _ensure_sweeper(self) -> None:
        """Nyalakan sweeper saat ada yang perlu kedaluwarsa. Dipanggil dengan
        ``self._lock`` sudah dipegang."""
        if self._stop.is_set():
            return
        if self._sweeper is not None and self._sweeper.is_alive():
            return
        self._sweeper = threading.Thread(
            target=self._sweep_loop, name="remote-setup-sweeper", daemon=True,
            kwargs={"interval": self._sweep_interval},
        )
        self._sweeper.start()

    def _sweep_loop(self, *, interval: float) -> None:
        while not self._stop.wait(interval):
            with self._lock:
                self._prune()
                if not self._items:
                    # Tidak ada lagi yang bisa kedaluwarsa. Berhenti; ``stage``
                    # berikutnya menyalakannya lagi.
                    self._sweeper = None
                    return

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
            self._ensure_sweeper()
        _logger.info("remote_setup.staged", provider=request.provider,
                     requester=request.requester, hash=request.hash_suffix)
        return request

    def get(self, request_id: str) -> SetupRequest | None:
        with self._lock:
            self._prune()
            staged = self._items.get(str(request_id))
            return staged.request if staged else None

    def approve_local(self, request_id: str) -> str:
        """Import a staged setup after LOCAL approval; one-shot, then cleaned.

        Returns a fixed status string (never raw content): ``imported``,
        ``not_pending``, ``expired``, ``decrypt_failed``, or ``import_failed``.
        """
        with self._lock:
            self._prune()
            staged = self._items.get(str(request_id))
            if staged is None:
                return "not_pending"
            if staged.request.status != "pending":
                return "expired" if staged.request.status == "expired" else "not_pending"
            staged.request.status = "importing"
            cipher = staged.cipher
            provider = staged.request.provider
        try:
            payload = _decrypt_staging(cipher)
        except Exception as exc:
            _logger.error("remote_setup.decrypt_failed", error=type(exc).__name__)
            with self._lock:
                self._items.pop(str(request_id), None)
            return "decrypt_failed"
        try:
            ok = bool(_import_to_secret_store(provider, payload))
        except Exception as exc:
            _logger.error("remote_setup.import_failed", error=type(exc).__name__)
            ok = False
        finally:
            del cipher
        with self._lock:
            self._items.pop(str(request_id), None)
        return "imported" if ok else "import_failed"

    def cancel(self, request_id: str) -> None:
        with self._lock:
            self._items.pop(str(request_id), None)

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [rid for rid, staged in self._items.items()
                   if now - staged.request.created_at >= self._ttl_s]
        for rid in expired:
            self._items.pop(rid, None)


_QUEUE: SetupQueue | None = None
_QUEUE_LOCK = threading.Lock()


def get_setup_queue() -> SetupQueue:
    """Process-local runtime-owned queue shared by ingress and window."""
    global _QUEUE
    with _QUEUE_LOCK:
        if _QUEUE is None:
            _QUEUE = SetupQueue()
        return _QUEUE


__all__ = ["SetupQueue", "SetupRequest", "validate_setup_payload", "attachment_allowed", "get_setup_queue"]
