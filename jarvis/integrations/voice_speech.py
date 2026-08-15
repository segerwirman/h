"""Playback-aware arbitration seam for exact-speech Gemini Live turns.

The frozen Live loop still owns sessions, receive scheduling, playback, reconnects,
and teardown.  This module only creates a ticket for an exact-speech submission
and lets the editable playback owner settle that ticket at an audible boundary.
"""
from __future__ import annotations

import asyncio
import contextvars
import weakref
from concurrent.futures import Future
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Callable, Iterator


_MARKER = "_jarvis_voice_speech_installed"
_SEND_TIMEOUT_S = 10.0
_NO_AUDIO_TIMEOUT_S = 15.0


@dataclass(frozen=True)
class DeliveryScope:
    task_id: str
    kind: str
    speech_enabled: bool = True


_delivery_scope: contextvars.ContextVar[DeliveryScope | None] = (
    contextvars.ContextVar("voice_speech_delivery_scope", default=None)
)


class PlaybackTicket:
    """Thread-safe terminal token for one submitted Live speech turn."""

    def __init__(self) -> None:
        self._future: Future[str] = Future()

    @property
    def done(self) -> bool:
        return self._future.done()

    @property
    def completed(self) -> bool:
        return self.done and self._future.result() == "completed"

    @property
    def aborted(self) -> bool:
        return self.done and self._future.result() == "aborted"

    def complete(self) -> bool:
        if self.done:
            return False
        try:
            self._future.set_result("completed")
            return True
        except Exception:
            return False

    def abort(self) -> bool:
        if self.done:
            return False
        try:
            self._future.set_result("aborted")
            return True
        except Exception:
            return False

    def add_done_callback(self, callback: Callable[["PlaybackTicket"], Any]) -> None:
        self._future.add_done_callback(lambda _future: callback(self))

    async def wait_async(self) -> str:
        return await asyncio.wrap_future(self._future)


@contextmanager
def delivery_scope(
    *,
    task_id: str,
    kind: str,
    speech_enabled: bool = True,
) -> Iterator[DeliveryScope]:
    """Label synchronous callback speech without global mutable state."""
    label = str(kind or "info").casefold()
    if label not in {"ack", "progress", "final", "confirm", "info"}:
        label = "info"
    scope = DeliveryScope(
        str(task_id or ""),
        label,
        bool(speech_enabled),
    )
    token = _delivery_scope.set(scope)
    try:
        yield scope
    finally:
        _delivery_scope.reset(token)


def current_delivery_scope() -> DeliveryScope | None:
    """Return only the current context-local owner, never shared task state."""
    return _delivery_scope.get()


class SpeechSubmitter:
    """Bind a window speech producer to one current Live instance."""

    def __init__(self, live: Any) -> None:
        self._live_ref = weakref.ref(live)

    def ready(self) -> bool:
        live = self._live_ref()
        return live is not None and lane_idle(live)

    def __call__(self, line: str) -> PlaybackTicket:
        live = self._live_ref()
        ticket = PlaybackTicket()
        if live is None or not lane_idle(live):
            ticket.abort()
            return ticket
        submit(live, line, ticket=ticket)
        return ticket


def _queue_empty(live: Any) -> bool:
    queue = getattr(live, "audio_in_queue", None)
    if queue is None:
        return True
    try:
        return bool(queue.empty())
    except Exception:
        return False


def lane_idle(live: Any) -> bool:
    """Whether a new exact-speech turn may enter the shared Live lane."""
    if getattr(live, "session", None) is None:
        return False
    if bool(getattr(live, "_is_speaking", False)) or not _queue_empty(live):
        return False
    if getattr(live, "_awaiting_since", None) is not None:
        return False
    if bool(getattr(live, "_interrupted", False)):
        return False
    ticket = getattr(live, "_voice_speech_ticket", None)
    return not isinstance(ticket, PlaybackTicket) or ticket.done


def _turn_boundary_open(live: Any) -> bool:
    event = getattr(live, "_turn_done_event", None)
    try:
        return event is not None and bool(event.is_set())
    except Exception:
        return False


def mark_turn_complete(live: Any) -> int:
    """Record one server turn completion without treating it as audible drain."""
    epoch = int(getattr(live, "_voice_turn_boundary_epoch", 0) or 0) + 1
    live._voice_turn_boundary_epoch = epoch
    live._voice_turn_boundary_pending = epoch
    return epoch


def claim_turn_boundary(live: Any) -> bool:
    """Claim the current safe boundary for one direct notice submission.

    The legacy event is level-triggered and remains set for a short time after a
    server turn. A claim makes that level a one-shot capability, so a later
    context-only notice cannot reuse an old drained turn after no new model turn
    has occurred. Immediate submission aborts may release the claim for retry.
    """
    boundary = _sync_turn_boundary(live)
    if not lane_idle(live) or boundary <= 0:
        return False
    if not turn_boundary_safe(live):
        return False
    claimed = int(getattr(live, "_voice_turn_boundary_claimed", 0) or 0)
    if claimed >= boundary:
        return False
    live._voice_turn_boundary_claimed = boundary
    return True


