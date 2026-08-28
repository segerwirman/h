"""Salted verifier for desktop-local communication-mode authorization.

Only serialized KDF parameters, salt, and verifier bytes are persisted through
``secrets_store``. Raw user input exists only in the caller and verification
frame and is never logged, audited, published, or copied into configuration.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import os
import threading
import time
from dataclasses import dataclass

from jarvis.core import secrets_store


_STORE_KEY = "jarvis/communication/passphrase_verifier"
_ALGORITHM = "pbkdf2_sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 32
_DKLEN = 32
_MIN_INPUT_CHARS = 8
_MAX_INPUT_CHARS = 1024
_MAX_FAILURES = 5
_FAILURE_WINDOW_S = 300.0
_LOCKOUT_S = 60.0


@dataclass(frozen=True)
class VerificationResult:
    ok: bool
    status: str
    retry_after_s: float = 0.0


class PassphraseVerifier:
    """Encrypted-store-backed verifier with bounded process-local failures."""

    def __init__(
        self,
        *,
        store=secrets_store,
        now_fn=time.monotonic,
        random_bytes=os.urandom,
        derive_fn=None,
        max_failures: int = _MAX_FAILURES,
        failure_window_s: float = _FAILURE_WINDOW_S,
        lockout_s: float = _LOCKOUT_S,
    ) -> None:
        self._store = store
        self._now_fn = now_fn
        self._random_bytes = random_bytes
        self._derive_fn = derive_fn or self._derive
        self._max_failures = max(1, int(max_failures))
        self._failure_window_s = self._positive_finite(
            failure_window_s,
            _FAILURE_WINDOW_S,
        )
        self._lockout_s = self._positive_finite(lockout_s, _LOCKOUT_S)
        self._lock = threading.RLock()
        self._failures: list[float] = []
        self._locked_until = 0.0

    @staticmethod
    def _positive_finite(value: float, default: float) -> float:
        parsed = float(value)
        return parsed if math.isfinite(parsed) and parsed > 0 else default

    @staticmethod
    def _derive(value: bytes, salt: bytes, iterations: int, dklen: int) -> bytes:
        return hashlib.pbkdf2_hmac(
            "sha256",
            value,
            salt,
            int(iterations),
            dklen=int(dklen),
        )

    @staticmethod
    def _valid_input(value: object) -> bool:
        return isinstance(value, str) and _MIN_INPUT_CHARS <= len(value) <= _MAX_INPUT_CHARS

    def configured(self) -> bool:
        return self._load_record() is not None

    def set_passphrase(self, value: str) -> bool:
        if not self._valid_input(value):
            return False
        salt = bytes(self._random_bytes(_SALT_BYTES))
        if len(salt) != _SALT_BYTES:
            return False
        derived = self._derive_fn(
            value.encode("utf-8"),
            salt,
            _ITERATIONS,
            _DKLEN,
        )
        if not isinstance(derived, bytes) or len(derived) != _DKLEN:
            return False
        record = json.dumps(
            {
                "algorithm": _ALGORITHM,
                "salt": base64.b64encode(salt).decode("ascii"),
                "iterations": _ITERATIONS,
                "dklen": _DKLEN,
                "verifier": base64.b64encode(derived).decode("ascii"),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        if not bool(self._store.set(_STORE_KEY, record)):
            return False
        with self._lock:
            self._failures.clear()
            self._locked_until = 0.0
        return True

    def verify(self, value: str) -> VerificationResult:
        now = float(self._now_fn())
        with self._lock:
            if now < self._locked_until:
                return VerificationResult(
                    False,
                    "locked",
                    max(0.0, self._locked_until - now),
                )
        record = self._load_record()
        if record is None:
            return VerificationResult(False, "not_configured")
        if not self._valid_input(value):
            return self._failed(now)
        derived = self._derive_fn(
            value.encode("utf-8"),
            record["salt"],
            record["iterations"],
            record["dklen"],
        )
        valid = (
            isinstance(derived, bytes)
            and len(derived) == record["dklen"]
            and hmac.compare_digest(derived, record["verifier"])
        )
        if valid:
            with self._lock:
                self._failures.clear()
                self._locked_until = 0.0
            return VerificationResult(True, "verified")
        return self._failed(now)

    def _failed(self, now: float) -> VerificationResult:
        with self._lock:
            cutoff = now - self._failure_window_s
            self._failures = [item for item in self._failures if item >= cutoff]
            self._failures.append(now)
            if len(self._failures) >= self._max_failures:
                self._failures.clear()
                self._locked_until = now + self._lockout_s
                return VerificationResult(False, "locked", self._lockout_s)
        return VerificationResult(False, "denied")

    def _load_record(self) -> dict | None:
        try:
            raw = self._store.get(_STORE_KEY)
            data = json.loads(raw) if raw else None
            if not isinstance(data, dict):
                return None
            if set(data) != {
                "algorithm", "salt", "iterations", "dklen", "verifier",
            }:
                return None
            if data["algorithm"] != _ALGORITHM:
                return None
            iterations = int(data["iterations"])
            dklen = int(data["dklen"])
            if iterations != _ITERATIONS or dklen != _DKLEN:
                return None
            salt = base64.b64decode(data["salt"], validate=True)
            verifier = base64.b64decode(data["verifier"], validate=True)
            if len(salt) != _SALT_BYTES or len(verifier) != dklen:
                return None
            return {
                "salt": salt,
                "iterations": iterations,
                "dklen": dklen,
                "verifier": verifier,
            }
        except (TypeError, ValueError, json.JSONDecodeError):
            return None
        except Exception:
            return None


VERIFIER = PassphraseVerifier()


__all__ = [
    "PassphraseVerifier",
    "VERIFIER",
    "VerificationResult",
]
