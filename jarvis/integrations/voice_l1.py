"""PROMPT M — L1 voice hook yang fail-open di atas loop Gemini Live.

Modul ini tidak membaca mikrofon atau mengubah loop audio. Ia menerima transcript
final dari satu hook kecil pada legacy ``main.py``; jika tidak yakin/terlambat,
seluruh control kembali ke alur Gemini lama.
"""
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from typing import Any

from jarvis.core import config, log
from jarvis.core.action_registry import Action
from jarvis.core.resolver import FallthroughToLLM, Resolution, resolve
from jarvis.integrations import local_action_executor, voice_proposal_install

_logger = log.get("voice.l1")
Resolver = Callable[..., Resolution]
Submitter = Callable[[Action, Any], Awaitable[str]]
_can_execute = local_action_executor.can_execute
_submit_default = local_action_executor.submit


def _event(name: str, **data: Any) -> None:
    """Telemetry aman: tipe/latensi saja, tidak pernah transcript."""
    _logger.info(name, **data)


def _enabled() -> bool:
    return bool(config.get("routing.voice_l1_hook.enabled", False))


def _timeout_s() -> float:
    raw = config.get("routing.voice_l1_hook.timeout_ms", 50)
    try:
        return max(0.001, float(raw) / 1000.0)
    except (TypeError, ValueError):
        return 0.05


def _mark_pending(live: Any, lane: str, started: float) -> None:
    pending = getattr(live, "_voice_l1_pending_audio", None)
    if not isinstance(pending, dict):
        pending = {}
        setattr(live, "_voice_l1_pending_audio", pending)
    pending[lane] = started


def _has_output(live: Any) -> bool:
    if bool(getattr(live, "_is_speaking", False)):
        return True
    queue = getattr(live, "audio_in_queue", None)
    try:
        return queue is not None and not queue.empty()
    except Exception:  # noqa: BLE001 - optional legacy queue implementation
        return False


class VoiceL1Hook:
    """Resolve satu transcript final secara konservatif atau return ``False``."""

    def __init__(self, *, resolver: Resolver = resolve,
                 submit: Submitter = _submit_default,
                 timeout_s: float | None = None) -> None:
        self._resolver = resolver
        self._submit = submit
        self._timeout_s = _timeout_s() if timeout_s is None else timeout_s

    async def __call__(self, live: Any, turn: Any) -> bool:
        text = str(getattr(turn, "text", turn) or "")
        started = time.monotonic()
        try:
            outcome = await asyncio.wait_for(
                asyncio.to_thread(self._resolver, text, source="voice"),
                timeout=self._timeout_s,
            )
        except asyncio.TimeoutError:
            _event("voice.l1.fall_open", reason="resolver_timeout")
            _mark_pending(live, "L2", started)
            return False
        except Exception as exc:  # noqa: BLE001 - required fail-open boundary
            _logger.warning("voice.l1.fall_open", reason="resolver_error",
                            error=type(exc).__name__)
            _mark_pending(live, "L2", started)
            return False

        if not isinstance(outcome, Action) or not _can_execute(outcome):
            reason = outcome.reason if isinstance(outcome, FallthroughToLLM) else "unsupported_action"
            _event("voice.l1.fall_open", reason=reason)
            _mark_pending(live, "L2", started)
            return False

        # Gemini may already have emitted an audio chunk before final STT. The
        # legacy interrupt drains it and marks that old turn as interrupted.
        if _has_output(live):
            try:
                live.interrupt()
                _event("voice.l1.interrupt_prior_output")
            except Exception as exc:  # noqa: BLE001 - fail open is safer
                _logger.warning("voice.l1.fall_open", reason="interrupt_error",
                                error=type(exc).__name__)
                _mark_pending(live, "L2", started)
                return False

        try:
            confirmation = await self._submit(outcome, live)
            live.speak(confirmation)
        except Exception as exc:  # noqa: BLE001 - no local action should kill loop
            _logger.warning("voice.l1.fall_open", reason="submit_error",
                            error=type(exc).__name__)
            _mark_pending(live, "L2", started)
            return False

        reset = getattr(turn, "reset", None)
        if callable(reset):
            reset()
        _mark_pending(live, "L1", started)
        _event("voice.l1.handled", kind=outcome.kind, target=outcome.target)
        return True


def _install_meter(legacy: Any) -> None:
    cls = getattr(legacy, "JarvisLive", None)
    if cls is None or getattr(cls, "_jarvis_voice_l1_meter", False):
        return
    original = getattr(cls, "set_speaking", None)
    if not callable(original):
        return

    def measured_set_speaking(self, value: bool):
        was_speaking = bool(getattr(self, "_voice_l1_meter_speaking", False))
        result = original(self, value)
        now_speaking = bool(value)
        self._voice_l1_meter_speaking = now_speaking
        if now_speaking and not was_speaking:
            pending = getattr(self, "_voice_l1_pending_audio", None)
            if isinstance(pending, dict) and pending:
                lane, started = next(iter(pending.items()))
                pending.clear()
                _event("voice.first_audio", lane=lane, metric="first_audio_ms",
                       value_ms=round((time.monotonic() - float(started)) * 1000, 1))
        return result

    cls.set_speaking = measured_set_speaking
    cls._jarvis_voice_l1_meter = True


def install(legacy: Any) -> bool:
    """Compose opt-in L1/proposal hooks; both-off is a true no-op."""
    l1_enabled = _enabled()
    current = getattr(legacy, "VOICE_L1_HOOK", None)
    hook = VoiceL1Hook() if l1_enabled and current is None else current
    hook = voice_proposal_install.compose(hook)
    if hook is not current:
        legacy.VOICE_L1_HOOK = hook
    if l1_enabled:
        _install_meter(legacy)
    return bool(
        l1_enabled or getattr(hook, "_jarvis_voice_proposal_hook", False)
    )


__all__ = ["VoiceL1Hook", "install"]
