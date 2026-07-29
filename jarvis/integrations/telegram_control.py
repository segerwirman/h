"""Konfigurasi aman dan lifecycle Telegram Control native (MK50 §11).

Nilai token dan allowlist hanya disimpan lewat ``secrets_store``.  YAML
menyimpan metadata non-rahasia berupa master toggle; adapter tidak pernah
menggunakan kredensial plaintext sebagai sumber runtime.
"""
from __future__ import annotations

import asyncio
import os
import re
import stat
from dataclasses import dataclass

from jarvis.core import config, config_write, log, release_controls, secrets_store

_logger = log.get("integrations.telegram_control")
TOKEN_SECRET = "jarvis/telegram/bot_token"
ALLOWED_IDS_SECRET = "jarvis/telegram/allowed_ids"
_LEGACY_TOKEN_SECRET = "TG_BOT_TOKEN"


@dataclass(frozen=True)
class SaveResult:
    ok: bool
    message: str


@dataclass(frozen=True)
class ConnectionResult:
    ok: bool
    message: str
    bot_name: str = ""


def token() -> str:
    """Ambil token dari backend terenkripsi, tanpa fallback plaintext."""
    try:
        return (secrets_store.get(TOKEN_SECRET) or "").strip()
    except Exception:  # noqa: BLE001 - backend gagal berarti nonaktif jujur
        return ""


def _parse_ids(raw: str, *, strict: bool = False) -> tuple[int, ...]:
    parts = [part.strip() for part in re.split(r"[,;\s]+", raw.strip())
             if part.strip()]
    if not parts:
        return ()
    if strict and any(not part.isdecimal() or int(part) <= 0
                      for part in parts):
        raise ValueError("Allowed User IDs harus berupa angka positif, dipisah koma.")
    values = [int(part) for part in parts
              if part.isdecimal() and int(part) > 0]
    return tuple(dict.fromkeys(values))


def allowed_ids() -> tuple[int, ...]:
    """Allowlist Telegram; entry invalid di store tidak pernah diberi akses."""
    try:
        raw = secrets_store.get(ALLOWED_IDS_SECRET) or ""
    except Exception:  # noqa: BLE001
        return ()
    return _parse_ids(raw)


def master_enabled() -> bool:
    return bool(config.get("integrations.telegram.enabled", False))


def credentials_ready() -> bool:
    return bool(token()) and bool(allowed_ids())


def enabled() -> bool:
    """Bot hanya boleh start bila toggle, token, dan allowlist valid."""
    return master_enabled() and credentials_ready()


def backend_label() -> str:
    try:
        return str(secrets_store.backend_label() or "Tidak tersedia")
    except Exception:  # noqa: BLE001
        return "Tidak tersedia"


def save_credentials(token_value: str = "", allowed_raw: str = "") -> SaveResult:
    """Simpan input baru secara terenkripsi; input kosong mempertahankan nilai."""
    new_token = token_value.strip()
    current_token = token()
    current_ids = allowed_ids()
    try:
        new_ids = _parse_ids(allowed_raw, strict=True) if allowed_raw.strip() \
            else current_ids
    except ValueError as exc:
        return SaveResult(False, str(exc))

    final_token = new_token or current_token
    if not final_token:
        return SaveResult(False, "Bot token belum diisi.")
    if not new_ids:
        return SaveResult(False, "Minimal satu Allowed User ID diperlukan.")

    old_token = current_token
    old_ids_raw = ",".join(str(item) for item in current_ids)
    ids_value = ",".join(str(item) for item in new_ids)
    try:
        if not secrets_store.set(TOKEN_SECRET, final_token):
            return SaveResult(False, "Bot token gagal disimpan di penyimpanan aman.")
        if not secrets_store.set(ALLOWED_IDS_SECRET, ids_value):
            _restore_secret(TOKEN_SECRET, old_token)
            return SaveResult(False, "Allowed User IDs gagal disimpan di penyimpanan aman.")
        if token() != final_token or allowed_ids() != new_ids:
            _restore_secret(TOKEN_SECRET, old_token)
            _restore_secret(ALLOWED_IDS_SECRET, old_ids_raw)
            return SaveResult(False, "Verifikasi penyimpanan aman gagal.")
    except Exception:  # noqa: BLE001
        _restore_secret(TOKEN_SECRET, old_token)
        _restore_secret(ALLOWED_IDS_SECRET, old_ids_raw)
        return SaveResult(False, "Backend penyimpanan aman tidak tersedia.")
    return SaveResult(True, "Kredensial Telegram tersimpan aman.")


