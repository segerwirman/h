"""Registry tugas latar (AUDIT_REPORT §8.2). Satu sumber kebenaran untuk UI,
suara, dan agent.

Kontrak thread (§8 poin 2-3):

* Registry diakses dari minimal tiga thread — worker agent, thread Qt UI, dan
  event loop asyncio lane suara. Semua state dilindungi satu ``RLock``.
* **Tidak ada** mutasi field ``Task`` dari luar. Semua lewat method registry.
* Pembaca dari thread lain menerima ``TaskView`` **imutabel**, bukan ``Task``
  hidup — mengembalikan objek mutable ke thread lain persis balapan yang
  hendak dicegah. Ini satu-satunya penyimpangan dari tanda tangan §8.2
  (``snapshot() -> list[Task]``) dan disengaja.
* Event ke UI hanya lewat ``jarvis.core.bus`` yang sudah mem-marshal ke thread
  Qt. Modul ini tidak pernah menyentuh widget.

Serialisasi sumber daya (§8.2) punya DUA lapis, karena satu saja tidak cukup:

1. **Statis** — ``Task.resources`` dideklarasikan saat submit. Dipakai bila
   pemanggil sudah tahu tugasnya menyetir desktop/kamera/browser.
2. **Dinamis** — ``hold()`` dipakai ``loop.py`` tepat sebelum satu tool
   dieksekusi. Ini yang benar-benar mencegah dua agent berebut mouse, karena
   pada saat submit kita **belum tahu** tool mana yang akan dipilih model.
"""
from __future__ import annotations

import threading
import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum

from jarvis.core import config, log
from jarvis.core.bus import BUS

_logger = log.get("agent.tasks")


class TaskStatus(str, Enum):
    QUEUED = "queued"          # menunggu slot / resource
    RUNNING = "running"
    WAITING = "waiting"        # butuh konfirmasi user
    DONE = "done"
    FAILED = "failed"
    CANCELLED = "cancelled"


TERMINAL_STATES = frozenset({
    TaskStatus.DONE, TaskStatus.FAILED, TaskStatus.CANCELLED})
ACTIVE_STATES = frozenset({
    TaskStatus.QUEUED, TaskStatus.RUNNING, TaskStatus.WAITING})

# §8.2 — hanya nama di sini yang diserialkan. Sisanya jalan paralel penuh.
DEFAULT_EXCLUSIVE = ("desktop", "camera", "browser_context")


def exclusive_resources() -> frozenset[str]:
    raw = config.get("agent.exclusive_resources", list(DEFAULT_EXCLUSIVE))
    if isinstance(raw, str):
        raw = [raw]
    try:
        names = {str(v).strip() for v in raw if str(v).strip()}
    except TypeError:
        names = set(DEFAULT_EXCLUSIVE)
    return frozenset(names or DEFAULT_EXCLUSIVE)


@dataclass
class Task:
    """State satu tugas latar. JANGAN dimutasi dari luar registry."""

    id: str = field(default_factory=lambda: f"T-{uuid.uuid4().hex[:4]}")
    title: str = ""                     # ringkas, layak diucapkan
    prompt: str = ""                    # perintah asli lengkap
    status: TaskStatus = TaskStatus.QUEUED
    step: str = ""                      # "browser_navigate → tokopedia.com"
    iteration: int = 0
    max_iterations: int = 50
    resources: frozenset = frozenset()  # {"desktop"}, {"camera"}, ...
    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    finished_at: float | None = None
    result: str = ""
    error: str = ""
    # Completion speech has exactly one owner. Registry-owned tasks have no
    # terminal callback (for example Live ``task_start``); caller-owned tasks
    # deliver through their typed/voice/remote callback instead.
    completion_owner: str = "registry"
    source: str = "agent"
    # Sesi agent yang mengerjakan task ini — dipakai Task Deck untuk memfilter
    # data/logs/tools.jsonl per tugas (record tool memakai kunci "session").
    session_id: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)

    # dipegang registry saja
    _held: tuple[str, ...] = field(default=(), repr=False)
    _slot: bool = field(default=False, repr=False)
    _finish_pending: bool = field(default=False, repr=False)
    _finished_published: bool = field(default=False, repr=False)

    @property
    def progress(self) -> float:
        """0.0–1.0, kasar tapi jujur. Dijamin monoton naik: ``iteration``
        tidak pernah diturunkan oleh ``update()``, dan state terminal selalu
        1.0 yang >= nilai mana pun sebelumnya."""
        if self.status in TERMINAL_STATES:
            return 1.0
        return min(0.95, self.iteration / max(1, self.max_iterations))

    @property
    def elapsed(self) -> float:
        if self.started_at is None:
            return 0.0
        return (self.finished_at or time.time()) - self.started_at


