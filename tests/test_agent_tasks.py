"""AUDIT_REPORT §8 Fase 1-2 — TaskRegistry: konkurensi, kunci sumber daya,
pembatalan, dan progres.

Tidak ada UI di fase ini. Yang diuji adalah logikanya, dengan worker thread
yang meniru persis urutan kerja ``dispatch._worker``:

    acquire_slot → mark_running → kerja → finish → release_slot
"""
from __future__ import annotations

import asyncio
import threading
import time

import pytest

from jarvis.agent.tasks import (
    ACTIVE_STATES,
    Task,
    TaskRegistry,
    TaskStatus,
    TaskView,
)


class _NullBus:
    """BUS pengganti — mencatat topik supaya bisa diperiksa, tanpa Qt."""

    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []
        self._lock = threading.Lock()

    def publish(self, topic: str, **data) -> None:
        with self._lock:
            self.events.append((topic, data))

    def topics(self) -> list[str]:
        with self._lock:
            return [t for t, _ in self.events]


@pytest.fixture
def registry() -> TaskRegistry:
    return TaskRegistry(bus=_NullBus(), max_concurrent=3, queue_max=20,
                        poll_s=0.005)


def _worker(reg: TaskRegistry, task: Task, *,
            work=None, started: threading.Event | None = None,
            release: threading.Event | None = None,
            error: str = "") -> threading.Thread:
    """Meniru dispatch._worker: slot → RUNNING → kerja → finish → lepas."""

    def _run() -> None:
        if not reg.acquire_slot(task):
            return                                    # dibatalkan saat antre
        try:
            reg.mark_running(task.id)
            if started is not None:
                started.set()
            if work is not None:
                work(task)
            elif release is not None:
                while not release.is_set() and not task.cancel.is_set():
                    time.sleep(0.005)
            if task.cancel.is_set():
                reg.finish(task.id, status=TaskStatus.CANCELLED)
            elif error:
                reg.finish(task.id, error=error)
            else:
                reg.finish(task.id, result="ok")
        finally:
            reg.release_slot(task)

    th = threading.Thread(target=_run, daemon=True, name=f"t-{task.id}")
    th.start()
    return th


def _wait(predicate, timeout: float = 3.0, interval: float = 0.005) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(interval)
    return False


# ── 1. tiga task bersamaan → ketiganya RUNNING ───────────────────────────

def test_tiga_task_berjalan_bersamaan(registry: TaskRegistry) -> None:
    release = threading.Event()
    tasks = [registry.submit(f"tugas {i}") for i in range(3)]
    assert all(t is not None for t in tasks)
    threads = [_worker(registry, t, release=release) for t in tasks]

    assert _wait(lambda: registry.running_count() == 3), \
        f"hanya {registry.running_count()} RUNNING"
    assert {v.status for v in registry.snapshot()} == {TaskStatus.RUNNING}

    release.set()
    for th in threads:
        th.join(timeout=3)
    assert _wait(lambda: registry.running_count() == 0)
    assert all(v.status is TaskStatus.DONE for v in registry.snapshot())


# ── 2. task ke-4 → QUEUED, bukan ditolak ─────────────────────────────────

def test_task_keempat_mengantre_bukan_ditolak(registry: TaskRegistry) -> None:
    release = threading.Event()
    first = [registry.submit(f"tugas {i}") for i in range(3)]
    threads = [_worker(registry, t, release=release) for t in first]
    assert _wait(lambda: registry.running_count() == 3)

    fourth = registry.submit("tugas keempat")
    assert fourth is not None, "task ke-4 ditolak — seharusnya mengantre"
    assert fourth.status is TaskStatus.QUEUED

    threads.append(_worker(registry, fourth, release=release))
    # tetap QUEUED selama tiga slot terpakai
    time.sleep(0.15)
    assert registry.get(fourth.id).status is TaskStatus.QUEUED
    assert registry.running_count() == 3

    release.set()
    for th in threads:
        th.join(timeout=3)
    assert registry.get(fourth.id).status is TaskStatus.DONE


