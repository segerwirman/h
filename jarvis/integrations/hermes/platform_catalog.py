"""Katalog platform messaging Hermes (PARITY v2 §6.3) — DATA, bukan UI.

Mirror dari ``hermes_cli/web_server.py::_PLATFORM_OVERRIDES`` (diverifikasi
2026-07-17 terhadap hermes-agent-main). UI merender dari data ini —
nol hardcode field di widget. Menambah platform = menambah entri di sini.

Konvensi Hermes:
    env_vars     — semua field platform (di ``~/.hermes/.env``)
    required_env — subset wajib; sisanya tampil di seksi ADVANCED
    field *_ALLOWED_USERS — allowlist (§6.4: WAJIB sebelum enable)

Kredensial ditulis via ``hermes config set KEY value`` (bridge), flag
on/off di ``config.yaml platforms.<id>.enabled`` milik Hermes.
"""
from __future__ import annotations

from dataclasses import dataclass

_SECRET_MARKERS = ("TOKEN", "SECRET", "KEY", "PASSWORD")

# global Hermes: matikan seluruh allowlist (dev only) — dipantau untuk warning
ALLOW_ALL_ENV = "GATEWAY_ALLOW_ALL_USERS"


@dataclass(frozen=True)
class PlatformSpec:
    id: str
    name: str
    description: str
    env_vars: tuple[str, ...]
    required_env: tuple[str, ...]

    @property
    def allowlist_key(self) -> str | None:
        for key in self.env_vars:
            if key.endswith("_ALLOWED_USERS"):
                return key
        return None


def is_secret(key: str) -> bool:
    return any(m in key for m in _SECRET_MARKERS)


CATALOG: tuple[PlatformSpec, ...] = (
    PlatformSpec(
        "telegram", "Telegram",
        "Jalankan Jarvis dari DM, grup, dan topic Telegram.",
        ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_USERS", "TELEGRAM_PROXY"),
        ("TELEGRAM_BOT_TOKEN",)),
    PlatformSpec(
        "discord", "Discord",
        "Hubungkan Jarvis ke DM, channel, dan thread Discord.",
        ("DISCORD_BOT_TOKEN", "DISCORD_ALLOWED_USERS", "DISCORD_REPLY_TO_MODE"),
        ("DISCORD_BOT_TOKEN",)),
    PlatformSpec(
        "slack", "Slack",
        "Pakai Jarvis dari Slack via Socket Mode.",
        ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN", "SLACK_ALLOWED_USERS"),
        ("SLACK_BOT_TOKEN", "SLACK_APP_TOKEN")),
    PlatformSpec(
        "whatsapp", "WhatsApp",
        "Platform ini tidak butuh token di sini — pairing via QR/self-chat.",
        ("WHATSAPP_ENABLED", "WHATSAPP_MODE", "WHATSAPP_DM_POLICY",
         "WHATSAPP_ALLOWED_USERS"),
        ()),
    PlatformSpec(
        "signal", "Signal",
        "Hubungkan Jarvis ke Signal lewat signal-cli HTTP.",
        ("SIGNAL_HTTP_URL", "SIGNAL_ACCOUNT", "SIGNAL_ALLOWED_USERS"),
        ("SIGNAL_HTTP_URL", "SIGNAL_ACCOUNT")),
    PlatformSpec(
        "matrix", "Matrix",
        "Pakai Jarvis di room dan DM Matrix.",
        ("MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN", "MATRIX_USER_ID",
         "MATRIX_ALLOWED_USERS"),
        ("MATRIX_HOMESERVER", "MATRIX_ACCESS_TOKEN", "MATRIX_USER_ID")),
    PlatformSpec(
        "mattermost", "Mattermost",
        "Hubungkan Jarvis ke channel dan DM Mattermost.",
        ("MATTERMOST_URL", "MATTERMOST_TOKEN", "MATTERMOST_ALLOWED_USERS"),
        ("MATTERMOST_URL", "MATTERMOST_TOKEN")),
    PlatformSpec(
        "email", "Email",
        "Jarvis membaca dan membalas email (IMAP/SMTP). Tanpa field "
        "allowlist di Hermes — aktifkan hanya bila kotak masuk terpercaya.",
        ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_IMAP_HOST",
         "EMAIL_SMTP_HOST"),
        ("EMAIL_ADDRESS", "EMAIL_PASSWORD", "EMAIL_IMAP_HOST",
         "EMAIL_SMTP_HOST")),
)


def spec(platform_id: str) -> PlatformSpec | None:
    for s in CATALOG:
        if s.id == platform_id:
            return s
    return None


def known_env_keys() -> set[str]:
    out = {ALLOW_ALL_ENV}
    for s in CATALOG:
        out.update(s.env_vars)
    return out
