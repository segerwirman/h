"""Process-local, human-only CAPTCHA handoff for semantic Screen Control.

This module owns no durable queue. It keeps one opaque continuation while the
existing TaskRegistry owns lifecycle and Screen Control owns desktop authority.
"""
from __future__ import annotations

import asyncio
import math
import threading
import time
from dataclasses import dataclass, field

from jarvis.agent.tasks import REGISTRY, TaskStatus
from jarvis.core import config, log
from jarvis.core.bus import BUS
from jarvis.ui.screen_control import COORDINATOR

_logger = log.get("agent.captcha_handoff")
_COMPLETION_TEXT = "captcha selesai"
_DEFAULT_TIMEOUT_S = 600.0
_MIN_TIMEOUT_S = 10.0
_MAX_TIMEOUT_S = 1800.0


@dataclass
class CaptchaHandoffRequest:
    """Opaque process-local continuation; never serialized or model-visible."""

    session_id: str
    task_id: str
    authority: object = field(repr=False)
    token: object = field(default_factory=object, repr=False)
    completed: threading.Event = field(default_factory=threading.Event, repr=False)
    expires_at: float = field(default=0.0, repr=False)
    state: str = field(default="staged", repr=False)


class CaptchaHandoffOwner:
    """Own at most one live handoff because Screen Control owns one desktop."""

    def __init__(self, *, clock=time.monotonic, bus=BUS, subscribe=False) -> None:
        self._clock = clock
        self._bus = bus
        self._lock = threading.RLock()
        self._request: CaptchaHandoffRequest | None = None
        if subscribe:
            self._subscribe()

    def _subscribe(self) -> None:
        for topic in (
            "agent.tasks.cancel_all",
            "emergency.stop",
            "window.closing",
            "application.shutdown",
        ):
            self._bus.subscribe(
                topic,
                lambda _data, reason=topic: self.cancel_all(reason),
            )
        self._bus.subscribe("task.finished", self._on_task_finished)
        self._bus.subscribe(
            "screen_control.changed",
            self._on_screen_control_changed,
        )

    def stage(self, *, session_id: str, task_id: str, authority) -> CaptchaHandoffRequest:
        """Revoke all session refs and stage one exact live task continuation."""
        session = str(session_id or "").strip()
        task = str(task_id or "").strip()
        if not session or not task or authority is None:
            raise RuntimeError("captcha_handoff_binding_invalid")
        clear_session = getattr(authority, "clear_session", None)
        if callable(clear_session):
            clear_session(session)
        request = CaptchaHandoffRequest(
            session_id=session,
            task_id=task,
            authority=authority,
            expires_at=self._clock() + _timeout_s(),
        )
        with self._lock:
            current = self._request
            if current is not None:
                if (
                    current.session_id == session
                    and current.task_id == task
                    and current.state in {"staged", "waiting", "resuming"}
                ):
                    return current
                raise RuntimeError("captcha_handoff_already_active")
            self._request = request
        return request

    def complete_local(self, text: str) -> bool:
        """Accept only the exact local phrase for the one exact WAITING task."""
        if str(text or "").strip().casefold() != _COMPLETION_TEXT:
            return False
        with self._lock:
            request = self._request
            if request is None or request.state != "waiting":
                return False
            view = REGISTRY.get(request.task_id)
            if (
                view is None
                or _status_value(getattr(view, "status", None))
                != TaskStatus.WAITING.value
                or bool(getattr(view, "cancelled", False))
            ):
                return False
            request.completed.set()
            return True

    async def suspend_if_staged(self, session, bg_task) -> str | None:
        """Suspend after loop resource release, then validate a fresh observation."""
        request = self._matching(session, bg_task)
        if request is None:
            return None
        if not self._begin_wait(request):
            self._cancel(request, "handoff_start_failed")
            return "cancelled"
        while True:
            outcome = await self._wait_for_completion(request, bg_task)
            if outcome != "completed":
                self._cancel(request, outcome)
                return "cancelled"
            resumed = await self._resume_and_validate(request, bg_task)
            if resumed == "waiting":
                continue
            return resumed

    async def resume_for_test(self, request: CaptchaHandoffRequest, *, bg_task) -> str:
        """Narrow offline seam for lifecycle tests; production uses suspend_if_staged."""
        return await self._resume_and_validate(request, bg_task)

    def clear_session(self, session_id: str, reason: str = "task_terminal") -> bool:
        owner = str(session_id or "").strip()
        with self._lock:
            request = self._request
            if request is None or request.session_id != owner:
                return False
        self._cancel(request, reason)
        return True

    def cancel_all(self, reason: str = "cancelled") -> bool:
        with self._lock:
            request = self._request
        if request is None:
            return False
        self._cancel(request, reason)
        return True

    def _matching(self, session, bg_task) -> CaptchaHandoffRequest | None:
        session_id = str(getattr(session, "id", "") or "")
        task_id = str(getattr(session, "registry_task_id", "") or "")
        bg_id = str(getattr(bg_task, "id", "") or "")
        with self._lock:
            request = self._request
            if (
                request is None
                or request.state != "staged"
                or request.session_id != session_id
                or request.task_id != task_id
                or request.task_id != bg_id
            ):
                return None
            return request

    def _begin_wait(self, request: CaptchaHandoffRequest) -> bool:
        if not REGISTRY.register_wait_continuation(request.task_id, request.token):
            return False
        if not COORDINATOR.begin_handoff(request.task_id):
            REGISTRY.clear_wait_continuation(request.task_id, request.token)
            return False
        if not REGISTRY.begin_wait(request.task_id, "captcha_handoff"):
            COORDINATOR.release_task(request.task_id, "handoff_wait_failed")
            REGISTRY.clear_wait_continuation(request.task_id, request.token)
            return False
        request.state = "waiting"
        self._publish_required()
        return True

    async def _wait_for_completion(self, request: CaptchaHandoffRequest, bg_task) -> str:
        """Bounded async polling leaves no detached event-wait worker thread."""
        while True:
            if request.completed.is_set():
                return "completed"
            if self._clock() >= request.expires_at:
                return "timeout"
            if _cancelled(bg_task):
                return "cancelled"
            with self._lock:
                if self._request is not request:
                    return "missing_continuation"
            view = REGISTRY.get(request.task_id)
            if (
                view is None
                or _status_value(getattr(view, "status", None))
                != TaskStatus.WAITING.value
                or bool(getattr(view, "cancelled", False))
            ):
                return "task_not_waiting"
            await asyncio.sleep(0.05)

    async def _resume_and_validate(self, request: CaptchaHandoffRequest, bg_task) -> str:
        if not REGISTRY.resume_wait(request.task_id, request.token):
            self._cancel(request, "resume_wait_failed")
            return "cancelled"
        request.state = "resuming"
        request.completed.clear()
        if not COORDINATOR.resume_handoff(request.task_id):
            self._cancel(request, "screen_control_resume_failed")
            return "cancelled"

        held = await self._acquire_desktop(request, bg_task)
        if held is None:
            self._cancel(request, "desktop_reacquire_failed")
            return "cancelled"
        try:
            observation = await asyncio.to_thread(
                request.authority.observe_for,
                request.session_id,
            )
            decision = request.authority.gate.classify_observation(observation)
        except Exception:
            self._cancel(request, "fresh_observation_failed")
            return "cancelled"
        finally:
            try:
                request.authority.clear_session(request.session_id)
            except Exception as exc:
                _logger.warning(
                    "captcha_handoff.fresh_ref_cleanup_failed",
                    error=type(exc).__name__,
                )
            if held:
                REGISTRY.release_held(held)

        if not decision.allowed:
            if not COORDINATOR.begin_handoff(request.task_id):
                self._cancel(request, "repeat_handoff_failed")
                return "cancelled"
            if not REGISTRY.begin_wait(request.task_id, "captcha_handoff"):
                self._cancel(request, "repeat_wait_failed")
                return "cancelled"
            request.state = "waiting"
            self._publish_required()
            return "waiting"

        REGISTRY.clear_wait_continuation(request.task_id, request.token)
        request.state = "resumed"
        self._retire(request)
        return "resumed"

    async def _acquire_desktop(self, request: CaptchaHandoffRequest, bg_task):
        while self._clock() < request.expires_at:
            if _cancelled(bg_task):
                return None
            got = REGISTRY.try_acquire(bg_task, {"desktop"})
            if got is not None:
                return got
            await asyncio.sleep(0.02)
        return None

    def _cancel(self, request: CaptchaHandoffRequest, reason: str) -> None:
        with self._lock:
            if self._request is not request:
                return
            self._request = None
            request.state = "cancelled"
            request.completed.set()
        try:
            request.authority.clear_session(request.session_id)
        except Exception as exc:
            _logger.warning(
                "captcha_handoff.cancel_ref_cleanup_failed",
                error=type(exc).__name__,
            )
        REGISTRY.clear_wait_continuation(request.task_id, request.token)
        REGISTRY.cancel(request.task_id)
        COORDINATOR.release_task(request.task_id, str(reason or "cancelled")[:64])

    def _retire(self, request: CaptchaHandoffRequest) -> None:
        with self._lock:
            if self._request is request:
                self._request = None

    def _publish_required(self) -> None:
        self._bus.publish(
            "captcha.handoff.required",
            title="CAPTCHA memerlukan tindakan",
            body=(
                "Selesaikan CAPTCHA secara manual, lalu ketik "
                "‘CAPTCHA selesai’ di aplikasi lokal."
            ),
        )

    def _on_task_finished(self, data: dict) -> None:
        task = data.get("task") or {}
        task_id = str(task.get("id", "") if isinstance(task, dict) else "")
        with self._lock:
            request = self._request
        if request is not None and request.task_id == task_id:
            self._cancel(request, "task_terminal")

    def _on_screen_control_changed(self, data: dict) -> None:
        if str(data.get("state", "") or "").casefold() != "off":
            return
        reason = str(data.get("reason", "") or "").casefold()
        if reason != "expired":
            return
        with self._lock:
            request = self._request
        if request is not None and request.state in {"staged", "waiting", "resuming"}:
            self._cancel(request, "screen_control_expired")


def _status_value(status) -> str:
    return str(getattr(status, "value", status) or "").casefold()


def _cancelled(bg_task) -> bool:
    try:
        return bg_task is not None and bg_task.cancel.is_set()
    except Exception:
        return False


def _timeout_s() -> float:
    try:
        value = float(config.get("screen_control.captcha_handoff_timeout_s", _DEFAULT_TIMEOUT_S))
    except (TypeError, ValueError):
        value = _DEFAULT_TIMEOUT_S
    if not math.isfinite(value):
        value = _DEFAULT_TIMEOUT_S
    return min(_MAX_TIMEOUT_S, max(_MIN_TIMEOUT_S, value))


OWNER = CaptchaHandoffOwner(subscribe=True)


__all__ = [
    "CaptchaHandoffOwner",
    "CaptchaHandoffRequest",
    "OWNER",
]
