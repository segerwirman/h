"""Rincian latensi per tahap untuk satu giliran kerja (Fase 24).

Siklus ini dua kali membuktikan tebakan arsitektur bisa meleset total: S-13
dikira pustaka native padahal thread ``SetupQueue`` yang bocor, dan S-22 dikira
ambang atau mikrofon padahal echo guard buatan sendiri. Keduanya baru selesai
setelah ada angka.

Karena itu modul ini mendahului seluruh optimasi Siklus 4. Total 7 detik tidak
memberi tahu apa pun; "LLM pertama 3,4 detik" memberi tahu ke mana harus
melihat.

Aturan modul: **tidak pernah melempar, dan tidak pernah menahan pekerjaan.**
Pengukur yang menjatuhkan tugas lebih buruk daripada tidak mengukur. Jumlah
giliran aktif dibatasi agar ia sendiri tidak menjadi kebocoran seperti S-14.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

from jarvis.core import config, log

_logger = log.get("core.latency")

MAX_TURNS = 64

_lock = threading.Lock()
_turns: dict = {}


def enabled() -> bool:
    try:
        return bool(config.get("agent.latency.enabled", True))
    except Exception:                                        # noqa: BLE001
        return True


@dataclass
class _Turn:
    started_at: float
    task: str = ""
    last_at: float = 0.0
    stages: list = field(default_factory=list)
    seen: set = field(default_factory=set)


def _key(value) -> str | None:
    try:
        text = str(value or "").strip()
    except Exception:                                        # noqa: BLE001
        return None
    return text or None


def start(key, *, task: str = "", now: float | None = None) -> None:
    """Buka pengukuran satu giliran. Aman dipanggil dua kali."""
    try:
        if not enabled():
            return
        name = _key(key)
        if name is None:
            return
        moment = time.monotonic() if now is None else float(now)
        with _lock:
            # Batas keras: pengukur tidak boleh tumbuh tanpa henti. Giliran
            # tertua dibuang lebih dulu.
            while len(_turns) >= MAX_TURNS:
                oldest = min(_turns, key=lambda k: _turns[k].started_at)
                _turns.pop(oldest, None)
            _turns[name] = _Turn(started_at=moment, last_at=moment,
                                 task=str(task or "")[:160])
    except Exception:                                        # noqa: BLE001
        pass


def mark(key, stage: str, *, now: float | None = None) -> None:
    """Catat satu tahap. Tahap yang sama hanya dicatat sekali — "pertama"
    memang berarti yang pertama, dan iterasi berikutnya tidak menimpanya."""
    try:
        name = _key(key)
        if name is None:
            return
        label = str(stage or "").strip()
        if not label:
            return
        moment = time.monotonic() if now is None else float(now)
        with _lock:
            turn = _turns.get(name)
            if turn is None or label in turn.seen:
                return
            turn.seen.add(label)
            turn.stages.append((label, round((moment - turn.last_at) * 1000, 1)))
            turn.last_at = moment
    except Exception:                                        # noqa: BLE001
        pass


def finish(key, *, now: float | None = None) -> dict:
    """Tutup pengukuran dan terbitkan SATU baris log untuk giliran ini."""
    try:
        name = _key(key)
        if name is None:
            return {}
        moment = time.monotonic() if now is None else float(now)
        with _lock:
            turn = _turns.pop(name, None)
        if turn is None:
            return {}
        report = {
            "task": turn.task,
            "total_ms": round((moment - turn.started_at) * 1000, 1),
            "stages": list(turn.stages),
        }
        fields = {f"{stage}_ms": value for stage, value in turn.stages}
        _logger.info("latency.turn", total_ms=report["total_ms"],
                     task=turn.task[:80], **fields)
        return report
    except Exception:                                        # noqa: BLE001
        return {}


def active_count() -> int:
    with _lock:
        return len(_turns)


def reset() -> None:
    with _lock:
        _turns.clear()


__all__ = ["MAX_TURNS", "active_count", "enabled", "finish", "mark", "reset",
           "start"]
