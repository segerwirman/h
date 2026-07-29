"""Migrasi satu-arah credential plaintext lama ke ``secrets_store``.

Metadata non-secret dipertahankan. Sumber baru hanya dihapus setelah nilai
berhasil ditulis dan dibaca balik dari backend terenkripsi.
"""
from __future__ import annotations

import json
import os
import re
import stat
from dataclasses import dataclass, field
from pathlib import Path

from jarvis.core import config, log, secrets_store

_logger = log.get("core.secret_migration")
_SECRET_FIELD = re.compile(
    r"(?:api_?key|token|password|client_?secret|bot_?token)$", re.I)


@dataclass
class MigrationReport:
    migrated: list[str] = field(default_factory=list)
    pending: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.pending


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".migration.tmp")
    flags = os.O_WRONLY | os.O_CREAT | os.O_TRUNC
    fd = os.open(str(tmp), flags, stat.S_IRUSR | stat.S_IWUSR)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _store(secret_name: str, value: str, source: str,
           report: MigrationReport) -> bool:
    if not value:
        return True
    if secrets_store.set(secret_name, value) and \
            secrets_store.get(secret_name) == value:
        report.migrated.append(source)
        return True
    report.pending.append(source)
    return False


def _migrate_providers(report: MigrationReport) -> None:
    path = config.resolve_path(
        config.get("agent.providers_file", "config/providers.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    changed = False
    for name, entry in (data.get("providers") or {}).items():
        if not isinstance(entry, dict) or "api_key" not in entry:
            continue
        value = str(entry.get("api_key") or "")
        if not value or _store(f"jarvis/llm/{name}", value,
                               f"providers.{name}.api_key", report):
            entry.pop("api_key", None)
            changed = True
    if changed:
        _write_json(path, data)


def _migrate_api_keys(report: MigrationReport) -> None:
    path = config.resolve_path(
        config.get("llm.api_key_file", "config/api_keys.json"))
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    names = {
        "gemini_api_key": "jarvis/llm/gemini",
        "youtube_api_key": str(config.get(
            "integrations.youtube.api_key_secret_name",
            "jarvis/youtube/data_api_v3")),
    }
    changed = False
    for key in list(data):
        if not _SECRET_FIELD.search(str(key)):
            continue
        secret_name = names.get(key, f"jarvis/legacy/api_keys/{key}")
        value = str(data.get(key) or "")
        if not value or _store(secret_name, value, f"api_keys.{key}", report):
            data.pop(key, None)
            changed = True
    if changed:
        _write_json(path, data)


def _migrate_youtube_oauth(report: MigrationReport) -> None:
    path = config.resolve_path("config/youtube_oauth.json")
    try:
        raw = path.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict) or not any(data.values()):
        return
    name = str(config.get("integrations.youtube.oauth_token_secret_name",
                          "jarvis/youtube/oauth_token"))
    if _store(name, json.dumps(data, separators=(",", ":")),
              "youtube_oauth.credentials", report):
        _write_json(path, {})


def _migrate_blob(path: Path, secret_name: str, source: str,
                  report: MigrationReport) -> None:
    try:
        raw = path.read_text(encoding="utf-8").strip()
        data = json.loads(raw)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return
    if not isinstance(data, dict) or not any(data.values()):
        return
    if _store(secret_name, json.dumps(data, separators=(",", ":")),
              source, report):
        _write_json(path, {})


def migrate_legacy() -> MigrationReport:
    report = MigrationReport()
    _migrate_providers(report)
    _migrate_api_keys(report)
    _migrate_youtube_oauth(report)
    _migrate_blob(config.resolve_path("google_token.json"),
                  "jarvis/google/oauth_token", "google.oauth_token", report)
    try:
        from jarvis.agent.paths import data_dir
        spotify_path = data_dir() / "spotify_tokens.json"
    except Exception:
        spotify_path = config.resolve_path("data/spotify_tokens.json")
    _migrate_blob(spotify_path, "jarvis/oauth/spotify",
                  "spotify.oauth_token", report)
    _logger.info("secrets.legacy_migration",
                 migrated=len(report.migrated), pending=len(report.pending))
    return report