def test_antrean_penuh_menolak_dengan_none() -> None:
    reg = TaskRegistry(bus=_NullBus(), max_concurrent=1, queue_max=2,
                       poll_s=0.005)
    assert reg.submit("satu") is not None
    assert reg.submit("dua") is not None
    assert reg.submit("tiga") is None, "queue_max tidak ditegakkan"


# ── 3. dua task {"desktop"} tidak pernah RUNNING bersamaan ───────────────

def test_resource_desktop_tidak_pernah_paralel(registry: TaskRegistry) -> None:
    """Inti §8.2: dua agent tidak boleh sama-sama menyetir mouse."""
    live = 0
    peak = 0
    guard = threading.Lock()
    release = threading.Event()

    def work(_task: Task) -> None:
        nonlocal live, peak
        with guard:
            live += 1
            peak = max(peak, live)
        try:
            while not release.is_set():
                time.sleep(0.005)
        finally:
            with guard:
                live -= 1

    tasks = [registry.submit(f"desktop {i}", resources={"desktop"})
             for i in range(3)]
    threads = [_worker(registry, t, work=work) for t in tasks]

    assert _wait(lambda: live == 1)
    time.sleep(0.2)                       # beri kesempatan yang lain menyerobot
    assert peak == 1, f"{peak} task desktop berjalan bersamaan"
    # hanya satu yang RUNNING; sisanya masih QUEUED menunggu kunci
    assert registry.running_count() == 1

    release.set()
    for th in threads:
        th.join(timeout=3)
    assert peak == 1
    assert all(v.status is TaskStatus.DONE for v in registry.snapshot())


def test_resource_berbeda_tetap_paralel(registry: TaskRegistry) -> None:
    """Serialisasi hanya berlaku per-resource, bukan global."""
    release = threading.Event()
    a = registry.submit("pakai desktop", resources={"desktop"})
    b = registry.submit("pakai kamera", resources={"camera"})
    c = registry.submit("tanpa resource")
    threads = [_worker(registry, t, release=release) for t in (a, b, c)]

    assert _wait(lambda: registry.running_count() == 3), \
        "resource berbeda seharusnya tidak saling memblokir"

    release.set()
    for th in threads:
        th.join(timeout=3)


# ── 4. cancel task RUNNING → CANCELLED dalam < 2 detik ───────────────────

def test_cancel_task_running_cepat(registry: TaskRegistry) -> None:
    started = threading.Event()

    def work(task: Task) -> None:
        while not task.cancel.is_set():   # pembatalan kooperatif
            time.sleep(0.005)

    task = registry.submit("tugas panjang")
    th = _worker(registry, task, work=work, started=started)
    assert started.wait(timeout=3)

    t0 = time.monotonic()
    assert registry.cancel(task.id) is True
    assert _wait(lambda: registry.get(task.id).status is TaskStatus.CANCELLED,
                 timeout=2.0)
    elapsed = time.monotonic() - t0
    assert elapsed < 2.0, f"pembatalan makan {elapsed:.2f}s"

    th.join(timeout=3)
    assert registry.running_count() == 0


def test_cancel_task_queued_langsung_cancelled(registry: TaskRegistry) -> None:
    """Task QUEUED tidak punya pekerjaan yang perlu diberi kesempatan berhenti."""
    release = threading.Event()
    busy = [registry.submit(f"sibuk {i}") for i in range(3)]
    threads = [_worker(registry, t, release=release) for t in busy]
    assert _wait(lambda: registry.running_count() == 3)

    queued = registry.submit("belum mulai")
    assert queued.status is TaskStatus.QUEUED
    assert registry.cancel(queued.id) is True
    assert registry.get(queued.id).status is TaskStatus.CANCELLED

    release.set()
    for th in threads:
        th.join(timeout=3)


