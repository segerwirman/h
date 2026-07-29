"""Config loader — single source of truth for every tunable (config.yaml)."""
from __future__ import annotations

import sys
import threading
from pathlib import Path
from typing import Any

import yaml


def base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent.parent


CONFIG_PATH = base_dir() / "config.yaml"

def _load_env():
    env_path = base_dir() / ".env"
    if env_path.exists():
        import os
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

_load_env()

_lock = threading.Lock()
_data: dict | None = None


def _load() -> dict:
    global _data
    with _lock:
        if _data is None:
            try:
                _data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
            except FileNotFoundError:
                _data = {}
        return _data


def reload() -> None:
    global _data
    with _lock:
        _data = None
    _load()


def get(path: str, default: Any = None) -> Any:
    """Dot-path lookup: cfg.get('orb.states.IDLE.diameter', 280)."""
    node: Any = _load()
    for key in path.split("."):
        if isinstance(node, dict) and key in node:
            node = node[key]
        else:
            return default
    return node


def section(path: str) -> dict:
    val = get(path, {})
    return val if isinstance(val, dict) else {}


def resolve_path(rel: str) -> Path:
    """Resolve a config-relative path against the project root."""
    p = Path(rel)
    return p if p.is_absolute() else base_dir() / p


def secret(env_name: str, config_path: str = "", default: str = "") -> str:
    """Secrets: environment variable first, config.yaml fallback.
    Never log the returned value."""
    import os
    val = os.environ.get(env_name, "")
    if val:
        return val
    if config_path:
        return str(get(config_path, default) or default)
    return default


def validate() -> list[str]:
    """Startup config validation → list of human-readable issues.
    Reports WHICH values are missing without ever printing secrets."""
    issues: list[str] = []
    if not CONFIG_PATH.exists():
        issues.append("config.yaml tidak ditemukan — semua nilai memakai default.")
    try:
        from jarvis.core import llm
        if not llm.api_key():
            issues.append("API key Gemini belum ada di penyimpanan aman.")
    except Exception:
        issues.append("Backend penyimpanan aman tidak tersedia.")
    import os
    if get("relay.enabled", False) or \
            os.environ.get("RELAY_ENABLED", "").lower() in ("1", "true"):
        if not secret("RELAY_WEBHOOK_SECRET"):
            issues.append("Relay aktif tetapi RELAY_WEBHOOK_SECRET kosong — "
                          "webhook tidak akan berjalan.")
    imap_user = secret("JARVIS_IMAP_USER", "nlp.email.imap_user")
    imap_pass = secret("JARVIS_IMAP_PASSWORD", "nlp.email.imap_password")
    if bool(imap_user) != bool(imap_pass):
        issues.append("Konfigurasi email tidak lengkap (user/password salah "
                      "satunya kosong) — modul email nonaktif.")
    if get("whatsapp_web.enabled", False):
        contacts_file = resolve_path(str(get(
            "whatsapp_web.contacts_file",
            "data/whatsapp_contacts.json",
        )))
        if not contacts_file.exists():
            issues.append(
                "WhatsApp Web aktif tetapi daftar kontak belum ada: "
                f"{contacts_file}."
            )
        if get("whatsapp_web.audio_bridge.enabled", False):
            remote_input = str(get(
                "whatsapp_web.audio_bridge.remote_input_device", ""
            ) or "").strip()
            remote_output = str(get(
                "whatsapp_web.audio_bridge.remote_output_device", ""
            ) or "").strip()
            if not remote_input or not remote_output:
                issues.append(
                    "Audio bridge WhatsApp aktif tetapi perangkat input/output "
                    "virtual belum lengkap."
                )
            elif remote_input.casefold() == remote_output.casefold():
                issues.append(
                    "Perangkat input dan output virtual WhatsApp harus berbeda."
                )
    if get("agent.enabled", True):
        try:
            from jarvis.agent import model_routing

            _client, provider, reason = model_routing.heavy_resolution()
            if not provider:
                issues.append(
                    "Agent native aktif tetapi provider tugas berat belum "
                    f"siap: {reason}."
                )
        except Exception as exc:
            issues.append(
                "Kesiapan provider tugas berat tidak dapat diperiksa "
                f"({type(exc).__name__})."
            )
    return issues
