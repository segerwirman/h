"""Release the wake-word microphone while Gemini Live owns voice capture."""
from __future__ import annotations

from jarvis.core import log
from jarvis.core.bus import BUS

_logger = log.get("voice.wake_arbitration")

_LIVE_STATES = frozenset({
    "LISTENING",
    "TRANSCRIBING",
    "THINKING",
    "PROCESSING",
    "EXECUTING",
    "SPEAKING",
})
_RELEASED_STATES = frozenset({"IDLE", "OFFLINE", "ERROR", "STOPPED"})


class WakeAudioArbiter:
    """Give exactly one microphone owner to wake capture or Gemini Live."""

    def __init__(self, wake) -> None:                         # noqa: ANN001
        self._wake = wake
        self._paused = False
        self._closed = False

    def on_state(self, data: dict) -> None:
        if self._closed:
            return
        state = str(data.get("state", "")).upper()
        if state in _LIVE_STATES and not self._paused:
            try:
                self._wake.stop()
            except Exception as exc:                         # noqa: BLE001
                _logger.warning(
                    "wake.stream_release_failed",
                    state=state,
                    error=type(exc).__name__,
                )
                return
            self._paused = True
            _logger.info("wake.stream_released_for_live", state=state)
        elif state in _RELEASED_STATES and self._paused:
            try:
                self._wake.start()
            except Exception as exc:                         # noqa: BLE001
                _logger.warning(
                    "wake.stream_restore_failed",
                    state=state,
                    error=type(exc).__name__,
                )
                return
            self._paused = False
            _logger.info("wake.stream_restored_after_live", state=state)

    def close(self) -> None:
        self._closed = True


def install(wake, *, bus=BUS) -> WakeAudioArbiter:            # noqa: ANN001
    arbiter = WakeAudioArbiter(wake)
    bus.subscribe("pipeline.state", arbiter.on_state)
    _logger.info("wake.audio_arbiter.installed")
    return arbiter