@dataclass(frozen=True)
class TaskView:
    """Salinan imutabel untuk dibaca lintas thread (UI, suara, tes)."""

    id: str
    title: str
    prompt: str
    status: TaskStatus
    step: str
    iteration: int
    max_iterations: int
    resources: frozenset
    created_at: float
    started_at: float | None
    finished_at: float | None
    result: str
    error: str
    completion_owner: str
    source: str
    session_id: str
    progress: float
    elapsed: float
    cancelled: bool

    @property
    def active(self) -> bool:
        return self.status in ACTIVE_STATES

    def as_dict(self) -> dict:
        return {
            "id": self.id, "title": self.title, "status": self.status.value,
            "step": self.step, "iteration": self.iteration,
            "progress": self.progress, "elapsed": self.elapsed,
            "result": self.result, "error": self.error,
            "completion_owner": self.completion_owner,
            "source": self.source,
            "resources": sorted(self.resources),
        }


def _view(task: Task) -> TaskView:
    return TaskView(
        id=task.id, title=task.title, prompt=task.prompt, status=task.status,
        step=task.step, iteration=task.iteration,
        max_iterations=task.max_iterations, resources=task.resources,
        created_at=task.created_at, started_at=task.started_at,
        finished_at=task.finished_at, result=task.result, error=task.error,
        completion_owner=task.completion_owner, source=task.source,
        session_id=task.session_id, progress=task.progress, elapsed=task.elapsed,
        cancelled=task.cancel.is_set(),
    )


