"""Explicit voice-pipeline state machine (Fase 2).

Thread-safe. Every state carries a timeout; a monitor thread forces the
machine back to a safe state (and fires ``on_timeout``) when a stage hangs,
so the pipeline can never silently stick in PROCESSING/SPEAKING forever.

Transitions publish ``pipeline.state`` on the BUS with the previous state,
next state, correlation id, and stage duration — the backbone of end-to-end
tracing for one voice command.
"""
from __future__ import annotations

import threading
import time
import uuid
from enum import Enum
from typing import Callable

from jarvis.core import log
from jarvis.core.bus import BUS

_logger = log.get("pipeline")


class PipelineState(str, Enum):
    IDLE = "IDLE"
    WAKING = "WAKING"
    LISTENING = "LISTENING"
    TRANSCRIBING = "TRANSCRIBING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    ERROR = "ERROR"
    RECOVERING = "RECOVERING"
    SHUTTING_DOWN = "SHUTTING_DOWN"


class Outcome(str, Enum):
    SUCCESS = "success"
    NO_SPEECH = "no_speech"
    UNRECOGNIZED_SPEECH = "unrecognized_speech"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
    TOOL_ERROR = "tool_error"
    NETWORK_ERROR = "network_error"
    TTS_ERROR = "tts_error"
    INTERNAL_ERROR = "internal_error"


# per-state hang timeout (seconds); None = unbounded (IDLE/LISTENING wait for
# the user indefinitely by design)
DEFAULT_TIMEOUTS: dict[PipelineState, float | None] = {
    PipelineState.IDLE: None,
    PipelineState.WAKING: 15.0,
    PipelineState.LISTENING: None,
    PipelineState.TRANSCRIBING: 30.0,
    PipelineState.PROCESSING: 90.0,
    PipelineState.SPEAKING: 120.0,
    PipelineState.ERROR: 10.0,
    PipelineState.RECOVERING: 60.0,
    PipelineState.SHUTTING_DOWN: None,
}

_SAFE_FALLBACK = {
    PipelineState.WAKING: PipelineState.IDLE,
    PipelineState.TRANSCRIBING: PipelineState.LISTENING,
    PipelineState.PROCESSING: PipelineState.LISTENING,
    PipelineState.SPEAKING: PipelineState.LISTENING,
    PipelineState.ERROR: PipelineState.RECOVERING,
    PipelineState.RECOVERING: PipelineState.IDLE,
}


def new_request_id() -> str:
    return uuid.uuid4().hex[:8]


