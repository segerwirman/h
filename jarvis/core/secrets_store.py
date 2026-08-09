"""Penyimpanan secret berlapis MK50 (master spec §9.1-§9.2).

Prioritas backend:
1. keyring OS (Credential Locker / Keychain / SecretService)
2. Windows DPAPI, terikat akun Windows
3. file Fernet terenkripsi di ``~/.jarvis``

Tidak ada backend plaintext. API publik tetap ``get/set/delete`` sehingga
integrasi lama dapat dibungkus tanpa membuat registry credential baru.
"""
from __future__ import annotations

import base64
import json
import os
import stat
import threading
from pathlib import Path
from typing import Protocol

from jarvis.core import log

from jarvis.core import quiet
_logger = log.get("core.secrets_store")
_SERVICE = "jarvis-mk50"
_lock = threading.RLock()
_backend: "_Backend | None" = None
_initialized = False


class _Backend(Protocol):
    name: str
    label: str

    def get(self, key: str) -> str | None: ...
    def set(self, key: str, value: str) -> bool: ...
    def delete(self, key: str) -> bool: ...


def _jarvis_dir() -> Path:
    """Direktori store; fungsi terpisah agar permission dapat dites aman."""
    return Path.home() / ".jarvis"


def _strict_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(stat.S_IRWXU)  # 0700; ACL Windows tetap dijaga OS/DPAPI
    except OSError as exc:
        quiet.swallowed("core.secrets_store.strict_dir_failed", exc)
    _strict_windows_acl(path, directory=True)


def _strict_file(path: Path) -> None:
    try:
        path.chmod(stat.S_IRUSR | stat.S_IWUSR)  # 0600
    except OSError as exc:
        quiet.swallowed("core.secrets_store.strict_file_failed", exc)
    _strict_windows_acl(path, directory=False)


def _strict_windows_acl(path: Path, directory: bool) -> bool:
    """Cabut inheritance dan beri akses hanya ke user proses di Windows."""
    if os.name != "nt":
        return True
    try:
        import ntsecuritycon
        import win32api
        import win32security

        sid, _, _ = win32security.LookupAccountName(
            None, win32api.GetUserName())
        dacl = win32security.ACL()
        flags = 0
        if directory:
            flags = (win32security.OBJECT_INHERIT_ACE
                     | win32security.CONTAINER_INHERIT_ACE)
        dacl.AddAccessAllowedAceEx(
            win32security.ACL_REVISION, flags,
            ntsecuritycon.FILE_ALL_ACCESS, sid)
        descriptor = win32security.SECURITY_DESCRIPTOR()
        descriptor.SetSecurityDescriptorDacl(True, dacl, False)
        info = (win32security.DACL_SECURITY_INFORMATION
                | win32security.PROTECTED_DACL_SECURITY_INFORMATION)
        win32security.SetFileSecurity(str(path), info, descriptor)
        return True
    except Exception as exc:
        _logger.warning("secrets.permission_hardening_failed",
                        path=path.name, error=type(exc).__name__)
        return False


def permissions_strict(path: Path) -> bool:
    """Verifikasi permission lintas-platform tanpa membaca isi secret."""
    if os.name != "nt":
        return stat.S_IMODE(path.stat().st_mode) & 0o077 == 0
    try:
        import win32api
        import win32security

        expected, _, _ = win32security.LookupAccountName(
            None, win32api.GetUserName())
        descriptor = win32security.GetFileSecurity(
            str(path), win32security.DACL_SECURITY_INFORMATION)
        dacl = descriptor.GetSecurityDescriptorDacl()
        if dacl is None or dacl.GetAceCount() < 1:
            return False
        for index in range(dacl.GetAceCount()):
            ace = dacl.GetAce(index)
            if ace[2] != expected:
                return False
        return True
    except Exception:
        return False


