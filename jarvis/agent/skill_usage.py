"""Sidecar telemetry untuk skill (PARITY v2 §4.1-4.2).

Pola Hermes (audit §B.4-B.5): counter + provenance disimpan di sidecar JSON
``jarvis/agent/skills_data/.usage.json`` — bukan di frontmatter SKILL.md,
supaya telemetry operasional tidak mencemari konten skill dan tidak bikin
konflik saat skill bundled diperbarui.

Struktur:

    {
      "laporan-harian": {
        "use": 40, "view": 3, "patch": 1,
        "last_used": 1752700000,
        "is_agent_created": false,     # sumber badge "learned" — EKSPLISIT,
        "pinned": false,               #   tidak diinferensi dari path/tanggal
        "lifecycle": "active"          # active | stale | archived (Fase 5)
      }
    }

Semua operasi best-effort: sidecar korup/hilang → mulai dari kosong; kegagalan
tulis di-log DEBUG dan diam. Telemetry tidak boleh pernah mengganggu eksekusi
skill.
"""
from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from pathlib import Path

from jarvis.core import log

_logger = log.get("agent.skill_usage")
_lock = threading.Lock()

KINDS = ("use", "view", "patch")

LIFECYCLE_ACTIVE = "active"
LIFECYCLE_STALE = "stale"
LIFECYCLE_ARCHIVED = "archived"


def sidecar_path() -> Path:
    from jarvis.agent import skills
    return skills.skills_dir() / ".usage.json"


def _default_entry() -> dict:
    return {"use": 0, "view": 0, "patch": 0, "last_used": 0,
            "is_agent_created": False, "pinned": False,
            "lifecycle": LIFECYCLE_ACTIVE}


def _load() -> dict:
    try:
        raw = json.loads(sidecar_path().read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            return {}
        return {k: v for k, v in raw.items() if isinstance(v, dict)}
    except FileNotFoundError:
        return {}
    except Exception as e:                                   # noqa: BLE001
        _logger.warning("skill_usage.sidecar_corrupt", error=str(e)[:100])
        return {}


def _atomic_write(data: dict) -> None:
    """tempfile + os.replace — aman dari corrupt saat crash di tengah tulis."""
    path = sidecar_path()
    fd, tmp = tempfile.mkstemp(dir=str(path.parent),
                               prefix=".usage-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _mutate(name: str, fn) -> None:
    """Terapkan mutasi pada entry ``name``. Tidak pernah raise."""
    if not name:
        return
    try:
        with _lock:
            data = _load()
            entry = data.get(name)
            if not isinstance(entry, dict):
                entry = _default_entry()
            merged = _default_entry()
            merged.update(entry)
            data[name] = merged
            fn(merged)
            _atomic_write(data)
    except Exception as e:                                   # noqa: BLE001
        _logger.debug("skill_usage.write_failed", name=name,
                      error=str(e)[:100])


def bump(name: str, kind: str) -> None:
    """Naikkan counter. kind: use | view | patch. Tidak pernah raise.

    Panggil SETELAH skill berhasil dipakai — bukan saat dipanggil.
    """
    if kind not in KINDS:
        return

    def _do(entry: dict) -> None:
        entry[kind] = int(entry.get(kind, 0) or 0) + 1
        entry["last_used"] = int(time.time())

    _mutate(name, _do)


def usage_of(name: str) -> int:
    """Total observed activity = use + view + patch (sesuai Hermes)."""
    try:
        entry = _load().get(name) or {}
        return sum(int(entry.get(k, 0) or 0) for k in KINDS)
    except Exception:                                        # noqa: BLE001
        return 0


def mark_agent_created(name: str) -> None:
    """Tandai skill sebagai buatan agent — sumber badge "learned".

    Dipanggil dari ``skill_manage`` action=create. EKSPLISIT saat pembuatan;
    JANGAN diinferensi dari lokasi/tanggal file (audit §B.5).
    """
    _mutate(name, lambda e: e.__setitem__("is_agent_created", True))


def is_agent_created(name: str) -> bool:
    try:
        return bool((_load().get(name) or {}).get("is_agent_created", False))
    except Exception:                                        # noqa: BLE001
        return False


def mark_hub_installed(name: str) -> None:
    """Tandai skill hasil install dari hub — badge 'hub' (§B.2)."""
    _mutate(name, lambda e: e.__setitem__("is_hub_installed", True))


def provenance(name: str) -> str:
    """'agent' (learned) | 'hub' (di-install) | 'bundled' (ikut repo)."""
    entry = _load().get(name) or {}
    if entry.get("is_agent_created"):
        return "agent"
    if entry.get("is_hub_installed"):
        return "hub"
    return "bundled"


def set_pinned(name: str, pinned: bool) -> None:
    """Pin = bypass semua transisi otomatis curator (Fase 5)."""
    _mutate(name, lambda e: e.__setitem__("pinned", bool(pinned)))


def set_lifecycle(name: str, state: str) -> None:
    if state not in (LIFECYCLE_ACTIVE, LIFECYCLE_STALE, LIFECYCLE_ARCHIVED):
        return
    _mutate(name, lambda e: e.__setitem__("lifecycle", state))


def entry_of(name: str) -> dict:
    return dict(_load().get(name) or {})


def forget(name: str) -> None:
    """Hapus entry sidecar (dipanggil saat skill di-delete). Tidak raise."""
    try:
        with _lock:
            data = _load()
            if name in data:
                del data[name]
                _atomic_write(data)
    except Exception as e:                                   # noqa: BLE001
        _logger.debug("skill_usage.forget_failed", name=name,
                      error=str(e)[:100])


def all_usage() -> dict:
    """Snapshot seluruh sidecar (untuk UI Fase 2). Salinan, aman dimutasi."""
    try:
        return json.loads(json.dumps(_load()))
    except Exception:                                        # noqa: BLE001
        return {}
