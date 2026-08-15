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
_inflight: tuple[tuple[str, bool], ...] | None = None
_inflight_live_id: int | None = None
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
    """Queue only legacy results that have no registry-scoped speech owner."""
    try:
        from jarvis.integrations.voice_speech import current_delivery_scope

        scope = current_delivery_scope()
        if scope is not None and scope.task_id:
            # Returning False deliberately sends the frozen voice callback to
            # ``self.speak``; its composed wrapper then uses this exact scope.
            return False
    except Exception as exc:  # noqa: BLE001 - fallback bridge stays fail-open
        _logger.warning(
            "voice.notice.scope_lookup_failed", error=type(exc).__name__
        )
    status = "berhasil" if ok else "gagal"
    return enqueue(
        f"[TUGAS] {_clean(task, 120)} ({status}): {_clean(result, 180)}",
        request_response=True,
    )


def _settle_batch(
    ticket,
    batch: tuple[tuple[str, bool], ...],
    live_id: int,
) -> None:
    global _inflight, _inflight_live_id
    with _lock:
        if _inflight != batch or _inflight_live_id != live_id:
            return
        _inflight = None
        _inflight_live_id = None
        if ticket.completed:
            return
        # Playback abort means the batch was submitted but never verified as
        # audible. Restore its original order and let the next safe boundary retry.
        _pending.extendleft(reversed(batch))


async def flush_at_turn_boundary(live: Any) -> bool:
    """Submit one generic batch through the shared playback-aware Live lane."""
    global _inflight, _inflight_live_id
    if not _enabled():
        return False
    key = id(live)
    try:
        from jarvis.integrations import voice_speech

        if not voice_speech.notice_lane_idle(live):
            _boundary_waiting.add(key)
            return False
        _boundary_waiting.discard(key)
        with _lock:
            if _inflight is not None or not _pending:
                return False
            batch = tuple(_pending)
            _pending.clear()
            _inflight = batch
            _inflight_live_id = key
        boundary = int(
            getattr(live, "_voice_turn_boundary_epoch", 0) or 0
        )
        if not voice_speech.claim_turn_boundary(live):
            with _lock:
                if _inflight == batch and _inflight_live_id == key:
                    _inflight = None
                    _inflight_live_id = None
                    _pending.extendleft(reversed(batch))
            return False
        needs_playback = any(
            needs_response for _, needs_response in batch
        )
        ticket = voice_speech.submit_exact(
            live,
            "\n".join(text for text, _ in batch),
            exact=False,
            turn_complete=needs_playback,
            require_playback=needs_playback,
        )
        if ticket.aborted:
            voice_speech.release_turn_boundary(live, boundary)
            _settle_batch(ticket, batch, key)
            return False
        ticket.add_done_callback(
            lambda done: (
                voice_speech.release_turn_boundary(live, boundary)
                if done.aborted else None,
                _settle_batch(done, batch, key),
            )
        )
        return True
    except Exception as exc:  # noqa: BLE001 - producer bridge always fail-open
        _logger.warning("voice.notice.flush_failed", error=type(exc).__name__)
        try:
            with _lock:
                if (_inflight is not None
                        and _inflight_live_id == key):
                    batch = _inflight
                    _inflight = None
                    _inflight_live_id = None
                    _pending.extendleft(reversed(batch))
        except Exception:
            pass
        return False


def pending_count() -> int:
    with _lock:
        return len(_pending) + (len(_inflight) if _inflight is not None else 0)


def pending_snapshot() -> list[str]:
    with _lock:
        inflight = list(_inflight or ())
        return [text for text, _ in [*inflight, *_pending]]


def _reset_for_tests() -> None:
    global _inflight, _inflight_live_id
    with _lock:
        _pending.clear()
        _inflight = None
        _inflight_live_id = None
    _boundary_waiting.clear()




__all__ = [
    "enqueue",
    "flush_at_turn_boundary",
    "remember_action",
    "remember_agent_result",
]
