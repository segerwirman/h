"""Lokasi runtime agent — semuanya di bawah ``data/`` (dibuat on-demand)."""
from __future__ import annotations

from pathlib import Path

from jarvis.core import config


def data_dir() -> Path:
    p = config.resolve_path(str(config.get("agent.data_dir", "data")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def logs_dir() -> Path:
    p = data_dir() / "logs"
    p.mkdir(parents=True, exist_ok=True)
    return p


def generated_dir() -> Path:
    p = data_dir() / "generated"
    p.mkdir(parents=True, exist_ok=True)
    return p


def db_path() -> Path:
    return data_dir() / "agent.sqlite"


def workspace_root() -> Path:
    """Sandbox operasi file (§3.1.A). Default: root proyek."""
    ws = str(config.get("agent.workspace_root", "") or "")
    return Path(ws) if ws else config.base_dir()


def allowed_paths() -> list[Path]:
    raw = config.get("agent.allowed_paths", []) or []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.split(",") if x.strip()]
    return [Path(x) for x in raw]


def is_allowed_path(value: str | Path) -> bool:
    """Return whether a local path stays inside the configured file roots."""
    try:
        candidate = Path(value).expanduser()
        if not candidate.is_absolute():
            candidate = workspace_root() / candidate
        target = candidate.resolve()
        roots = [workspace_root().expanduser().resolve()]
        for raw in allowed_paths():
            root = raw.expanduser()
            if not root.is_absolute():
                root = workspace_root() / root
            roots.append(root.resolve())
        return any(target == root or root in target.parents for root in roots)
    except (OSError, TypeError, ValueError):
        return False