def release_turn_boundary(live: Any, epoch: int | None = None) -> None:
    """Return a claim only when the matching notice submission was aborted."""
    boundary = int(getattr(live, "_voice_turn_boundary_epoch", 0) or 0)
    claimed = int(getattr(live, "_voice_turn_boundary_claimed", 0) or 0)
    if boundary <= 0 or claimed != boundary:
        return
    if epoch is not None and int(epoch) != boundary:
        return
    live._voice_turn_boundary_claimed = 0


def _sync_turn_boundary(live: Any) -> int:
    """Translate the legacy event's rising edge into one durable boundary."""
    event = getattr(live, "_turn_done_event", None)
    identity = id(event) if event is not None else 0
    if int(getattr(live, "_voice_turn_event_id", 0) or 0) != identity:
        live._voice_turn_event_id = identity
        live._voice_turn_event_open = False
        # A reconnect installs a fresh compatibility event. Never let a
        # drained epoch from the previous session make the new lane appear
        # safe before this session has completed its own server turn.
        live._voice_turn_boundary_epoch = 0
        live._voice_turn_boundary_pending = 0
        live._voice_turn_drained_epoch = 0
        live._voice_turn_boundary_claimed = 0
    current = _turn_boundary_open(live)
    was_open = bool(getattr(live, "_voice_turn_event_open", False))
    if current and not was_open:
        mark_turn_complete(live)
    live._voice_turn_event_open = current
    return int(getattr(live, "_voice_turn_boundary_epoch", 0) or 0)


def turn_boundary_safe(live: Any) -> bool:
    """Whether a completed turn is at an authoritative audible-safe boundary.

    Text-only turns are safe once the Live lane is idle while the server boundary
    event remains open.  Turns that produced PCM become safe only after the local
    playback owner records a matching drain; clearing the legacy event at that
    point must not erase the durable boundary.
    """
    boundary = _sync_turn_boundary(live)
    if not lane_idle(live):
        return False
    drained = int(getattr(live, "_voice_turn_drained_epoch", 0) or 0)
    if boundary > 0 and drained >= boundary:
        return True
    return _turn_boundary_open(live)


def notice_lane_idle(live: Any) -> bool:
    """Keep direct notices behind every pending window-owned speech item."""
    if not turn_boundary_safe(live):
        return False
    window = getattr(getattr(live, "ui", None), "_win", None)
    queue = getattr(window, "_speech_queue", None)
    busy = getattr(queue, "busy", None)
    if callable(busy):
        try:
            return not bool(busy())
        except Exception:
            return False
    pending = getattr(queue, "pending", None)
    if not callable(pending):
        return True
    try:
        return int(pending()) == 0
    except Exception:
        return False


def _record_playback_drain(live: Any) -> None:
    """Promote the latest completed server turn to a durable local boundary."""
    boundary = _sync_turn_boundary(live)
    if boundary <= 0 and _turn_boundary_open(live):
        boundary = mark_turn_complete(live)
    if boundary > 0:
        live._voice_turn_drained_epoch = max(
            int(getattr(live, "_voice_turn_drained_epoch", 0) or 0),
            boundary,
        )
        live._voice_turn_boundary_pending = 0


def _prompt(line: str, *, exact: bool = True) -> str:
    if not exact:
        return str(line or "")
    return (
        "Ucapkan kalimat berikut PERSIS seperti tertulis, tanpa tambahan: «"
        + str(line or "")
        + "»"
    )


def _set_ticket(live: Any, ticket: PlaybackTicket | None) -> int:
    epoch = int(getattr(live, "_voice_speech_epoch_counter", 0) or 0) + 1
    live._voice_speech_epoch_counter = epoch
    live._voice_speech_epoch = epoch
    live._voice_speech_ticket = ticket
    live._voice_speech_had_audio = False
    return epoch


def current_playback_epoch(live: Any) -> int:
    """Return the opaque epoch currently owning ticket settlement."""
    return int(getattr(live, "_voice_speech_epoch", 0) or 0)


def active_playback_epoch(live: Any) -> int | None:
    """Return the epoch only while an unsettled speech ticket owns the lane."""
    ticket = getattr(live, "_voice_speech_ticket", None)
    if not isinstance(ticket, PlaybackTicket) or ticket.done:
        return None
    return current_playback_epoch(live)


def _matches_epoch(live: Any, epoch: int | None) -> bool:
    return epoch is None or current_playback_epoch(live) == int(epoch)


def _settle(live: Any, status: str, *, epoch: int | None = None) -> bool:
    if not _matches_epoch(live, epoch):
        return False
    ticket = getattr(live, "_voice_speech_ticket", None)
    if not isinstance(ticket, PlaybackTicket) or ticket.done:
        return False
    changed = ticket.complete() if status == "completed" else ticket.abort()
    if changed:
        live._voice_speech_ticket = None
        live._voice_speech_had_audio = False
    return changed


def mark_audio(live: Any, *, epoch: int | None = None) -> None:
    if not _matches_epoch(live, epoch):
        return
    ticket = getattr(live, "_voice_speech_ticket", None)
    if isinstance(ticket, PlaybackTicket) and not ticket.done:
        live._voice_speech_had_audio = True