def _atomic_write(path: Path, payload: bytes) -> None:
    _strict_dir(path.parent)
    tmp = path.with_name(path.name + ".tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    if hasattr(os, "O_BINARY"):
        flags |= os.O_BINARY
    fd = os.open(str(tmp), flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError as exc:
            quiet.swallowed("core.secrets_store.atomic_write_failed", exc)
        raise
    _strict_file(tmp)
    os.replace(tmp, path)
    _strict_file(path)


class _KeyringBackend:
    name = "keyring"
    label = "Keyring OS"

    def __init__(self, module):
        self._keyring = module

    def get(self, key: str) -> str | None:
        return self._keyring.get_password(_SERVICE, key)

    def set(self, key: str, value: str) -> bool:
        self._keyring.set_password(_SERVICE, key, value)
        return True

    def delete(self, key: str) -> bool:
        try:
            self._keyring.delete_password(_SERVICE, key)
        except Exception as exc:  # keyring memakai exception untuk key absen
            if "not found" not in str(exc).lower():
                raise
        return True


class _EncryptedFileBackend:
    """Dictionary JSON yang seluruh blob-nya dienkripsi sebelum ditulis."""

    name = "encrypted"
    label = "File terenkripsi"
    _last_load_ok = True

    @property
    def _data_path(self) -> Path:
        return _jarvis_dir() / "secrets.dat"

    def _encrypt(self, raw: bytes) -> bytes:
        raise NotImplementedError

    def _decrypt(self, raw: bytes) -> bytes:
        raise NotImplementedError

    def _load(self) -> dict[str, str]:
        try:
            raw = self._data_path.read_bytes()
            if not raw:
                self._last_load_ok = True
                return {}
            data = json.loads(self._decrypt(raw).decode("utf-8"))
            self._last_load_ok = True
            return {str(k): str(v) for k, v in data.items()} \
                if isinstance(data, dict) else {}
        except FileNotFoundError:
            self._last_load_ok = True
            return {}
        except Exception as exc:
            self._last_load_ok = False
            _logger.error("secrets.encrypted_read_failed",
                          backend=self.name, error=type(exc).__name__)
            return {}

    def _save(self, data: dict[str, str]) -> bool:
        raw = json.dumps(data, ensure_ascii=False,
                         separators=(",", ":")).encode("utf-8")
        _atomic_write(self._data_path, self._encrypt(raw))
        return True

    def get(self, key: str) -> str | None:
        return self._load().get(key)

    def set(self, key: str, value: str) -> bool:
        data = self._load()
        if not self._last_load_ok:
            return False
        data[key] = value
        return self._save(data)

    def delete(self, key: str) -> bool:
        data = self._load()
        if not self._last_load_ok:
            return False
        if key not in data:
            return True
        data.pop(key, None)
        return self._save(data)


class _DPAPIBackend(_EncryptedFileBackend):
    name = "dpapi"
    label = "DPAPI"

    def __init__(self, module):
        self._win32crypt = module

    def _encrypt(self, raw: bytes) -> bytes:
        protected = self._win32crypt.CryptProtectData(
            raw, "Jarvis MK50 secrets", None, None, None, 0)
        # Beberapa binding lama mengembalikan tuple; pywin32 modern bytes.
        if isinstance(protected, tuple):
            protected = protected[-1]
        return b"dpapi:" + base64.b64encode(bytes(protected))

    def _decrypt(self, raw: bytes) -> bytes:
        payload = raw.removeprefix(b"dpapi:")
        if raw.startswith(b"fernet:"):
            raise ValueError("store Fernet tidak dapat dibaca DPAPI")
        result = self._win32crypt.CryptUnprotectData(
            base64.b64decode(payload), None, None, None, 0)
        return bytes(result[-1] if isinstance(result, tuple) else result)


class _FernetBackend(_EncryptedFileBackend):
    name = "fernet"
    label = "File terenkripsi"

    @property
    def _key_path(self) -> Path:
        return _jarvis_dir() / ".keyfile"

    def _fernet(self):
        from cryptography.fernet import Fernet

        try:
            key = self._key_path.read_bytes().strip()
        except FileNotFoundError:
            key = Fernet.generate_key()
            _atomic_write(self._key_path, key + b"\n")
        _strict_file(self._key_path)
        return Fernet(key)

    def _encrypt(self, raw: bytes) -> bytes:
        return b"fernet:" + self._fernet().encrypt(raw)

    def _decrypt(self, raw: bytes) -> bytes:
        if raw.startswith(b"dpapi:"):
            raise ValueError("store DPAPI tidak dapat dibaca Fernet")
        return self._fernet().decrypt(raw.removeprefix(b"fernet:"))


def _usable_keyring():
    try:
        import keyring
        backend = keyring.get_keyring()
        if float(getattr(backend, "priority", 0) or 0) <= 0:
            return None
        # Membaca sentinel tidak mengubah state, tetapi mendeteksi backend
        # headless/fail sebelum ia dipilih sebagai penyimpan aktif.
        keyring.get_password(_SERVICE, "__backend_probe__")
        return keyring
    except Exception:
        return None


def _choose_fallback() -> _Backend | None:
    if os.name == "nt":
        try:
            import win32crypt
            return _DPAPIBackend(win32crypt)
        except Exception as exc:
            quiet.swallowed("core.secrets_store.choose_fallback_failed", exc)
    try:
        from cryptography.fernet import Fernet  # noqa: F401
        return _FernetBackend()
    except Exception:
        return None


def _choose_backend() -> _Backend | None:
    keyring_module = _usable_keyring()
    if keyring_module is not None:
        return _KeyringBackend(keyring_module)
    return _choose_fallback()


def _degrade_from_keyring() -> _Backend | None:
    global _backend
    if _backend is None or _backend.name != "keyring":
        return _backend
    fallback = _choose_fallback()
    _backend = fallback
    _logger.warning("secrets.backend_fallback",
                    backend=fallback.label if fallback else "Tidak tersedia")
    return fallback


def initialize(force: bool = False) -> str:
    """Deteksi sekali dan log tepat satu baris backend aktif."""
    global _backend, _initialized
    with _lock:
        if force or not _initialized:
            _backend = _choose_backend()
            _initialized = True
            _logger.info("secrets.backend_active",
                         backend=backend_label())
        return backend_name()


def _active() -> _Backend | None:
    if not _initialized:
        initialize()
    return _backend


def backend_name() -> str:
    backend = _backend if _initialized else _active()
    return backend.name if backend is not None else "unavailable"


def backend_label() -> str:
    backend = _backend if _initialized else _active()
    return backend.label if backend is not None else "Tidak tersedia"


def get(key: str) -> str | None:
    # Environment tetap boleh menjadi sumber ephemeral, tetapi tidak pernah
    # dipersistkan atau disalin ke config.
    env_val = os.environ.get(key)
    if env_val:
        return env_val
    backend = _active()
    if backend is None:
        return None
    try:
        return backend.get(key)
    except Exception as exc:
        _logger.warning("secrets.read_failed", backend=backend.name,
                        key=key, error=type(exc).__name__)
        with _lock:
            fallback = _degrade_from_keyring()
            if fallback is not None and fallback is not backend:
                try:
                    return fallback.get(key)
                except Exception as exc:
                    quiet.swallowed("core.secrets_store.get_failed", exc)
        return None


def set(key: str, value: str) -> bool:
    backend = _active()
    if backend is None:
        _logger.error("secrets.no_encrypted_backend", key=key)
        return False
    try:
        return bool(backend.set(key, str(value)))
    except Exception as exc:
        _logger.error("secrets.write_failed", backend=backend.name,
                      key=key, error=type(exc).__name__)
        with _lock:
            fallback = _degrade_from_keyring()
            if fallback is not None and fallback is not backend:
                try:
                    return bool(fallback.set(key, str(value)))
                except Exception as exc:
                    quiet.swallowed("core.secrets_store.set_failed", exc)
        return False


def delete(key: str) -> bool:
    backend = _active()
    if backend is None:
        return False
    try:
        return bool(backend.delete(key))
    except Exception as exc:
        _logger.warning("secrets.delete_failed", backend=backend.name,
                        key=key, error=type(exc).__name__)
        with _lock:
            fallback = _degrade_from_keyring()
            if fallback is not None and fallback is not backend:
                try:
                    return bool(fallback.delete(key))
                except Exception as exc:
                    quiet.swallowed("core.secrets_store.delete_failed", exc)
        return False


def available() -> bool:
    return _active() is not None