def test_cancel_melepas_slot_agar_antrean_maju(registry: TaskRegistry) -> None:
    """Regresi: task yang dibatalkan harus melepas slot DAN kunci resource."""
    def work(task: Task) -> None:
        while not task.cancel.is_set():
            time.sleep(0.005)

    first = registry.submit("desktop A", resources={"desktop"})
    th1 = _worker(registry, first, work=work)
    assert _wait(lambda: registry.get(first.id).status is TaskStatus.RUNNING)

    second = registry.submit("desktop B", resources={"desktop"})
    th2 = _worker(registry, second, work=work)
    time.sleep(0.1)
    assert registry.get(second.id).status is TaskStatus.QUEUED

    registry.cancel(first.id)
    th1.join(timeout=3)
    assert _wait(lambda: registry.get(second.id).status is TaskStatus.RUNNING), \
        "kunci desktop tidak dilepas setelah pembatalan"

    registry.cancel(second.id)
    th2.join(timeout=3)


# ── 5. task gagal → FAILED, error tersimpan, yang lain tidak terpengaruh ──

def test_task_gagal_tidak_menular(registry: TaskRegistry) -> None:
    release = threading.Event()
    boom = registry.submit("yang gagal")
    ok_a = registry.submit("yang sehat A")
    ok_b = registry.submit("yang sehat B")

    th_bad = _worker(registry, boom, error="ledakan di tool X")
    th_ok = [_worker(registry, t, release=release) for t in (ok_a, ok_b)]

    assert _wait(lambda: registry.get(boom.id).status is TaskStatus.FAILED)
    failed = registry.get(boom.id)
    assert failed.error == "ledakan di tool X"
    assert failed.result == ""

    # dua lainnya tetap berjalan normal
    assert _wait(lambda: registry.running_count() == 2)
    release.set()
    for th in [th_bad, *th_ok]:
        th.join(timeout=3)

    assert registry.get(ok_a.id).status is TaskStatus.DONE
    assert registry.get(ok_b.id).status is TaskStatus.DONE
    assert registry.get(ok_a.id).error == ""


def test_worker_crash_tetap_melepas_slot(registry: TaskRegistry) -> None:
    """Slot bocor = seluruh antrean membeku. Ini penjaganya."""
    def explode(_task: Task) -> None:
        raise RuntimeError("crash di tengah kerja")

    task = registry.submit("akan crash")

    def _run() -> None:
        if not registry.acquire_slot(task):
            return
        try:
            registry.mark_running(task.id)
            try:
                explode(task)
            except RuntimeError as exc:
                registry.finish(task.id, error=str(exc))
        finally:
            registry.release_slot(task)

    th = threading.Thread(target=_run, daemon=True)
    th.start()
    th.join(timeout=3)

    assert registry.get(task.id).status is TaskStatus.FAILED
    # slot benar-benar kembali: tiga task baru masih bisa RUNNING bersamaan
    release = threading.Event()
    fresh = [registry.submit(f"sesudah crash {i}") for i in range(3)]
    threads = [_worker(registry, t, release=release) for t in fresh]
    assert _wait(lambda: registry.running_count() == 3), "slot bocor"
    release.set()
    for t in threads:
        t.join(timeout=3)


# ── 6. snapshot() aman dari thread lain saat task berjalan ───────────────

def test_snapshot_aman_lintas_thread(registry: TaskRegistry) -> None:
    release = threading.Event()
    stop = threading.Event()
    errors: list[BaseException] = []
    samples: list[int] = []

    tasks = [registry.submit(f"tugas {i}") for i in range(3)]
    threads = [_worker(registry, t, release=release) for t in tasks]

    def reader() -> None:
        try:
            while not stop.is_set():
                snap = registry.snapshot()
                assert all(isinstance(v, TaskView) for v in snap)
                # TaskView imutabel — pembaca tidak bisa merusak state registry
                with pytest.raises((AttributeError, TypeError)):
                    snap[0].status = TaskStatus.DONE       # type: ignore[misc]
                samples.append(len(snap))
                registry.active()
                time.sleep(0.002)
        except BaseException as exc:                       # noqa: BLE001
            errors.append(exc)

    readers = [threading.Thread(target=reader, daemon=True) for _ in range(4)]
    for r in readers:
        r.start()
    time.sleep(0.25)
    release.set()
    for th in threads:
        th.join(timeout=3)
    stop.set()
    for r in readers:
        r.join(timeout=3)

    assert not errors, f"snapshot tidak aman lintas thread: {errors[:2]}"
    assert samples, "reader tidak pernah sempat membaca"
    assert all(n == 3 for n in samples)


