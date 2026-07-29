"""Curator (PARITY v2 §8) — maintenance lifecycle skill hasil belajar.

Transisi lifecycle berbasis telemetry sidecar. Review default selalu dry-run;
arsip fisik tetap tindakan eksplisit melalui ``archive_skill``.
"""
from __future__ import annotations

import json
import shutil
import threading
import time

from jarvis.core import config, log
from jarvis.agent import skill_usage, skills

_logger = log.get("agent.curator")
_lock = threading.Lock()
_DAY_S = 86400


def _state_path():
    return skills.skills_dir() / ".curator_state.json"


def archive_dir():
    path = skills.skills_dir() / ".archive"
    path.mkdir(parents=True, exist_ok=True)
    return path


def _read_state() -> dict:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _write_state(state: dict) -> None:
    try:
        _state_path().write_text(json.dumps(state), encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        _logger.debug("curator.state_write_failed", error=str(exc)[:100])


def _last_activity(name: str, entry: dict) -> float:
    timestamp = float(entry.get("last_used", 0) or 0)
    if timestamp > 0:
        return timestamp
    try:
        return (skills.skills_dir() / name / "SKILL.md").stat().st_mtime
    except OSError:
        return 0.0


def archive_skill(name: str) -> tuple[bool, str]:
    """Pindahkan skill agent-created ke .archive/, tanpa delete."""
    with _lock:
        entry = skill_usage.entry_of(name)
        if not entry.get("is_agent_created"):
            return False, "hanya skill buatan agent yang bisa diarsip"
        source = skills.skills_dir() / name
        if not source.is_dir():
            return False, "skill tidak ditemukan"
        destination = archive_dir() / name
        if destination.exists():
            return False, "sudah ada arsip dengan nama sama"
        try:
            shutil.move(str(source), str(destination))
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:120]
        skill_usage.set_lifecycle(name, skill_usage.LIFECYCLE_ARCHIVED)
        _logger.info("curator.archived", name=name)
        return True, f"skill {name} diarsipkan (pulihkan via unarchive)"


def unarchive_skill(name: str) -> tuple[bool, str]:
    with _lock:
        source = archive_dir() / name
        if not source.is_dir():
            return False, "arsip tidak ditemukan"
        destination = skills.skills_dir() / name
        if destination.exists():
            return False, "skill aktif dengan nama sama sudah ada"
        try:
            shutil.move(str(source), str(destination))
        except Exception as exc:  # noqa: BLE001
            return False, str(exc)[:120]
        skill_usage.set_lifecycle(name, skill_usage.LIFECYCLE_ACTIVE)
        skill_usage.bump(name, "use")
        _logger.info("curator.unarchived", name=name)
        return True, f"skill {name} dipulihkan"


def list_archived() -> list[str]:
    try:
        return sorted(path.name for path in archive_dir().iterdir() if path.is_dir())
    except OSError:
        return []


def review(stale_after_s: float, dry_run: bool = True) -> dict[str, list[str]]:
    """Report stale agent-created skills; mutate only when explicitly requested."""
    result = {"stale": [], "archived": []}
    now = time.time()
    for name, entry in skill_usage.all_usage().items():
        if not entry.get("is_agent_created") or entry.get("pinned"):
            continue
        if entry.get("lifecycle", skill_usage.LIFECYCLE_ACTIVE) != skill_usage.LIFECYCLE_ACTIVE:
            continue
        if now - _last_activity(name, entry) <= stale_after_s:
            continue
        result["stale"].append(name)
        if not dry_run:
            skill_usage.set_lifecycle(name, skill_usage.LIFECYCLE_STALE)
    return result


def run_transitions(now: float | None = None) -> dict:
    """Compatibility scheduled pass. It reports first; no automatic archive."""
    now = now or time.time()
    stale_after = float(config.get("curator.stale_after_days", 14)) * _DAY_S
    return review(stale_after, dry_run=False)


def maybe_run(now: float | None = None) -> dict | None:
    """Best-effort scheduled stale review; no archival side effect."""
    try:
        if not bool(config.get("curator.enabled", True)):
            return None
        now = now or time.time()
        interval_s = float(config.get("curator.interval_hours", 24)) * 3600
        state = _read_state()
        if now - float(state.get("last_run_at", 0) or 0) < interval_s:
            return None
        result = run_transitions(now)
        state["last_run_at"] = now
        _write_state(state)
        return result
    except Exception as exc:  # noqa: BLE001
        _logger.warning("curator.run_failed", error=str(exc)[:120])
        return None


def maybe_run_async() -> None:
    threading.Thread(target=maybe_run, daemon=True, name="skill-curator").start()