class PipelineStateMachine:
    """Single active command at a time; observers get every transition."""

    def __init__(self,
                 timeouts: dict[PipelineState, float | None] | None = None,
                 on_timeout: Callable[[PipelineState, str], None] | None = None,
                 monitor_interval: float = 1.0):
        self._lock = threading.Lock()
        self._state = PipelineState.IDLE
        self._since = time.monotonic()
        self._request_id: str = ""
        self._timeouts = dict(DEFAULT_TIMEOUTS)
        if timeouts:
            self._timeouts.update(timeouts)
        self._on_timeout = on_timeout
        self._monitor_interval = monitor_interval
        self._stop = threading.Event()
        self._monitor: threading.Thread | None = None

    # ── properties ───────────────────────────────────────────────────────────
    @property
    def state(self) -> PipelineState:
        with self._lock:
            return self._state

    @property
    def request_id(self) -> str:
        with self._lock:
            return self._request_id

    def busy(self) -> bool:
        return self.state in (PipelineState.TRANSCRIBING,
                              PipelineState.PROCESSING,
                              PipelineState.SPEAKING,
                              PipelineState.WAKING)

    # ── transitions ──────────────────────────────────────────────────────────
    def begin_request(self) -> str:
        """New correlation id for one voice command.

        Fase 42/50 — titik ini juga membuka rentang gelap ``voice_ack``
        (akhir ucapan → task masuk dispatch). ``main.py:1509`` memanggilnya
        tepat di dalam ``if not in_buf:``, yaitu chunk pertama sebuah ucapan.

        Mengapa di sini, bukan di ``_voice_intercept``: ``latency.mark()``
        menyimpan selang sejak penanda terakhir (``latency.py:93``), sehingga
        ``start`` yang dipanggil sesudah transkrip final tiba membuat
        ``speech_end_ms`` selalu ``0.0`` — anomali yang tercatat sejak
        2026-08-19 tanpa penjelasan. Terukur pula bahwa ``start`` kedua
        mengganti turn yang berjalan dan **menghapus** ``speech_end``.

        Mengapa di sini, bukan di ``main.py``: berkas itu ada dalam
        ``config/frozen_manifest.json``. ``state.py`` tidak.

        Pengukur tidak pernah boleh menjatuhkan giliran — kegagalan di sini
        ditelan dan dicatat, bukan dibiarkan merambat.
        """
        rid = new_request_id()
        with self._lock:
            self._request_id = rid
        try:
            from jarvis.core import latency, quiet
        except Exception:                                        # noqa: BLE001
            return rid          # pengukur tidak pernah menjatuhkan giliran
        try:
            latency.start("voice_ack", task=f"voice:{rid}")
        except Exception as exc:                                 # noqa: BLE001
            quiet.swallowed("latency.voice_ack_open_failed", exc)
        return rid

    def _cancel_voice_ack_turn(self) -> None:
        """Buang turn ``voice_ack`` yang tidak pernah mencapai dispatch.

        Mengapa dibuang, bukan di-``finish``: ``finish`` selalu menerbitkan
        satu baris ``latency.turn``. Turn yang tidak pernah di-dispatch bukan
        pengukuran, jadi ia tidak boleh menghasilkan baris log sama sekali.

        Mengapa tidak digabung ke ``begin_request``: pembatalan harus terjadi
        pada AKHIR giliran, bukan awal. Di awal tidak ada yang tahu apakah
        giliran ini kelak mencapai dispatch.

        Seperti ``begin_request``, pengukur tidak pernah boleh menjatuhkan
        giliran — kegagalan di sini ditelan dan dicatat.
        """
        try:
            from jarvis.core import latency, quiet
        except Exception:                                        # noqa: BLE001
            return              # pengukur tidak pernah menjatuhkan giliran
        try:
            latency.cancel("voice_ack")
        except Exception as exc:                                 # noqa: BLE001
            quiet.swallowed("latency.voice_ack_cancel_failed", exc)

    def to(self, state: PipelineState, outcome: Outcome | None = None,
           detail: str = "") -> None:
        with self._lock:
            prev = self._state
            if prev is state:
                return
            elapsed = time.monotonic() - self._since
            self._state = state
            self._since = time.monotonic()
            rid = self._request_id
        _logger.info("pipeline.transition", request_id=rid,
                     prev=prev.value, next=state.value,
                     stage_s=round(elapsed, 2),
                     outcome=outcome.value if outcome else None,
                     detail=detail[:120] if detail else None)
        BUS.publish("pipeline.state", prev=prev.value, state=state.value,
                    request_id=rid, stage_s=round(elapsed, 2),
                    outcome=outcome.value if outcome else None)

    def finish(self, outcome: Outcome, detail: str = "") -> None:
        """End the active command with an explicit outcome, back to LISTENING.

        Fase 52 — akhir giliran juga MEMBATALKAN turn ``voice_ack`` bila ia
        tidak pernah mencapai dispatch. Sebelumnya turn itu dibiarkan terbuka
        dan ditutup oleh ``voice_handoff()`` berikutnya — terukur 2026-09-01
        menghasilkan ``total_ms: 10800000.0`` berlabel ``voice:...`` untuk
        sebuah dispatch Telegram tiga jam kemudian.

        Bila dispatch sudah menutup turn lebih dulu (jalur normal), ``cancel``
        menjadi no-op. Jadi pemanggilan ini aman di kedua urutan.

        Alasan ia ada di sini, bukan di pemanggil: ``main.py:1612`` hanya
        memanggil ``finish()`` bila ``outcome == "success"``, sedangkan
        ``unrecognized_speech`` tidak memanggilnya sama sekali. Menaruh
        pembatalan di dalam ``finish()`` membuatnya berlaku untuk SETIAP
        outcome, bukan hanya yang kebetulan dipanggil pemanggilnya.
        """
        self._cancel_voice_ack_turn()
        _logger.info("pipeline.outcome", request_id=self.request_id,
                     outcome=outcome.value, detail=detail[:160])
        BUS.publish("pipeline.outcome", request_id=self.request_id,
                    outcome=outcome.value, detail=detail[:160])
        self.to(PipelineState.LISTENING, outcome=outcome, detail=detail)

    # ── watchdog ─────────────────────────────────────────────────────────────
    def start_monitor(self) -> None:
        if self._monitor is not None:
            return
        self._stop.clear()
        self._monitor = threading.Thread(target=self._watch, daemon=True,
                                         name="pipeline-watchdog")
        self._monitor.start()

    def stop_monitor(self) -> None:
        self._stop.set()
        if self._monitor is not None:
            self._monitor.join(timeout=2.0)
            self._monitor = None

    def _watch(self) -> None:
        while not self._stop.wait(self._monitor_interval):
            with self._lock:
                state = self._state
                elapsed = time.monotonic() - self._since
                rid = self._request_id
            limit = self._timeouts.get(state)
            if limit is None or elapsed <= limit:
                continue
            fallback = _SAFE_FALLBACK.get(state, PipelineState.IDLE)
            _logger.warning("pipeline.stage_timeout", request_id=rid,
                            state=state.value, elapsed_s=round(elapsed, 1),
                            fallback=fallback.value)
            self.to(fallback, outcome=Outcome.TIMEOUT,
                    detail=f"stage {state.value} exceeded {limit}s")
            if self._on_timeout is not None:
                try:
                    self._on_timeout(state, rid)
                except Exception as e:
                    _logger.error("pipeline.on_timeout_failed",
                                  error=str(e)[:120])
