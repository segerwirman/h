"""MessagingService (PARITY v2 §6) — status & konfigurasi platform Hermes.

Jarvis TIDAK menulis adapter platform (Hermes punya 22). Panel Messaging =
editor konfigurasi Hermes + penampil status:

    BACA (langsung file, read-only, tanpa subprocess):
      ~/.hermes/.env                 kredensial (nilai di-redact untuk UI)
      ~/.hermes/config.yaml          platforms.<id>.enabled
      ~/.hermes/gateway_state.json   state runtime per platform

    TULIS (via HermesBridge → CLI, tervalidasi Hermes sendiri):
      hermes config set KEY value                    (kredensial → .env)
      hermes config set platforms.<id>.enabled bool  (toggle, diverifikasi
                                                      dengan baca ulang)
      hermes gateway restart                         (apply)

KEAMANAN (§6.4 — syarat, bukan saran): platform ber-allowlist tidak bisa
di-enable selama allowlist kosong. ``GATEWAY_ALLOW_ALL_USERS`` aktif →
ditandai agar UI menampilkan peringatan merah.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from jarvis.core import log
from jarvis.integrations.hermes.bridge import HermesBridge, is_enabled
from jarvis.integrations.hermes import platform_catalog as catalog

_logger = log.get("hermes.messaging")

# state runtime gateway yang berarti "hidup & terhubung"
_LIVE_STATES = {"connected", "running", "ready"}
_DISABLED_MESSAGE = (
    "Integrasi Hermes dinonaktifkan; gunakan messaging native Jarvis."
)


def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME", "")
                or Path.home() / ".hermes")


def _redact(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return ""
    return ("•" * 8) + v[-4:] if len(v) > 4 else "•" * 8


def read_env() -> dict[str, str]:
    """Parse ~/.hermes/.env → dict. File hilang/korup → kosong."""
    out: dict[str, str] = {}
    try:
        for line in (hermes_home() / ".env").read_text(
                encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    except FileNotFoundError:
        pass
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("messaging.env_unreadable", error=str(e)[:100])
    return out


def read_platforms_config() -> dict:
    """Blok ``platforms:`` dari config.yaml Hermes. Gagal → kosong."""
    try:
        import yaml
        data = yaml.safe_load((hermes_home() / "config.yaml").read_text(
            encoding="utf-8", errors="replace")) or {}
        platforms = data.get("platforms")
        return platforms if isinstance(platforms, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("messaging.config_unreadable", error=str(e)[:100])
        return {}


def read_runtime() -> dict:
    """gateway_state.json Hermes. Gagal/hilang → kosong."""
    try:
        data = json.loads((hermes_home() / "gateway_state.json").read_text(
            encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("messaging.runtime_unreadable", error=str(e)[:100])
        return {}


def _derive_state(enabled: bool, configured: bool, gateway_alive: bool,
                  runtime_state: str | None) -> str:
    """Mirror derivasi Hermes (web_server._messaging_platform_payload)."""
    if not enabled:
        return "disabled"
    if not configured:
        return "not_configured"
    if runtime_state:
        return runtime_state
    if gateway_alive:
        return "pending_restart"
    return "gateway_stopped"


def list_platforms() -> list[dict]:
    """Status seluruh platform katalog untuk UI. Murni baca file."""
    if not is_enabled():
        # Keep the existing panel shape stable without reading ~/.hermes.
        # Phase 8 replaces this compatibility service with native messaging.
        return [{
            "id": s.id,
            "name": s.name,
            "description": s.description,
            "enabled": False,
            "configured": False,
            "allowlist_ok": s.allowlist_key is None,
            "allow_all": False,
            "state": "disabled",
            "live": False,
            "fields": [{
                "key": key,
                "required": key in s.required_env,
                "secret": catalog.is_secret(key),
                "is_allowlist": key == s.allowlist_key,
                "is_set": False,
                "redacted": "",
            } for key in s.env_vars],
        } for s in catalog.CATALOG]

    env = read_env()
    platforms_cfg = read_platforms_config()
    runtime = read_runtime()
    runtime_platforms = runtime.get("platforms") or {}
    gateway_alive = str(runtime.get("gateway_state", "")).lower() == "running"
    allow_all = str(env.get(catalog.ALLOW_ALL_ENV, "")).strip().lower() \
        in ("1", "true", "yes", "on")

    out = []
    for s in catalog.CATALOG:
        plat_cfg = platforms_cfg.get(s.id)
        enabled = bool(isinstance(plat_cfg, dict) and plat_cfg.get("enabled"))
        configured = all(env.get(k) for k in s.required_env)
        rt = runtime_platforms.get(s.id)
        rt_state = str(rt.get("state")) if isinstance(rt, dict) \
            and rt.get("state") else None
        allow_key = s.allowlist_key
        allowlist_ok = bool(allow_key is None or env.get(allow_key))
        fields = [{
            "key": k,
            "required": k in s.required_env,
            "secret": catalog.is_secret(k),
            "is_allowlist": k == allow_key,
            "is_set": bool(env.get(k)),
            "redacted": _redact(env.get(k, ""))
            if catalog.is_secret(k) else env.get(k, ""),
        } for k in s.env_vars]
        out.append({
            "id": s.id, "name": s.name, "description": s.description,
            "enabled": enabled, "configured": configured,
            "allowlist_ok": allowlist_ok, "allow_all": allow_all,
            "state": _derive_state(enabled, configured, gateway_alive,
                                   rt_state),
            "live": (rt_state or "").lower() in _LIVE_STATES,
            "fields": fields,
        })
    return out


def set_env(key: str, value: str) -> tuple[bool, str]:
    """Simpan satu kredensial via ``hermes config set``. Key harus dikenal
    katalog — Jarvis tidak menulis env var sembarangan ke instalasi Hermes."""
    if not is_enabled():
        return False, _DISABLED_MESSAGE
    if key not in catalog.known_env_keys():
        return False, f"key tidak dikenal katalog: {key}"
    value = (value or "").strip()
    if not value:
        return False, "nilai kosong — pakai clear_env untuk menghapus"
    r = HermesBridge.get().config_set(key, value)
    if not r.get("ok"):
        return False, (r.get("error") or r.get("stderr") or "gagal")[:160]
    return True, "tersimpan"


def clear_env(key: str) -> tuple[bool, str]:
    """Hapus key dari .env Hermes — surgical per baris (CLI tidak punya
    unset). Baris lain, komentar, urutan: utuh."""
    if not is_enabled():
        return False, _DISABLED_MESSAGE
    if key not in catalog.known_env_keys():
        return False, f"key tidak dikenal katalog: {key}"
    path = hermes_home() / ".env"
    try:
        lines = path.read_text(encoding="utf-8",
                               errors="replace").splitlines(keepends=True)
    except FileNotFoundError:
        return True, "sudah kosong"
    kept = [ln for ln in lines
            if not ln.strip().startswith(f"{key}=")]
    if len(kept) == len(lines):
        return True, "sudah kosong"
    try:
        path.write_text("".join(kept), encoding="utf-8")
        return True, "dihapus"
    except Exception as e:                                   # noqa: BLE001
        return False, str(e)[:160]


def set_enabled(platform_id: str, enabled: bool,
                allow_all_confirmed: bool = False) -> tuple[bool, str]:
    """Toggle platform. ENFORCEMENT §6.4:

    - enable ditolak bila platform ber-allowlist dan allowlist kosong,
      KECUALI GATEWAY_ALLOW_ALL_USERS aktif DAN user sudah konfirmasi
      eksplisit kedua (allow_all_confirmed).
    - hasil diverifikasi baca ulang config.yaml — bukan percaya exit code.
    """
    if not is_enabled():
        return False, _DISABLED_MESSAGE
    s = catalog.spec(platform_id)
    if s is None:
        return False, f"platform tidak dikenal: {platform_id}"
    if enabled:
        env = read_env()
        allow_key = s.allowlist_key
        has_allowlist = bool(allow_key and env.get(allow_key))
        allow_all = str(env.get(catalog.ALLOW_ALL_ENV, "")).strip().lower() \
            in ("1", "true", "yes", "on")
        if allow_key and not has_allowlist:
            if not (allow_all and allow_all_confirmed):
                return False, (f"allowlist kosong — isi {allow_key} dulu. "
                               "Bot messaging tanpa allowlist = komputer "
                               "terbuka ke internet.")
    r = HermesBridge.get().config_set(f"platforms.{platform_id}.enabled",
                                      "true" if enabled else "false")
    if not r.get("ok"):
        return False, (r.get("error") or r.get("stderr") or "gagal")[:160]
    # verifikasi nyata — config set bisa "sukses" tanpa efek di versi lain
    plat = read_platforms_config().get(platform_id)
    actual = bool(isinstance(plat, dict) and plat.get("enabled"))
    if actual != enabled:
        return False, ("hermes config set tidak berefek — versi CLI tidak "
                       "mendukung key platforms.*; toggle lewat "
                       "'hermes gateway' manual")
    return True, "tersimpan — restart gateway untuk menerapkan"


def restart_gateway() -> tuple[bool, str]:
    if not is_enabled():
        return False, _DISABLED_MESSAGE
    r = HermesBridge.get().gateway_command("restart")
    if not r.get("ok"):
        return False, (r.get("error") or r.get("stderr") or "gagal")[:160]
    return True, "gateway di-restart"
