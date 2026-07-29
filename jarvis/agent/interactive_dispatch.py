"""Interactive lifecycle wrapper around the existing native dispatcher."""
from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from jarvis.agent import dispatch
from jarvis.agent.interaction import (
    render_failure,
    render_success,
    unavailable_reason,
)

FeedbackCallback = Callable[[str, str], None]


def start(
    task: str,
    *,
    on_ack: FeedbackCallback | None = None,
    on_done: FeedbackCallback | None = None,
    on_error: FeedbackCallback | None = None,
    adapter: Any = None,
    timeout_s: float | None = None,
    allowed_tools: list[str] | None = None,
    language: str | None = None,
    address: str | None = None,
    chooser=None,
) -> bool:
    """Start one T2+ task with a single, never-raising feedback lifecycle.

    Every external callback receives (raw, rendered_report). The native
    primitive remains responsible for ordering: it invokes on_ack before
    starting its worker and invokes no ACK when it returns False.
    """

    task_text = str(task or "").strip()
    lock = threading.Lock()
    ack_emitted = False
    terminal_emitted = False

    def _take_ack() -> bool:
        nonlocal ack_emitted
        with lock:
            if ack_emitted or terminal_emitted:
                return False
            ack_emitted = True
            return True

    def _take_terminal() -> bool:
        nonlocal terminal_emitted
        with lock:
            if terminal_emitted:
                return False
            terminal_emitted = True
            return True

    def _ack(raw: str) -> None:
        if not _take_ack():
            return
        try:
            # Satu composer untuk semua ingress native. Ia memiliki deadline
            # 250 ms dan fallback template lama, sehingga ACK tidak menggantung.
            from jarvis.agent.ack_composer import compose_ack
            report = compose_ack(task_text, language=language, address=address)
        except Exception:  # noqa: BLE001 - feedback cannot break dispatch
            report = str(raw or "")
        _safe_call(on_ack, str(raw or ""), report)

    def _done(raw: str) -> None:
        if not _take_terminal():
            return
        try:
            report = render_success(
                raw, task_text, language=language, address=address
            )
        except Exception:  # noqa: BLE001
            report = str(raw or "")
        _safe_call(on_done, str(raw or ""), report)

    def _error(raw: str) -> None:
        if not _take_terminal():
            return
        try:
            report = render_failure(
                raw, task_text, language=language, address=address
            )
        except Exception:  # noqa: BLE001
            report = str(raw or "")
        _safe_call(on_error, str(raw or ""), report)

    try:
        started = bool(dispatch.dispatch_async(
            task_text,
            on_ack=_ack,
            on_done=_done,
            on_error=_error,
            adapter=adapter,
            timeout_s=timeout_s,
            allowed_tools=allowed_tools,
        ))
    except Exception as exc:  # noqa: BLE001 - degrade like the primitive
        _error(f"{type(exc).__name__}: {exc}")
        return False

    if not started:
        _error(unavailable_reason(task_text, language))
    return started


def _safe_call(
    callback: FeedbackCallback | None, raw: str, report: str
) -> None:
    if callback is None:
        return
    try:
        callback(raw, report)
    except Exception:  # noqa: BLE001 - external delivery must never kill work
        pass
