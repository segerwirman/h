"""Pemanasan latar belakang saat boot (Fase 29).

Diukur di proses baru, sebelum model ditanya apa pun:

===========================  ========
tahap                        dingin
===========================  ========
``import llm_client``          235 ms
``client()``                   248 ms
**SDK dibangun**              1577 ms
``all_tools()`` (103 tool)     319 ms
``schemas()`` (94 schema)       49 ms
**total**                     2427 ms
===========================  ========

Semuanya dibayar pada perintah PERTAMA setelah boot, dan seluruhnya sebelum
satu byte pun dikirim ke model. Tidak satu pun bergantung pada isi perintah,
jadi tidak ada alasan menunggu perintah untuk mengerjakannya.

Yang penting di sini adalah apa yang TIDAK dilakukan: pemanasan tidak
memanggil model, tidak menyentuh jaringan, dan tidak pernah melempar ke
pemanggilnya. Satu langkah yang gagal (SDK tanpa kredensial, misalnya) tidak
boleh menghentikan langkah lain — dan tidak boleh menghentikan boot.
"""
from __future__ import annotations

import threading
import time

from jarvis.core import config, log

_logger = log.get("agent.prewarm")

_lock = threading.Lock()
_thread: threading.Thread | None = None


def enabled() -> bool:
    try:
        return bool(config.get("agent.prewarm.enabled", True))
    except Exception:                                        # noqa: BLE001
        return True


def _warm_registry() -> None:
    from jarvis.agent import registry

    registry.all_tools()


def _warm_schemas() -> None:
    from jarvis.agent import registry

    registry.schemas()


def _warm_llm_sdk() -> None:
    """Bangun SDK-nya — konstruktor saja, tanpa satu pun permintaan."""
    from jarvis.agent import llm_client

    llm_client.client()._client()


def default_steps() -> list[tuple]:
    """Urutannya mengikuti ketergantungan: schema butuh registry."""
    return [
        ("registry", _warm_registry),
        ("schemas", _warm_schemas),
        ("llm_sdk", _warm_llm_sdk),
    ]


def _run(steps: list[tuple]) -> None:
    started = time.perf_counter()
    timings: dict = {}
    for name, step in steps:
        mark = time.perf_counter()
        try:
            step()
        except Exception as exc:                             # noqa: BLE001
            # Satu langkah gagal bukan alasan menjatuhkan sisanya. SDK tanpa
            # kredensial adalah keadaan yang sah, bukan kesalahan.
            timings[f"{name}_error"] = str(exc)[:120]
        timings[f"{name}_ms"] = round((time.perf_counter() - mark) * 1000, 1)
    timings["total_ms"] = round((time.perf_counter() - started) * 1000, 1)
    _logger.info("prewarm.done", **timings)


def start(steps=None) -> bool:
    """Panaskan di thread latar. ``False`` bila dimatikan atau sudah jalan."""
    global _thread
    try:
        if not enabled():
            return False
        if not isinstance(steps, (list, tuple)):
            steps = default_steps()
        cleaned = [(str(name), func) for name, func in steps if callable(func)]
        if not cleaned:
            return False
        with _lock:
            if _thread is not None and _thread.is_alive():
                return False
            if _thread is not None:
                return False
            _thread = threading.Thread(target=_run, args=(cleaned,),
                                       name="jarvis-prewarm", daemon=True)
            _thread.start()
        return True
    except Exception as exc:                                 # noqa: BLE001
        _logger.warning("prewarm.failed", error=str(exc)[:120])
        return False


def wait(timeout_s: float = 10.0) -> bool:
    """Tunggu pemanasan selesai. Hanya untuk tes dan diagnostik."""
    thread = _thread
    if thread is None:
        return False
    thread.join(timeout_s)
    return not thread.is_alive()


def reset() -> None:
    """Lupakan pemanasan sebelumnya supaya bisa dijalankan lagi (tes)."""
    global _thread
    with _lock:
        thread = _thread
        _thread = None
    if thread is not None:
        thread.join(2.0)


__all__ = ["default_steps", "enabled", "reset", "start", "wait"]