def _title_from(prompt: str, limit: int = 60) -> str:
    text = " ".join(str(prompt or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


class TaskRegistry:
    """Thread-safe. Mem-publish ke BUS: task.submitted / updated / finished."""

    def __init__(self, bus=BUS, max_concurrent: int | None = None,
                 queue_max: int | None = None,
                 poll_s: float = 0.02) -> None:
        self._lock = threading.RLock()
        self._tasks: dict[str, Task] = {}
        self._bus = bus
        self._poll_s = poll_s
        self._max_concurrent = int(
            max_concurrent
            if max_concurrent is not None
            else config.get("agent.max_concurrent_tasks", 3))
        self._queue_max = int(
            queue_max if queue_max is not None
            else config.get("agent.queue_max", 20))
        self._sem = threading.BoundedSemaphore(max(1, self._max_concurrent))
        self._resource_locks: dict[str, threading.Lock] = {}

    # ── introspeksi ──────────────────────────────────────────────────────

    @property
    def max_concurrent(self) -> int:
        return self._max_concurrent

    @property
    def queue_max(self) -> int:
        return self._queue_max

    def _publish_view(self, topic: str, view: TaskView) -> None:
        """BUS tidak pernah boleh menjatuhkan worker agent."""
        try:
            self._bus.publish(topic, task=view.as_dict())
        except Exception:                                    # noqa: BLE001
            _logger.warning("tasks.publish_failed", topic=topic, id=view.id)

    def _publish(self, topic: str, task: Task) -> None:
        self._publish_view(topic, _view(task))

    def _resource_lock(self, name: str) -> threading.Lock:
        with self._lock:
            lk = self._resource_locks.get(name)
            if lk is None:
                lk = threading.Lock()
                self._resource_locks[name] = lk
            return lk

    # ── siklus hidup ─────────────────────────────────────────────────────

    def submit(self, prompt: str, title: str | None = None,
               resources: frozenset | set | tuple = frozenset(),
               max_iterations: int | None = None,
               completion_owner: str = "registry",
               source: str = "agent") -> Task | None:
        """Task baru berstatus QUEUED. ``None`` bila antrean penuh."""
        res = frozenset(str(r).strip() for r in (resources or ()) if str(r).strip())
        with self._lock:
            if sum(1 for t in self._tasks.values()
                   if t.status in ACTIVE_STATES) >= self._queue_max:
                _logger.warning("tasks.queue_full", queue_max=self._queue_max)
                return None
            owner = str(completion_owner or "registry").casefold()
            if owner not in {"registry", "caller"}:
                owner = "registry"
            task = Task(
                title=title or _title_from(prompt),
                prompt=str(prompt or ""),
                resources=res,
                completion_owner=owner,
                source=str(source or "agent")[:32],
                max_iterations=int(
                    max_iterations
                    if max_iterations is not None
                    else config.get("agent.max_iterations", 50)),
            )
            self._tasks[task.id] = task
        self._publish("task.submitted", task)
        return task

    def update(self, task_id: str, **fields) -> TaskView | None:
        """Satu-satunya jalan memutasi Task. Publish ``task.updated``."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            for key, value in fields.items():
                if key.startswith("_") or not hasattr(task, key):
                    continue
                if key == "iteration":
                    # progres wajib monoton — jangan pernah mundur
                    value = max(int(task.iteration), int(value))
                if key == "status":
                    value = TaskStatus(value)
                setattr(task, key, value)
            view = _view(task)
        self._publish("task.updated", task)
        return view

    def mark_running(self, task_id: str) -> TaskView | None:
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATES:
                return None
            task.status = TaskStatus.RUNNING
            if task.started_at is None:
                task.started_at = time.time()
            view = _view(task)
        self._publish("task.updated", task)
        return view

    def prepare_finish(self, task_id: str, result: str = "", error: str = "",
                       status: TaskStatus | None = None,
                       completion_owner: str | None = None) -> TaskView | None:
        """Begin one unpublished terminal transition for callback resolution.

        The terminal status, result, and provisional speech owner become visible
        atomically. A caller that arrives after another terminal claim gets no
        transition view and must not invoke a second completion callback.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATES:
                return None
            if status is None:
                if task.cancel.is_set():
                    status = TaskStatus.CANCELLED
                elif error:
                    status = TaskStatus.FAILED
                else:
                    status = TaskStatus.DONE
            owner = str(completion_owner or "").casefold()
            if owner in {"registry", "caller"}:
                task.completion_owner = owner
            task.status = status
            task.result = str(result or "")
            task.error = str(error or "")
            task.finished_at = time.time()
            if task.started_at is None:
                task.started_at = task.finished_at
            task.step = ""
            task._finish_pending = True
            return _view(task)


    def publish_finish(self, task_id: str,
                       completion_owner: str | None = None) -> TaskView | None:
        """Resolve terminal owner and publish ``task.finished`` exactly once."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status not in TERMINAL_STATES:
                return None
            if task._finished_published:
                return _view(task)
            owner = str(completion_owner or "").casefold()
            if owner in {"registry", "caller"}:
                task.completion_owner = owner
            task._finish_pending = False
            task._finished_published = True
            # Publish an immutable snapshot.  A subscriber is synchronous, may
            # trigger another registry call, and must never observe a mutable
            # Task after this lock has been released.
            view = _view(task)
        self._publish_view("task.finished", view)
        return view

    def finish(self, task_id: str, result: str = "", error: str = "",
               status: TaskStatus | None = None,
               completion_owner: str | None = None) -> TaskView | None:
        """Atomically claim and publish a compatibility terminal transition.

        The old pre-check followed by ``prepare_finish()`` left a window where
        two direct finishers could both observe a live task.  The first caller
        now establishes the terminal snapshot while holding the registry lock;
        every later caller returns that immutable snapshot and cannot replace
        its result or speech owner.
        """
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                return None
            if task.status in TERMINAL_STATES:
                return _view(task)
            if status is None:
                if task.cancel.is_set():
                    status = TaskStatus.CANCELLED
                elif error:
                    status = TaskStatus.FAILED
                else:
                    status = TaskStatus.DONE
            owner = str(completion_owner or "").casefold()
            if owner in {"registry", "caller"}:
                task.completion_owner = owner
            task.status = status
            task.result = str(result or "")
            task.error = str(error or "")
            task.finished_at = time.time()
            if task.started_at is None:
                task.started_at = task.finished_at
            task.step = ""
            task._finish_pending = False
            task._finished_published = True
            view = _view(task)
        self._publish_view("task.finished", view)
        return view

    def cancel(self, task_id: str) -> bool:
        """Kooperatif: set event. Task QUEUED langsung jadi CANCELLED karena
        belum ada pekerjaan yang perlu diberi kesempatan berhenti."""
        with self._lock:
            task = self._tasks.get(task_id)
            if task is None or task.status in TERMINAL_STATES:
                return False
            task.cancel.set()
            queued = task.status == TaskStatus.QUEUED and not task._slot
            view_task = task
        self._publish("task.updated", view_task)
        if queued:
            self.finish(task_id, status=TaskStatus.CANCELLED)
        return True

    def cancel_all(self) -> int:
        with self._lock:
            ids = [t.id for t in self._tasks.values()
                   if t.status in ACTIVE_STATES]
        return sum(1 for tid in ids if self.cancel(tid))

    # ── pembacaan lintas thread ──────────────────────────────────────────

    def get(self, task_id: str) -> TaskView | None:
        with self._lock:
            task = self._tasks.get(task_id)
            return _view(task) if task is not None else None

    def snapshot(self) -> list[TaskView]:
        """Aman dipanggil dari thread mana pun saat task berjalan."""
        with self._lock:
            return [_view(t) for t in self._tasks.values()]

    def active(self) -> list[TaskView]:
        return [v for v in self.snapshot() if v.status in ACTIVE_STATES]

    def running_count(self) -> int:
        with self._lock:
            return sum(1 for t in self._tasks.values()
                       if t.status == TaskStatus.RUNNING)

    def prune(self, keep_terminal: int = 50) -> int:
        """Buang task terminal terlama agar registry tidak tumbuh tanpa batas."""
        with self._lock:
            done = sorted(
                (t for t in self._tasks.values()
                 if t.status in TERMINAL_STATES),
                key=lambda t: t.finished_at or t.created_at)
            drop = done[:-keep_terminal] if len(done) > keep_terminal else []
            for t in drop:
                self._tasks.pop(t.id, None)
            return len(drop)

    def clear(self) -> None:
        """Hanya untuk tes — buang seluruh state."""
        with self._lock:
            self._tasks.clear()
            self._resource_locks.clear()
            self._sem = threading.BoundedSemaphore(max(1, self._max_concurrent))

    # ── slot konkurensi + kunci sumber daya ──────────────────────────────

    def _acquire_cancellable(self, primitive, task: Task) -> bool:
        """Blocking acquire yang tetap responsif terhadap cancel."""
        while True:
            if task.cancel.is_set():
                return False
            if primitive.acquire(timeout=self._poll_s):
                return True

    def acquire_slot(self, task: Task) -> bool:
        """Tunggu slot konkurensi + seluruh resource eksklusif milik task.

        Urutan: semaphore dulu, lalu resource **terurut nama** — urutan global
        yang konsisten inilah yang mencegah deadlock silang. Pemegang lock
        selalu punya slot dan karena itu pasti maju, sehingga antrean tidak
        pernah macet permanen.

        ``False`` bila dibatalkan selagi menunggu.
        """
        if not self._acquire_cancellable(self._sem, task):
            self.finish(task.id, status=TaskStatus.CANCELLED)
            return False
        with self._lock:
            task._slot = True

        held: list[str] = []
        for name in sorted(task.resources):
            lock = self._resource_lock(name)
            if not self._acquire_cancellable(lock, task):
                for got in held:
                    self._resource_lock(got).release()
                with self._lock:
                    task._slot = False
                    task._held = ()
                self._sem.release()
                self.finish(task.id, status=TaskStatus.CANCELLED)
                return False
            held.append(name)

        with self._lock:
            task._held = tuple(held)
        return True

    def release_slot(self, task: Task) -> None:
        with self._lock:
            held = task._held
            had_slot = task._slot
            task._held = ()
            task._slot = False
        for name in held:
            try:
                self._resource_lock(name).release()
            except RuntimeError:                             # noqa: BLE001
                pass
        if had_slot:
            try:
                self._sem.release()
            except ValueError:                               # noqa: BLE001
                pass

    def try_acquire(self, task: Task | None, resources) -> list[str] | None:
        """Non-blocking. Kembalikan daftar resource yang berhasil dipegang,
        atau ``None`` bila ada yang sedang dipakai task lain.

        Dipakai jalur **async** (``loop.py``): acquire blocking akan
        membekukan event loop, sehingga pemanggil harus melakukan poll
        sendiri dengan ``await asyncio.sleep``.
        """
        names = sorted({str(r) for r in (resources or ()) if str(r).strip()})
        if not names:
            return []
        already: set[str] = set()
        if task is not None:
            with self._lock:
                already = set(task._held)
        wanted = [n for n in names if n not in already]
        got: list[str] = []
        for name in wanted:
            if self._resource_lock(name).acquire(blocking=False):
                got.append(name)
                continue
            for held in reversed(got):                       # rollback penuh
                try:
                    self._resource_lock(held).release()
                except RuntimeError:                         # noqa: BLE001
                    pass
            return None
        return got

    def release_held(self, names) -> None:
        for name in reversed(list(names or ())):
            try:
                self._resource_lock(str(name)).release()
            except RuntimeError:                             # noqa: BLE001
                pass

    @contextmanager
    def hold(self, task: Task | None, resources):
        """Kunci resource **per tool call** (lapis dinamis).

        Dipakai ``loop.py`` tepat sebelum sebuah tool dieksekusi. Diperlukan
        karena saat submit kita belum tahu tool mana yang akan dipilih model —
        deklarasi statis saja tidak akan pernah menangkap agent yang tiba-tiba
        memanggil ``computer_click``.

        Resource yang sudah dipegang task di level slot tidak diambil ulang
        (``threading.Lock`` tidak reentrant → itu akan deadlock dengan diri
        sendiri).
        """
        names = sorted({str(r) for r in (resources or ()) if str(r).strip()})
        if task is None or not names:
            yield True
            return
        with self._lock:
            already = set(task._held)
        wanted = [n for n in names if n not in already]
        got: list[str] = []
        try:
            for name in wanted:
                lock = self._resource_lock(name)
                if not self._acquire_cancellable(lock, task):
                    yield False
                    return
                got.append(name)
            yield True
        finally:
            for name in reversed(got):
                try:
                    self._resource_lock(name).release()
                except RuntimeError:                         # noqa: BLE001
                    pass


REGISTRY = TaskRegistry()

__all__ = [
    "Task", "TaskView", "TaskStatus", "TaskRegistry", "REGISTRY",
    "ACTIVE_STATES", "TERMINAL_STATES", "exclusive_resources",
]