def test_mutasi_hanya_lewat_registry(registry: TaskRegistry) -> None:
    task = registry.submit("uji")
    view = registry.get(task.id)
    assert isinstance(view, TaskView)
    with pytest.raises((AttributeError, TypeError)):
        view.step = "diretas"                              # type: ignore[misc]
    registry.update(task.id, step="langkah sah")
    assert registry.get(task.id).step == "langkah sah"
    # field privat tidak bisa disetel lewat update()
    registry.update(task.id, _slot=True)
    assert registry.get(task.id).status is TaskStatus.QUEUED


# ── 7. progres monoton, tidak pernah mundur ──────────────────────────────

def test_progress_tidak_pernah_mundur(registry: TaskRegistry) -> None:
    task = registry.submit("progres", max_iterations=10)
    seen: list[float] = []
    stop = threading.Event()
    errors: list[str] = []

    def watcher() -> None:
        last = -1.0
        while not stop.is_set():
            p = registry.get(task.id).progress
            if p < last:
                errors.append(f"progres mundur {last} → {p}")
            last = p
            seen.append(p)
            time.sleep(0.002)

    th = threading.Thread(target=watcher, daemon=True)
    th.start()
    for i in range(1, 11):
        registry.update(task.id, iteration=i)
        time.sleep(0.01)
    registry.update(task.id, iteration=3)      # laporan telat/kacau
    time.sleep(0.05)
    registry.finish(task.id, result="beres")
    time.sleep(0.05)
    stop.set()
    th.join(timeout=3)

    assert not errors, errors[:3]
    assert seen[-1] == 1.0
    assert registry.get(task.id).iteration == 10, "iteration mundur"


def test_progress_clamped_dan_terminal_penuh(registry: TaskRegistry) -> None:
    task = registry.submit("clamp", max_iterations=4)
    registry.update(task.id, iteration=99)
    assert registry.get(task.id).progress == pytest.approx(0.95)
    registry.finish(task.id, result="x")
    assert registry.get(task.id).progress == 1.0


def test_progress_awal_nol_dan_status_queued(registry: TaskRegistry) -> None:
    task = registry.submit("baru")
    view = registry.get(task.id)
    assert view.status is TaskStatus.QUEUED
    assert view.progress == 0.0
    assert view.elapsed == 0.0
    assert view.status in ACTIVE_STATES


# ── event BUS ────────────────────────────────────────────────────────────

def test_event_bus_dipublikasikan(registry: TaskRegistry) -> None:
    task = registry.submit("dengan event")
    registry.mark_running(task.id)
    registry.update(task.id, step="langkah")
    registry.finish(task.id, result="beres")
    topics = registry._bus.topics()
    assert "task.submitted" in topics
    assert "task.updated" in topics
    assert "task.finished" in topics


# ── Fase 2: integrasi dispatch ↔ loop ────────────────────────────────────

@pytest.fixture
def wired(monkeypatch):
    """dispatch + loop nyata, hanya panggilan LLM yang dipalsukan."""
    from jarvis.agent import dispatch, loop as agent_loop
    from jarvis.agent.tasks import REGISTRY

    monkeypatch.setattr(dispatch, "available", lambda: True)
    with dispatch._active_lock:
        dispatch._active.clear()
    REGISTRY.clear()
    yield dispatch, agent_loop, REGISTRY
    with dispatch._active_lock:
        dispatch._active.clear()
    REGISTRY.clear()