def _restore_secret(key: str, old_value: str) -> None:
    try:
        if old_value:
            secrets_store.set(key, old_value)
        else:
            secrets_store.delete(key)
    except Exception:  # noqa: BLE001
        pass


def set_enabled(value: bool) -> SaveResult:
    if value and not credentials_ready():
        return SaveResult(False, "Isi bot token dan minimal satu Allowed User ID dahulu.")
    if value and not release_controls.current().get("gateway", False):
        # The Telegram toggle is already an explicit, credentialed opt-in.
        # Keep the formal rollout gate synchronized so Settings cannot report
        # "aktif" while boot silently refuses to start the service.
        if not config_write.set_scalar("release_controls.gateway", True):
            return SaveResult(
                False, "Gateway Telegram gagal diaktifkan di release controls."
            )
    if not config_write.set_scalar("integrations.telegram.enabled", bool(value)):
        return SaveResult(False, "Master toggle gagal disimpan.")
    return SaveResult(True, "Telegram Control aktif." if value
                      else "Telegram Control nonaktif.")


def clear_credentials() -> SaveResult:
    """Matikan service sebelum menghapus kedua secret Telegram."""
    toggle_result = set_enabled(False)
    try:
        # Stop langsung sebelum secret dihapus. Bahkan bila penulisan toggle
        # gagal, bot lama tidak boleh terus berjalan dengan token yang sudah
        # diminta user untuk dibuang.
        from jarvis.agent.adapters.telegram import TelegramService
        TelegramService.get().stop()
        ok_token = secrets_store.delete(TOKEN_SECRET)
        ok_ids = secrets_store.delete(ALLOWED_IDS_SECRET)
    except Exception:  # noqa: BLE001
        return SaveResult(False, "Kredensial Telegram gagal dihapus dari backend aman.")
    if not (ok_token and ok_ids):
        return SaveResult(False, "Sebagian kredensial Telegram gagal dihapus.")
    if not toggle_result.ok:
        return SaveResult(
            False,
            "Kredensial dihapus dan bot dihentikan, tetapi master toggle gagal disimpan.",
        )
    return SaveResult(True, "Kredensial Telegram dihapus.")


def migrate_legacy() -> bool:
    """Migrasi satu kali dari konfigurasi lama ke store terenkripsi.

    Sumber lama hanya dibaca untuk migrasi kompatibilitas. Setelah verifikasi,
    adapter tetap membaca dua key namespaced di atas saja.
    """
    if credentials_ready():
        return False
    legacy_token = ""
    try:
        legacy_token = secrets_store.get(_LEGACY_TOKEN_SECRET) or ""
    except Exception:  # noqa: BLE001
        pass
    legacy_token = legacy_token or os.environ.get("TG_BOT_TOKEN", "")
    legacy_ids = (os.environ.get("TG_ALLOWED_IDS", "") or
                  str(config.get("agent.telegram.allowed_ids", "") or ""))
    if not legacy_token or not legacy_ids:
        return False
    result = save_credentials(legacy_token, legacy_ids)
    if not result.ok:
        _logger.warning("telegram.legacy_migration_failed")
        return False
    try:
        secrets_store.delete(_LEGACY_TOKEN_SECRET)
    except Exception:  # noqa: BLE001
        pass
    _scrub_legacy_env_file()
    for key in ("TG_BOT_TOKEN", "TG_ALLOWED_IDS", "TG_NOTIFY_CHAT_ID"):
        os.environ.pop(key, None)
    set_enabled(True)
    _logger.info("telegram.legacy_credentials_migrated")
    return True


