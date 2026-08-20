"""Deprecated async Hermes dispatcher, retained for import compatibility.

Kontrak latency: pemanggil mendapat kontrol kembali dalam <1 ms. Suara
TIDAK pernah menunggu Hermes. Alur:

  1. speak(ack) langsung (mis. "Baik, sedang saya kerjakan.")
  2. Worker thread menjalankan HermesBridge.run_task()
  3. Selesai → BUS.publish("hermes.task.done"/"hermes.task.failed")
     dan on_done(text) dipanggil (biasanya → TTS + tulis log UI)

Dengan default MK50 ``hermes.enabled: false``, fungsi berhenti sebelum bridge
dibuat atau thread di-spawn. Dedup guard legacy tetap tersedia hanya untuk
opt-in eksplisit selama masa migrasi.
"""
from __future__ import annotations

import threading
import time

from jarvis.core import log
from jarvis.core.bus import BUS
from jarvis.integrations.hermes.bridge import HermesBridge, is_enabled

_logger = log.get("hermes.async")

_active_lock = threading.Lock()
_active: dict[str, float] = {}          # task-key → started_at


def _key(task: str) -> str:
    return " ".join(task.lower().split())[:160]


def active_count() -> int:
    with _active_lock:
        return len(_active)


def dispatch_async(task: str,
                   on_ack=None,
                   on_done=None,
                   on_error=None,
                   timeout_s: float | None = None) -> bool:
    """Mulai task Hermes di background. Return False bila Hermes tidak
    tersedia ATAU task yang sama masih berjalan (caller harus fallback /
    beri tahu user). Semua callback opsional dan dipanggil dari worker
    thread — marshal ke UI thread adalah tanggung jawab caller.
    """
    if not is_enabled():
        _logger.info("hermes.async.disabled")
        return False

    bridge = HermesBridge.get()
    if not bridge.available():
        _logger.warning("hermes.async.unavailable", task=task[:80])
        return False

    k = _key(task)
    with _active_lock:
        if k in _active:
            _logger.info("hermes.async.duplicate", task=task[:80])
            return False
        _active[k] = time.monotonic()

    ack = "Baik, sedang saya kerjakan."
    if on_ack:
        try:
            on_ack(ack)
        except Exception as exc:                             # noqa: BLE001
            from jarvis.core import quiet
            quiet.swallowed(
                "integrations.hermes.async_dispatch.ack_callback_failed",
                exc,
            )
    BUS.publish("hermes.task.started", task=task)

    def _worker():
        t0 = time.monotonic()
        try:
            r = bridge.run_task(task, timeout_s=timeout_s)
            elapsed = round(time.monotonic() - t0, 1)
            if r["ok"]:
                text = r["stdout"].strip() or "Selesai."
                _logger.info("hermes.async.done", elapsed_s=elapsed,
                             chars=len(text))
                BUS.publish("hermes.task.done", task=task, text=text,
                            elapsed_s=elapsed)
                if on_done:
                    on_done(text)
            else:
                err = r.get("error") or r["stderr"][:200] or "unknown error"
                _logger.error("hermes.async.failed", elapsed_s=elapsed,
                              error=err[:120])
                BUS.publish("hermes.task.failed", task=task, error=err,
                            elapsed_s=elapsed)
                if on_error:
                    on_error(err)
        finally:
            with _active_lock:
                _active.pop(k, None)

    threading.Thread(target=_worker, daemon=True,
                     name="hermes-task").start()
    return True