def test_dispatch_task_mengembalikan_task_dan_melaporkan_progres(
        wired, monkeypatch) -> None:
    dispatch, agent_loop, reg = wired
    done = threading.Event()
    progres: list[float] = []

    async def fake_run(task, adapter=None, session=None, bg_task=None, **kw):
        assert bg_task is not None, "loop tidak menerima bg_task"
        for i in range(1, 4):
            agent_loop._task_update(bg_task, iteration=i, step=f"langkah {i}")
            progres.append(reg.get(bg_task.id).progress)
        return agent_loop.RunResult(ok=True, text="selesai",
                                    session_id=getattr(session, "id", ""))

    monkeypatch.setattr(agent_loop, "run", fake_run)
    task = dispatch.dispatch_task("riset harga gpu",
                                  on_done=lambda _r: done.set())

    assert isinstance(task, Task)
    assert done.wait(timeout=5)
    assert _wait(lambda: reg.get(task.id).status is TaskStatus.DONE)
    view = reg.get(task.id)
    assert view.result == "selesai"
    assert view.progress == 1.0
    assert progres == sorted(progres), "progres mundur di jalur nyata"


def test_dispatch_async_tetap_mengembalikan_bool(wired, monkeypatch) -> None:
    """Kontrak lama dipegang belasan pemanggil + tests/test_phase2_dispatch.py:46."""
    dispatch, agent_loop, _reg = wired
    done = threading.Event()

    async def fake_run(task, adapter=None, session=None, bg_task=None, **kw):
        return agent_loop.RunResult(ok=True, text="ok",
                                    session_id=getattr(session, "id", ""))

    monkeypatch.setattr(agent_loop, "run", fake_run)
    started = dispatch.dispatch_async("tugas bool",
                                      on_done=lambda _r: done.set())
    assert started is True
    assert done.wait(timeout=5)

    monkeypatch.setattr(dispatch, "available", lambda: False)
    assert dispatch.dispatch_async("tak tersedia") is False
    assert dispatch.dispatch_task("tak tersedia") is None


def test_cancel_lewat_registry_menghentikan_loop(wired, monkeypatch) -> None:
    """Hook ① — batal kooperatif antar iterasi."""
    dispatch, agent_loop, reg = wired
    running = threading.Event()
    finished = threading.Event()
    iterasi: list[int] = []

    async def fake_run(task, adapter=None, session=None, bg_task=None, **kw):
        running.set()
        for i in range(1, 200):
            if agent_loop._cancelled(bg_task) or session.cancelled:
                return agent_loop.RunResult(ok=False, cancelled=True,
                                            iterations=i,
                                            session_id=session.id)
            iterasi.append(i)
            await asyncio.sleep(0.01)
        return agent_loop.RunResult(ok=True, text="tidak seharusnya sampai sini",
                                    session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)
    task = dispatch.dispatch_task("tugas panjang",
                                  on_done=lambda _r: finished.set(),
                                  on_error=lambda _e: finished.set())
    assert running.wait(timeout=5)

    t0 = time.monotonic()
    assert reg.cancel(task.id) is True
    assert _wait(lambda: reg.get(task.id).status is TaskStatus.CANCELLED,
                 timeout=2.0)
    assert time.monotonic() - t0 < 2.0
    assert len(iterasi) < 199, "loop tidak berhenti"


def test_bus_error_tidak_menjatuhkan_registry() -> None:
    class _BrokenBus:
        def publish(self, topic: str, **data) -> None:
            raise RuntimeError("bus mati")

    reg = TaskRegistry(bus=_BrokenBus(), max_concurrent=2, queue_max=5,
                       poll_s=0.005)
    task = reg.submit("tetap jalan")
    assert task is not None
    assert reg.finish(task.id, result="ok").status is TaskStatus.DONE