def _scrub_legacy_env_file() -> None:
    """Hapus hanya tiga field Telegram lama setelah encrypted readback."""
    path = config.base_dir() / ".env"
    try:
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (FileNotFoundError, OSError):
        return
    pattern = re.compile(
        r"^\s*(?:TG_BOT_TOKEN|TG_ALLOWED_IDS|TG_NOTIFY_CHAT_ID)\s*=")
    retained = [line for line in lines if not pattern.match(line)]
    if retained == lines:
        return
    tmp = path.with_name(path.name + ".telegram-migration.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(tmp), flags, stat.S_IRUSR | stat.S_IWUSR)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.writelines(retained)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
    except Exception:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        _logger.warning("telegram.legacy_env_scrub_failed")


def status() -> dict[str, object]:
    running = False
    try:
        from jarvis.agent.adapters.telegram import TelegramService
        running = TelegramService.get().running
    except Exception:  # noqa: BLE001
        pass
    ready = credentials_ready()
    active = master_enabled()
    gateway_enabled = bool(release_controls.current().get("gateway", False))
    if running:
        state = "Connected"
    elif ready and active and not gateway_enabled:
        state = "Configured — blocked by gateway release control"
    elif ready and active:
        state = "Configured — service offline"
    elif ready:
        state = "Configured — disabled"
    else:
        state = "Not configured"
    return {
        "configured": ready,
        "token_saved": bool(token()),
        "allowed_count": len(allowed_ids()),
        "master_enabled": active,
        "gateway_enabled": gateway_enabled,
        "running": running,
        "state": state,
        "blocked_by": (
            "credentials"
            if not ready
            else "master_toggle"
            if not active
            else "gateway_release_control"
            if not gateway_enabled
            else "runtime"
            if not running
            else ""
        ),
        "backend": backend_label(),
    }


async def test_connection() -> ConnectionResult:
    """Tes Bot API dengan SDK resmi tanpa membocorkan URL/token saat gagal."""
    bot_token = token()
    if not bot_token or not allowed_ids():
        return ConnectionResult(False, "Simpan token dan allowlist terlebih dahulu.")
    try:
        from telegram import Bot
    except ImportError:
        return ConnectionResult(False, "python-telegram-bot belum terpasang.")
    try:
        async with Bot(token=bot_token) as bot:
            me = await bot.get_me()
        name = _safe_name(getattr(me, "username", "") or
                          getattr(me, "first_name", "") or "Telegram bot")
        return ConnectionResult(True, f"Terhubung sebagai {name}.", name)
    except Exception as exc:  # noqa: BLE001 - raw error dapat memuat URL token
        return ConnectionResult(False,
                                f"Koneksi Telegram gagal ({type(exc).__name__}).")


def test_connection_sync() -> ConnectionResult:
    return asyncio.run(test_connection())


def _safe_name(value: object) -> str:
    return re.sub(r"[\x00-\x1f\x7f]", "", str(value)).strip()[:80] \
        or "Telegram bot"


def start_runtime() -> bool:
    """Start the application-owned gateway runtime only when configured."""
    if not enabled() or not release_controls.current().get("gateway", False):
        return False
    try:
        from jarvis.gateway.runtime import telegram_runtime
        runtime = telegram_runtime()
        for actor_id in allowed_ids():
            runtime.manager.pair(
                "telegram", str(actor_id), paired_by="local-telegram-config")
        return runtime.start()
    except Exception as exc:  # noqa: BLE001
        _logger.warning("telegram.runtime_start_failed", error=type(exc).__name__)
        return False


def apply_runtime() -> bool:
    """Terapkan toggle/kredensial melalui lifecycle GatewayManager yang nyata."""
    try:
        from jarvis.gateway.runtime import telegram_runtime
        runtime = telegram_runtime()
        runtime.stop()
        return runtime.start() if (
            enabled() and release_controls.current().get("gateway", False)
        ) else True
    except Exception as exc:  # noqa: BLE001
        _logger.warning("telegram.runtime_apply_failed",
                        error=type(exc).__name__)
        return False
