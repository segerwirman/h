"""Ephemeral, process-local continuations for approved high-risk tool calls.

Only the original process retains tool arguments. The durable approval database
contains metadata only, so a restart or TTL expiry safely drops the continuation.
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from jarvis.agent.base import ToolResult

_DEFAULT_TTL_S = 300.0


@dataclass(frozen=True)
class _Continuation:
    created_at: float
    is_approved: Callable[[], bool]
    runner: Callable[[], Awaitable[ToolResult]]


_lock = threading.Lock()
_items: dict[str, _Continuation] = {}


def _prune(now: float | None = None) -> None:
    current = time.monotonic() if now is None else float(now)
    expired = [request_id for request_id, item in _items.items()
               if current - item.created_at >= _DEFAULT_TTL_S]
    for request_id in expired:
        _items.pop(request_id, None)


def register(request_id: str, *, is_approved: Callable[[], bool],
             runner: Callable[[], Awaitable[ToolResult]]) -> bool:
    """Keep one executable continuation in memory; never write its args to disk."""
    key = str(request_id).strip()
    if not key:
        return False
    with _lock:
        _prune()
        _items[key] = _Continuation(time.monotonic(), is_approved, runner)
    return True


async def resume(request_id: str) -> ToolResult:
    """Run a one-shot continuation only after its durable approval is verified."""
    key = str(request_id).strip()
    with _lock:
        _prune()
        item = _items.get(key)
        if item is None:
            return ToolResult.fail("approval continuation tidak tersedia atau telah kedaluwarsa")
        try:
            approved = bool(item.is_approved())
        except Exception:  # noqa: BLE001
            approved = False
        if not approved:
            return ToolResult.fail("approval belum disetujui atau tidak lagi valid")
        _items.pop(key, None)
    try:
        return await item.runner()
    except Exception as exc:  # noqa: BLE001
        return ToolResult.fail(f"approval continuation gagal: {type(exc).__name__}")


def resume_sync(request_id: str) -> ToolResult:
    """Worker-thread helper for desktop UI; never call from an active event loop."""
    return asyncio.run(resume(request_id))


def clear() -> None:
    """Test/shutdown seam. Clears only volatile, never-persisted continuations."""
    with _lock:
        _items.clear()