def playback_drained(live: Any, *, epoch: int | None = None) -> bool:
    """Record local drain and complete only a matching ticket with written PCM."""
    if not _matches_epoch(live, epoch):
        return False
    _record_playback_drain(live)
    if not bool(getattr(live, "_voice_speech_had_audio", False)):
        return False
    return _settle(live, "completed", epoch=epoch)


def abort(live: Any, *, epoch: int | None = None) -> bool:
    return _settle(live, "aborted", epoch=epoch)


async def _abort_if_silent(
    live_ref,
    ticket: PlaybackTicket,
    epoch: int,
) -> None:
    await asyncio.sleep(_NO_AUDIO_TIMEOUT_S)
    live = live_ref()
    if live is not None and getattr(live, "_voice_speech_ticket", None) is ticket:
        abort(live, epoch=epoch)


def submit(
    live: Any,
    line: str,
    *,
    ticket: PlaybackTicket | None = None,
    exact: bool = True,
    turn_complete: bool = True,
    require_playback: bool = True,
) -> PlaybackTicket:
    ticket = ticket or PlaybackTicket()
    loop = getattr(live, "_loop", None)
    session = getattr(live, "session", None)
    if loop is None or session is None or not loop.is_running():
        ticket.abort()
        return ticket
    active = getattr(live, "_voice_speech_ticket", None)
    if isinstance(active, PlaybackTicket) and not active.done:
        ticket.abort()
        return ticket

    epoch = _set_ticket(live, ticket)

    async def _send() -> None:
        try:
            await asyncio.wait_for(
                session.send_client_content(
                    turns={"parts": [{"text": _prompt(line, exact=exact)}]},
                    turn_complete=bool(turn_complete),
                ),
                timeout=_SEND_TIMEOUT_S,
            )
            if require_playback:
                asyncio.create_task(
                    _abort_if_silent(weakref.ref(live), ticket, epoch)
                )
            else:
                _settle(live, "completed", epoch=epoch)
        except BaseException:
            if getattr(live, "_voice_speech_ticket", None) is ticket:
                abort(live, epoch=epoch)

    try:
        if loop is asyncio.get_running_loop():
            asyncio.create_task(_send())
        else:
            asyncio.run_coroutine_threadsafe(_send(), loop)
    except RuntimeError:
        try:
            asyncio.run_coroutine_threadsafe(_send(), loop)
        except Exception:
            abort(live, epoch=epoch)
    return ticket


def submit_exact(
    live: Any,
    line: str,
    *,
    exact: bool = True,
    turn_complete: bool = True,
    require_playback: bool = True,
) -> PlaybackTicket:
    """Submit one utterance only when the shared Live lane is idle."""
    ticket = PlaybackTicket()
    if not lane_idle(live):
        ticket.abort()
        return ticket
    return submit(
        live,
        line,
        ticket=ticket,
        exact=exact,
        turn_complete=turn_complete,
        require_playback=require_playback,
    )


def bind(window: Any, live: Any) -> SpeechSubmitter:
    submitter = SpeechSubmitter(live)
    window.on_speech_command = submitter
    return submitter


def install(legacy_module) -> bool:
    """Compose scoped callback speech and ticket aborts onto the Live class."""
    live_cls = getattr(legacy_module, "JarvisLive", None)
    if live_cls is None:
        return False
    if getattr(live_cls, _MARKER, False):
        return False

    original_speak = getattr(live_cls, "speak", None)
    if callable(original_speak):
        def speak(self, text, *args, **kwargs):
            scope = _delivery_scope.get()
            if scope is None or not scope.task_id:
                return original_speak(self, text, *args, **kwargs)
            if not scope.speech_enabled:
                return None
            window = getattr(getattr(self, "ui", None), "_win", None)
            queue_line = getattr(window, "_speak_line", None)
            if not callable(queue_line):
                return original_speak(self, text, *args, **kwargs)
            queue_line(
                str(text or ""), kind=scope.kind, turn=scope.task_id
            )
            return None

        speak._jarvis_voice_speech_scope = True
        live_cls.speak = speak

    original_interrupt = getattr(live_cls, "interrupt", None)
    if callable(original_interrupt):
        def interrupt(self, *args, **kwargs):
            try:
                return original_interrupt(self, *args, **kwargs)
            finally:
                abort(self)

        interrupt._jarvis_voice_speech = True
        live_cls.interrupt = interrupt

    setattr(live_cls, _MARKER, True)
    return True


__all__ = [
    "DeliveryScope",
    "PlaybackTicket",
    "SpeechSubmitter",
    "abort",
    "active_playback_epoch",
    "bind",
    "current_delivery_scope",
    "current_playback_epoch",
    "delivery_scope",
    "install",
    "lane_idle",
    "mark_audio",
    "mark_turn_complete",
    "claim_turn_boundary",
    "release_turn_boundary",
    "notice_lane_idle",
    "playback_drained",
    "submit",
    "submit_exact",
    "turn_boundary_safe",
]
