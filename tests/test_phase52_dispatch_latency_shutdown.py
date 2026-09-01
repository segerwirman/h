"""Fase 53 — penutup turn ``session.id`` dan eviction yang sadar progres.

Audit seluruh titik ``latency.finish()`` sesudah Fase 52 menemukan dua cacat
terukur pada 2026-09-01:

1. ``dispatch`` membuka turn sebelum worker, tetapi jalur task yang dibatalkan
   saat mengantre keluar sebelum ``try/finally``. Terukur sesudah worker
   terminal: ``active_count == 1`` dan turn ``session.id`` masih terbuka.
2. Saat batas 64 tercapai, eviction selalu membuang turn tertua. Sebuah turn
   sah yang sudah memiliki penanda ``first_llm`` dapat dibuang oleh turn bocor
   tanpa progres; ``finish()`` lalu mengembalikan ``{}`` tanpa jejak.

Tes dispatch di bawah menjalankan jalur worker dengan registry offline palsu;
ia menguji keadaan akhir, bukan mencari potongan teks sumber. Semua dependency
browser/desktop tetap fake/no-op dan tidak ada Chrome atau input live.
"""
from __future__ import annotations

import threading
import time

import pytest

from jarvis.agent import dispatch
from jarvis.core import latency


class _Task:
    def __init__(self, task_id: str = "T-latency") -> None:
        self.id = task_id
        self.title = "offline latency shutdown"
        self.cancel = threading.Event()


class _Registry:
    def __init__(self, *, acquire: bool) -> None:
        self.task = _Task()
        self.acquire = acquire
        self.session_id = ""
        self.finished = threading.Event()
        self.marked_running = threading.Event()
        self.released = threading.Event()

    def submit(self, *_args, **_kwargs):
        return self.task

    def update(self, _task_id, **fields):
        self.session_id = str(fields.get("session_id", ""))

    def acquire_slot(self, _task):
        return self.acquire

    def mark_running(self, _task_id):
        self.marked_running.set()
        return None

    def release_slot(self, _task):
        self.released.set()

    def finish(self, *_args, **_kwargs):
        self.finished.set()
        return None


def _wait_until(predicate, timeout: float = 2.0) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


def _isolate_dispatch(monkeypatch, registry: _Registry) -> None:
    async def no_replay(*_args, **_kwargs):
        return None

    async def unexpected_run(*_args, **_kwargs):
        raise AssertionError("jalur cancel offline tidak boleh menjalankan agent")

    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(dispatch, "_replay_plan", no_replay)
    monkeypatch.setattr("jarvis.agent.loop.run", unexpected_run)
    monkeypatch.setattr("jarvis.agent.communication_mode.active", lambda: False)
    monkeypatch.setattr("jarvis.agent.tasks.REGISTRY", registry)
    monkeypatch.setattr("jarvis.agent.ack_composer.compose_ack", lambda _task: "ACK")
    monkeypatch.setattr(
        "jarvis.agent.local_run_capabilities.mint_selected_tab_overlay",
        lambda **_kwargs: None,
    )
    monkeypatch.setattr(dispatch.BUS, "publish", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(dispatch, "_release_browser_session", lambda _sid: None)
    monkeypatch.setattr(dispatch, "_release_computer_session", lambda _sid: None)
    monkeypatch.setattr(dispatch, "_clear_desktop_safe_session", lambda _sid: None)
    monkeypatch.setattr(dispatch, "_clear_captcha_handoff_session", lambda _sid: None)
    monkeypatch.setattr(dispatch, "_release_screen_control_session", lambda _sid: None)
    monkeypatch.setattr(dispatch, "_revoke_execution_grants", lambda _tid: None)
    with dispatch._active_lock:
        dispatch._active.clear()


@pytest.fixture(autouse=True)
def _clean_state():
    latency.reset()
    with dispatch._active_lock:
        dispatch._active.clear()
    yield
    assert _wait_until(lambda: dispatch.active_count() == 0)
    latency.reset()
    with dispatch._active_lock:
        dispatch._active.clear()


def test_cancel_saat_mengantre_menutup_turn_session(monkeypatch):
    """Worker terminal sebelum RUNNING tetap harus menutup turn ACK→hasil.

    Registry palsu mengembalikan ``False`` dari ``acquire_slot`` seperti task
    yang dibatalkan saat menunggu. Callback error membuktikan jalurnya benar-
    benar dijalankan; keadaan akhir harus tidak menyisakan turn apa pun.
    """
    registry = _Registry(acquire=False)
    _isolate_dispatch(monkeypatch, registry)
    cancelled = threading.Event()

    task = dispatch.dispatch_task(
        "offline cancel while queued",
        on_error=lambda _text: cancelled.set(),
    )

    assert task is registry.task
    assert cancelled.wait(2), "jalur cancelled-while-queued tidak tercapai"
    assert _wait_until(lambda: dispatch.active_count() == 0)
    assert registry.session_id, "registry tidak menerima binding session nyata"
    assert latency.active_count() == 0, (
        "worker sudah terminal tetapi turn session.id masih terbuka — return "
        "cancelled-while-queued melewati penutup latency"
    )
    assert registry.finished.wait(2), (
        "finalizer worker tidak menegaskan terminal state pada jalur "
        "cancelled-while-queued"
    )
    assert not registry.marked_running.is_set(), (
        "task dibatalkan saat mengantre tetapi tetap dipromosikan ke RUNNING"
    )
    assert not registry.released.is_set(), (
        "worker mencoba melepas slot yang tidak pernah diperolehnya"
    )


def test_exception_worker_tetap_menutup_turn_session(monkeypatch):
    """Exception kerja tidak boleh memindahkan penutup keluar dari ``finally``."""
    registry = _Registry(acquire=True)
    _isolate_dispatch(monkeypatch, registry)
    failed = threading.Event()

    async def no_replay(*_args, **_kwargs):
        return None

    async def explode(*_args, **_kwargs):
        raise RuntimeError("worker offline meledak")

    monkeypatch.setattr(dispatch, "_replay_plan", no_replay)
    monkeypatch.setattr("jarvis.agent.loop.run", explode)

    task = dispatch.dispatch_task(
        "offline worker exception",
        on_error=lambda _text: failed.set(),
    )

    assert task is registry.task
    assert failed.wait(2), "exception worker tidak mencapai callback terminal"
    assert _wait_until(lambda: dispatch.active_count() == 0)
    assert registry.released.wait(2)
    assert latency.active_count() == 0, (
        "exception worker melewati penutup latency session.id"
    )


def test_turn_berprogres_tidak_dievict_oleh_turn_tanpa_progres():
    """Turn dengan tahap terukur harus menang atas kandidat tanpa progres.

    Batas keras tetap 64. Saat penuh, turn tanpa satu pun marker adalah kandidat
    eviction pertama; ini mencegah kebocoran baru menghapus pengukuran turn sah
    yang sudah mencapai ``first_llm``.
    """
    base = latency.time.monotonic()
    latency.start("korban", task="giliran sah yang sedang berjalan", now=base)
    latency.mark("korban", "first_llm", now=base + 0.5)

    for i in range(latency.MAX_TURNS + 5):
        latency.start(f"bocor{i}", task=f"task {i}", now=base + 1 + i)

    assert latency.active_count() == latency.MAX_TURNS
    report = latency.finish("korban", now=base + 100.0)
    assert report != {}, (
        "turn berprogres dibuang oleh turn tanpa progres — pengukuran hilang "
        "dan finish() mengembalikan {}"
    )
    assert dict(report["stages"])["first_llm"] == pytest.approx(500.0)
