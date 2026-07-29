"""PROMPT N — antrean notice generik, dibatch pada batas giliran Gemini Live."""
from __future__ import annotations

from collections import deque
from datetime import datetime
import threading
from typing import Any

from jarvis.agent import memory_store
from jarvis.core import config, log
from jarvis.core.action_registry import Action

_logger = log.get("voice.notices")
_MAX_ACTIVE = 20
_lock = threading.Lock()
_pending: deque[tuple[str, bool]] = deque(maxlen=_MAX_ACTIVE)
_boundary_waiting: set[int] = set()


def _enabled() -> bool:
    return bool(config.get("routing.voice_notice_bridge.enabled", False))


def _clean(value: str, limit: int = 240) -> str:
    return " ".join(str(value or "").split())[:limit]


def enqueue(text: str, *, request_response: bool = False) -> bool:
    """Terima notice dari produsen mana pun. Tidak pernah merusak caller."""
    if not _enabled():
        return False
    clean = _clean(text)
    if not clean:
        return False
    try:
        with _lock:
            _pending.append((clean, bool(request_response)))
        return True
    except Exception as exc:  # noqa: BLE001 - producer always fail-open
        _logger.warning("voice.notice.enqueue_failed", error=type(exc).__name__)
        return False


def _rememberable(action: Action) -> bool:
    if action.kind == "app":
        return action.verb in {"open", "close"}
    if action.kind == "panel":
        return action.verb in {"open", "toggle"}
    return action.kind == "system" and action.target not in {
        "volume_up", "volume_down", "volume_mute", "screenshot",
    }


def _action_text(action: Action) -> str:
    if action.kind == "app":
        label = str(action.args.get("app") or action.target)
        return f"{'buka' if action.verb == 'open' else 'tutup'} aplikasi {label}"
    if action.kind == "panel":
        return f"buka panel {action.args.get('panel', action.target)}"
    return f"ubah {action.target}"


def remember_action(action: Action, result: str = "berhasil") -> bool:
    """Aksi L0/L1 bermakna masuk SQLite agent dan konteks turn berikutnya."""
    if not _enabled() or not _rememberable(action):
        return False
    notice = f"[AKSI] {datetime.now():%H:%M} {_action_text(action)} ({_clean(result, 60)})"
    try:
        memory_store.write(
            "episodic", notice, importance=0.35,
            tags=["voice", "local-action", action.kind, action.target],
            scope="device-local", owner="device",
        )
    except Exception as exc:  # noqa: BLE001 - SQLite outage must not block action
        _logger.warning("voice.notice.memory_failed", error=type(exc).__name__)
    return enqueue(notice, request_response=False)


def remember_agent_result(task: str, result: str, *, ok: bool) -> bool:
    """PROMPT 4(b): completion agent memakai antrean sama dan meminta jawaban."""
    status = "berhasil" if ok else "gagal"
    return enqueue(
        f"[TUGAS] {_clean(task, 120)} ({status}): {_clean(result, 180)}",
        request_response=True,
    )


async def flush_at_turn_boundary(live: Any) -> bool:
    """Flush satu batch setelah turn selesai; bicara aktif selalu menang."""
    if not _enabled():
        return False
    key = id(live)
    if bool(getattr(live, "_is_speaking", True)):
        _boundary_waiting.add(key)
        return False
    _boundary_waiting.discard(key)
    batch: list[tuple[str, bool]] = []
    try:
        with _lock:
            if not _pending:
                return False
            batch = list(_pending)
            _pending.clear()
        session = getattr(live, "session", None)
        if session is None:
            raise RuntimeError("session_unavailable")
        await session.send_client_content(
            turns={"parts": [{"text": "\n".join(text for text, _ in batch)}]},
            turn_complete=any(needs_response for _, needs_response in batch),
        )
        return True
    except Exception as exc:  # noqa: BLE001 - restore exactly-once batch on failure
        _logger.warning("voice.notice.flush_failed", error=type(exc).__name__)
        try:
            with _lock:
                _pending.extendleft(reversed(batch))
        except Exception:
            pass
        return False


def pending_count() -> int:
    with _lock:
        return len(_pending)


def pending_snapshot() -> list[str]:
    with _lock:
        return [text for text, _ in _pending]


def _reset_for_tests() -> None:
    with _lock:
        _pending.clear()
    _boundary_waiting.clear()


def install(legacy: Any) -> bool:
    """Assign seam only while feature flag is enabled; off is legacy no-op."""
    if not _enabled():
        return False
    legacy.VOICE_NOTICE = __import__(__name__, fromlist=["*"])
    return True


__all__ = ["enqueue", "flush_at_turn_boundary", "install", "remember_action", "remember_agent_result"]
