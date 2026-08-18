"""Telemetri lokal tool: append, agregasi incremental, rotasi, rollup.

Tidak ada data yang dikirim keluar. Registry tetap pemilik kontrak eksekusi;
modul ini hanya wrapper persistence untuk ``tools.jsonl``.
"""
from __future__ import annotations

import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

from jarvis.agent.paths import logs_dir
from jarvis.core import config, log, quiet

_logger = log.get("agent.tool_usage")
_lock = threading.RLock()

_counts: dict[str, int] = {}
_rollup_counts: dict[str, int] = {}
_offset = 0
_path_seen = ""
_rollup_sig: tuple[int, int] | None = None


def jsonl_path() -> Path:
    return logs_dir() / "tools.jsonl"


def rollup_path() -> Path:
    return logs_dir() / "tools_rollup.json"


def _reset_active() -> None:
    global _counts, _offset
    _counts = {}
    _offset = 0


def _reset_all() -> None:
    global _rollup_counts, _rollup_sig
    _reset_active()
    _rollup_counts = {}
    _rollup_sig = None


def _successful_counts(lines: bytes) -> dict[str, int]:
    counts: dict[str, int] = {}
    for raw in lines.splitlines():
        try:
            record = json.loads(raw.decode("utf-8", errors="replace"))
        except Exception as exc:                              # noqa: BLE001
            quiet.swallowed("agent.tool_usage.line_skipped", exc)
            continue
        if record.get("ok") is True and record.get("tool"):
            name = str(record["tool"])
            counts[name] = counts.get(name, 0) + 1
    return counts


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.replace(tmp, path)


def _load_rollup() -> None:
    global _rollup_counts, _rollup_sig
    path = rollup_path()
    try:
        st = path.stat()
        sig = (st.st_mtime_ns, st.st_size)
        if sig == _rollup_sig:
            return
        data = json.loads(path.read_text(encoding="utf-8"))
        counts = data.get("counts") if isinstance(data, dict) else {}
        _rollup_counts = {str(k): int(v) for k, v in (counts or {}).items()}
        _rollup_sig = sig
    except FileNotFoundError:
        _rollup_counts = {}
        _rollup_sig = None
    except Exception as exc:
        _logger.warning("tool_usage.rollup_read_failed",
                        error=type(exc).__name__)


def _rotation_due(path: Path, incoming_bytes: int) -> bool:
    try:
        st = path.stat()
    except FileNotFoundError:
        return False
    max_bytes = int(config.get("telemetry.tools.max_bytes", 5 * 1024 * 1024))
    if max_bytes > 0 and st.st_size + incoming_bytes > max_bytes:
        return True
    daily = bool(config.get("telemetry.tools.rotate_daily", True))
    if daily:
        written = datetime.fromtimestamp(st.st_mtime).date()
        if written != datetime.now().date():
            return True
    return False


def _rotated_path(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidate = path.with_name(f"tools-{stamp}.jsonl")
    index = 1
    while candidate.exists():
        candidate = path.with_name(f"tools-{stamp}-{index}.jsonl")
        index += 1
    return candidate


def _rotate(path: Path) -> None:
    global _rollup_sig
    try:
        raw = path.read_bytes()
        delta = _successful_counts(raw)
        target = _rotated_path(path)
        os.replace(path, target)
        _load_rollup()
        merged = dict(_rollup_counts)
        for name, count in delta.items():
            merged[name] = merged.get(name, 0) + count
        _atomic_json(rollup_path(), {
            "version": 1, "updated_at": time.time(), "counts": merged,
            "last_rotated_file": target.name,
        })
        _rollup_sig = None
        _reset_active()
        _logger.info("tool_usage.rotated", file=target.name,
                     bytes=len(raw))
    except FileNotFoundError:
        return
    except Exception as exc:
        _logger.warning("tool_usage.rotate_failed", error=type(exc).__name__)


def append_record(record: dict) -> None:
    """Append satu event; rotasi sebelum tulis. Best-effort, tidak raise."""
    line = (json.dumps(record, ensure_ascii=False, default=str) + "\n") \
        .encode("utf-8")
    with _lock:
        try:
            path = jsonl_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            if _rotation_due(path, len(line)):
                _rotate(path)
            with path.open("ab") as fh:
                fh.write(line)
        except Exception as exc:
            _logger.debug("tool_usage.append_failed", error=type(exc).__name__)


def aggregate() -> dict[str, int]:
    """Counter sukses lifetime (rollup + file aktif), dibaca incremental."""
    global _offset, _path_seen
    with _lock:
        try:
            path = jsonl_path()
            key = str(path)
            if key != _path_seen:
                _path_seen = key
                _reset_all()
            _load_rollup()
            try:
                size = path.stat().st_size
            except FileNotFoundError:
                _reset_active()
                return dict(_rollup_counts)
            if size < _offset:
                _reset_active()
            if size > _offset:
                with path.open("rb") as fh:
                    fh.seek(_offset)
                    chunk = fh.read()
                end = chunk.rfind(b"\n")
                if end >= 0:
                    complete = chunk[:end + 1]
                    _offset += end + 1
                    for name, count in _successful_counts(complete).items():
                        _counts[name] = _counts.get(name, 0) + count
            merged = dict(_rollup_counts)
            for name, count in _counts.items():
                merged[name] = merged.get(name, 0) + count
            return merged
        except Exception as exc:
            _logger.debug("tool_usage.aggregate_failed",
                          error=type(exc).__name__)
            merged = dict(_rollup_counts)
            for name, count in _counts.items():
                merged[name] = merged.get(name, 0) + count
            return merged
