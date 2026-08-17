"""Mic stream controller for the legacy JarvisUI facade."""
from __future__ import annotations

import queue
import time

from jarvis.core import log, quiet

_logger = log.get("ui")


def _playback_level(win) -> float:
    """Measure current Jarvis playback level, with a safe echo fallback."""
    explicit = getattr(win, "_playback_level", None)
    if explicit is not None:
        return max(0.0, min(1.0, float(explicit)))
    try:
        tap = __import__(
            "jarvis.integrations.voice_playback_level",
            fromlist=["voice_playback_level"],
        )

        if not tap.is_installed():
            return 1.0
        return max(0.0, min(1.0, float(tap.current_level())))
    except Exception:                                        # noqa: BLE001
        return 1.0


class MicMeterController:
    """Consume frames from the Gemini Live microphone owner."""

    def __init__(self, win, stop_event):
        self._win = win
        self._stop_event = stop_event

    def _publish_interrupt(self, verdict, *, detected_at: float) -> None:
        """Queue a typed microphone event; never execute ESC from PortAudio."""
        from jarvis.integrations import voice_interrupt

        event, reason = voice_interrupt.build_microphone_event(
            self._win, verdict, detected_at=detected_at
        )
        fields = {
            "reason": reason,
            "rms": round(float(verdict.rms), 3),
            "threshold": round(float(verdict.threshold), 3),
            "noise_floor": round(float(verdict.noise_floor), 4),
        }
        if event is None:
            _logger.info("voice.barge_in_suppressed", **fields)
            return
        _logger.info(
            "voice.barge_in_candidate",
            playback_generation=event.playback_generation,
            playback_epoch=event.playback_epoch,
            capture_generation=event.capture_generation,
            **fields,
        )
        signal = getattr(self._win, "_voice_interrupt_sig", None)
        emit = getattr(signal, "emit", None)
        if callable(emit):
            emit(event)

    def run(self) -> None:
        # §19 — keputusan interupsi pindah ke jarvis/core/barge_in.py:
        # noise floor adaptif, pembeda suara-vs-transien, dan echo guard yang
        # berlaku SEPANJANG ucapan. Gerbang RMS ambang tetap 0.14 yang lama
        # itulah yang membuat barge-in harus dimatikan sejak awal.
        from jarvis.core.barge_in import BargeInAnalyzer, BargeInConfig

        analyzer = BargeInAnalyzer(BargeInConfig.from_config())
        analyzer.start_calibration(time.monotonic())
        # §30 — stream yang sama sudah memegang seluruh audio mic, jadi
        # pengenalan penutur tidak perlu membuka jalur audio kedua.
        from jarvis.core import speaker_id
        speaker_listener = speaker_id.Listener(16000)

        try:
            import numpy as np
            from jarvis.integrations.voice_input_owner import frame_hub

            frames = frame_hub(self._win)
            _logger.info("mic_meter.started", **analyzer.diagnostics())
            _logger.info("speaker_id.started", **speaker_id.diagnostics())
            while not self._stop_event.is_set():
                try:
                    frame = frames.get(timeout=0.2)
                except queue.Empty:
                    continue
                if frame.generation != int(
                    getattr(self._win, "_voice_capture_generation", 0) or 0
                ):
                    continue
                indata = np.frombuffer(frame.pcm, dtype=np.int16).astype(
                    np.float32
                ) / 32768.0
                if not indata.size:
                    continue
                state = self._win._legacy_state
                rms = float(np.sqrt(np.mean(indata ** 2)))
                speaking = state == "SPEAKING"
                level = min(1.0, rms * 12) if state == "LISTENING" else 0.0
                if speaking:
                    level = max(level, min(1.0, _playback_level(self._win)))
                signal = getattr(self._win, "_mic_level_sig", None)
                emit = getattr(signal, "emit", None)
                if callable(emit):
                    emit(level)

                if self._win._muted:
                    continue
                verdict = analyzer.process_block(
                    indata,
                    frame.captured_at,
                    speaking=speaking,
                    speaking_since=getattr(self._win, "_speaking_since", 0.0),
                    playback_level=_playback_level(self._win),
                )
                try:
                    who = speaker_listener.feed(
                        indata, listening=(state == "LISTENING"))
                    if who is not None and who.blocked:
                        self._win.write_log(
                            "SYS: Suara tidak dikenali — perintah diabaikan "
                            f"(skor {who.score:.2f} < {who.threshold:.2f}).")
                except Exception as exc:                     # noqa: BLE001
                    quiet.swallowed("ui.mic_meter.feed_failed", exc)

                if verdict.interrupt:
                    self._publish_interrupt(
                        verdict, detected_at=frame.captured_at
                    )
        except Exception as e:
            _logger.warning("mic_meter.unavailable", error=str(e)[:100])
