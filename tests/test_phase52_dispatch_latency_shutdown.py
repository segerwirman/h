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
from jarvis.agent import session as session_module
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
def _alihkan_db_sesi(tmp_path, monkeypatch):
    """Fase 68 — alihkan DB sesi ke tmp_path agar statusnya bisa diamati.

    Tanpa ini, ``Session.finish``/``record_turn`` menulis ke
    ``data/agent.sqlite`` milik pemakai. Pola yang sama dengan Fase 67.
    """
    monkeypatch.setattr(session_module, "db_path",
                        lambda: tmp_path / "session.sqlite")


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


def _status_sesi(session_id: str) -> str:
    """Status sesi sebagaimana terlihat operator di permukaan kelola.

    Diturunkan oleh ``management_surface._session_item`` dari ``ended_at``
    dan ``ok`` (management_surface.py:53). Dipakai agar RED mengunci apa yang
    terlihat operator, bukan struktur internalnya.
    """
    from jarvis.agent import management_surface

    for row in session_module.recent_sessions(20):
        if str(row.get("id")) == str(session_id):
            return management_surface._session_item(row)["status"]
    return "hilang"


def test_timeout_tidak_membiarkan_sesi_terbaca_menggantung(monkeypatch):
    """RED Fase 68 — sesi timeout tidak boleh terbaca "running" selamanya.

    Terukur pada Fase 68: setelah timeout, ``session.cancelled`` benar
    ``True`` dan ``on_error`` benar menyebut timeout, TETAPI baris sesinya
    tetap ``ended_at=None`` sehingga permukaan kelola membacanya ``running``.
    Padahal tugasnya sudah berakhir dengan gagal. Operator yang membuka
    permukaan kelola melihat tugas yang tak pernah selesai.

    Sebabnya: ``session.finish`` adalah satu-satunya pemanggil
    ``_ensure_row``, dan ia tidak pernah dipanggil di jalur timeout
    (``dispatch.py:1241-1253``) — hanya ``session.cancel()``, yang sebatas
    menyetel flag di memori dan tidak menulis apa pun ke arsip.

    Pembuktian dua arah pada Fase 68: menambahkan
    ``session.finish(err, ok=False)`` pada jalur ini TIDAK TERDETEKSI oleh 69
    test yang ada — jadi perbaikan kelak tidak akan dijaga tanpa test ini.
    """
    import asyncio

    registry = _Registry(acquire=True)
    _isolate_dispatch(monkeypatch, registry)

    async def hang(*_args, **_kwargs):
        await asyncio.sleep(30)

    monkeypatch.setattr("jarvis.agent.loop.run", hang)

    made: list = []
    real_session = session_module.Session

    class SpySession(real_session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr("jarvis.agent.session.Session", SpySession)

    errors: list[str] = []
    dispatch.dispatch_task("offline timeout status", timeout_s=0.3,
                           on_error=lambda text, **_kw: errors.append(
                               str(text)))

    assert _wait_until(lambda: bool(errors), timeout=5.0), (
        "timeout tidak pernah mencapai on_error"
    )
    assert made, "sesi tidak pernah dibuat"
    session = made[0]
    # loop.run sungguhan mencatat giliran; itu yang mempersist barisnya.
    session.record_turn("user", "offline timeout status")

    status = _status_sesi(session.id)
    assert status != "hilang", (
        "sesi timeout tidak pernah dipersist sama sekali"
    )
    assert status == "failed", (
        f"sesi yang sudah timeout terbaca '{status}' di permukaan kelola — "
        "operator melihat tugas menggantung selamanya padahal tugasnya sudah "
        "berakhir gagal"
    )


def test_kegagalan_agent_tidak_membiarkan_sesi_terbaca_menggantung(
        monkeypatch):
    """RED Fase 68 — sesi yang agent-nya gagal tidak boleh terbaca "running".

    Sama dengan timeout, pada jalur ``result.ok`` false
    (``dispatch.py:1229-1240``) ``session.finish`` tidak pernah dipanggil.
    Terukur pada Fase 68: statusnya tetap ``running`` walau ``on_error`` sudah
    menyampaikan kegagalan kepada pemakai.

    Akibatnya arsip sesi tidak pernah mencatat kegagalan, dan operator tidak
    bisa membedakan tugas yang sedang berjalan dari tugas yang sudah gagal.
    """
    registry = _Registry(acquire=True)
    _isolate_dispatch(monkeypatch, registry)

    async def fail_run(task, *, adapter, session, **_kwargs):
        session.record_turn("user", task)
        session.record_turn("assistant", "Gagal membuka.")
        await adapter.send("Gagal membuka.")
        from jarvis.agent.loop import RunResult
        return RunResult(ok=False, text="Gagal membuka.",
                         session_id=session.id)

    monkeypatch.setattr("jarvis.agent.loop.run", fail_run)

    made: list = []
    real_session = session_module.Session

    class SpySession(real_session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr("jarvis.agent.session.Session", SpySession)

    errors: list[str] = []
    dispatch.dispatch_task(
        "offline agent gagal",
        on_error=lambda text, **_kw: errors.append(str(text)))

    assert _wait_until(lambda: bool(errors), timeout=5.0), (
        "kegagalan agent tidak pernah mencapai on_error"
    )
    assert made, "sesi tidak pernah dibuat"

    status = _status_sesi(made[0].id)
    assert status != "hilang", "sesi yang gagal tidak pernah dipersist"
    assert status == "failed", (
        f"sesi yang agent-nya gagal terbaca '{status}' di permukaan kelola — "
        "operator tidak bisa membedakan tugas berjalan dari tugas yang sudah "
        "gagal"
    )


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


def test_worker_melepas_seluruh_resource_setelah_mengambil_ownership(monkeypatch):
    """Jalur PASCA-ownership wajib melepas kelima resource, bukan cuma latency.

    RED untuk Fase 64. Jendela pra-worker sudah dijaga ``_abort_pre_worker``
    (Fase 54-58), tetapi blok ``finally`` worker — jalur SETELAH worker
    mengambil ownership — terbukti tidak dikunci satu test pun: uji mutasi
    membuktikan menghapus SELURUH blok release di ``finally`` membuat nol test
    gagal.

    Penyebabnya ada di helper file ini sendiri: ``_isolate_dispatch``
    men-stub kelima fungsi release menjadi no-op, sehingga tidak ada satu pun
    test yang mengamati apakah mereka benar-benar dipanggil. Karena itu test
    ini memasang pencatatnya sendiri.
    """
    registry = _Registry(acquire=True)
    _isolate_dispatch(monkeypatch, registry)
    failed = threading.Event()

    async def no_replay(*_args, **_kwargs):
        return None

    async def explode(*_args, **_kwargs):
        raise RuntimeError("worker offline meledak")

    monkeypatch.setattr(dispatch, "_replay_plan", no_replay)
    monkeypatch.setattr("jarvis.agent.loop.run", explode)

    calls: list[tuple[str, str]] = []
    for name in (
        "_release_browser_session",
        "_release_computer_session",
        "_clear_desktop_safe_session",
        "_clear_captcha_handoff_session",
        "_release_screen_control_session",
    ):
        monkeypatch.setattr(
            dispatch, name,
            lambda sid, _n=name: calls.append((_n, str(sid))),
        )
    monkeypatch.setattr(
        dispatch, "_revoke_execution_grants",
        lambda tid: calls.append(("_revoke_execution_grants", str(tid))),
    )

    dispatch.dispatch_task(
        "offline worker release audit",
        on_error=lambda _text: failed.set(),
    )

    assert failed.wait(2), "exception worker tidak mencapai callback terminal"
    assert _wait_until(lambda: dispatch.active_count() == 0)

    released = {name for name, _sid in calls}
    assert released == {
        "_release_browser_session",
        "_release_computer_session",
        "_clear_desktop_safe_session",
        "_clear_captcha_handoff_session",
        "_release_screen_control_session",
        "_revoke_execution_grants",
    }, f"resource yang dilepas tidak lengkap: {sorted(released)}"

    # Masing-masing dipanggil dengan session id yang sama, bukan string kosong.
    by_session = [sid for name, sid in calls
                  if name != "_revoke_execution_grants"]
    assert by_session, "tidak ada release yang menerima session id"
    assert all(sid and sid == registry.session_id for sid in by_session), (
        f"release dipanggil dengan session id yang salah: {by_session!r} "
        f"(registry.session_id={registry.session_id!r})"
    )


def test_timeout_worker_membatalkan_sesi_dan_melepas_resource(monkeypatch):
    """Jalur TIMEOUT worker tidak pernah ditest — mutan di penjaganya HIDUP.

    Fase 64 mengunci blok ``finally``, tetapi hanya pada jalur exception.
    Uji mutasi Fase 65 membuktikan jalur ``except asyncio.TimeoutError``
    (``dispatch.py:1241-1253``) sama sekali tidak terkunci: mengganti
    ``except asyncio.TimeoutError`` menjadi penjaga lain membuat **nol** test
    gagal. Jadi tidak ada satu pun test yang pernah menjalankan timeout
    sungguhan — padahal inilah satu-satunya jalur yang memanggil
    ``session.cancel()``.

    RED ini menempuhnya dengan ``timeout_s`` nyata dan loop yang menggantung,
    lalu menuntut tiga hal yang hanya mungkin bila penjaga timeout benar-benar
    berjalan: sesi terbukti dibatalkan, pemanggil menerima keterangan timeout,
    dan tidak ada resource yang jadi yatim.
    """
    import asyncio

    registry = _Registry(acquire=True)
    _isolate_dispatch(monkeypatch, registry)
    delivered: list[str] = []

    async def no_replay(*_args, **_kwargs):
        return None

    async def hang(*_args, **_kwargs):
        """Menggantung lebih lama dari timeout agar wait_for benar-benar batas."""
        await asyncio.sleep(30)

    monkeypatch.setattr(dispatch, "_replay_plan", no_replay)
    monkeypatch.setattr("jarvis.agent.loop.run", hang)

    # Tangkap sesi yang dibuat dispatch — ``session.cancel()`` hanya terjadi
    # di penjaga timeout, jadi ini satu-satunya pengamatan langsung atasnya.
    made: list = []
    real_session = session_module.Session

    class SpySession(real_session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr("jarvis.agent.session.Session", SpySession)

    calls: list[tuple[str, str]] = []
    for name in (
        "_release_browser_session",
        "_release_computer_session",
        "_clear_desktop_safe_session",
        "_clear_captcha_handoff_session",
        "_release_screen_control_session",
    ):
        monkeypatch.setattr(
            dispatch, name,
            lambda sid, _n=name: calls.append((_n, str(sid))),
        )
    monkeypatch.setattr(
        dispatch, "_revoke_execution_grants",
        lambda tid: calls.append(("_revoke_execution_grants", str(tid))),
    )

    dispatch.dispatch_task(
        "offline timeout worker",
        timeout_s=0.15,
        on_error=lambda text, **_kwargs: delivered.append(str(text)),
    )

    assert _wait_until(lambda: dispatch.active_count() == 0, timeout=5.0), (
        "timeout membuat worker menggantung tanpa pernah terminal"
    )
    assert _wait_until(lambda: bool(delivered), timeout=5.0), (
        "timeout tidak pernah mencapai on_error — pemakai hanya mendapat sunyi"
    )

    # 1. inti jalur ini: sesi HARUS dibatalkan. Hanya penjaga timeout yang
    #    melakukannya, jadi tanpa penjaga itu nilai ini tetap False.
    assert made, "sesi tidak pernah dibuat — dispatch tidak mencapai worker"
    assert made[0].cancelled is True, (
        "session.cancel() tidak berjalan: penjaga timeout tidak menangani "
        "asyncio.TimeoutError, sehingga sesi dibiarkan hidup walau batas waktu "
        "sudah terlampaui"
    )

    # 2. keterangannya harus menjelaskan timeout, bukan "selesai tanpa status".
    assert "timeout" in delivered[0], (
        f"callback terminal tidak menjelaskan timeout: {delivered}"
    )

    # 3. resource tidak boleh jadi yatim hanya karena jalurnya berbeda.
    released = {name for name, _sid in calls}
    assert released == {
        "_release_browser_session",
        "_release_computer_session",
        "_clear_desktop_safe_session",
        "_clear_captcha_handoff_session",
        "_release_screen_control_session",
        "_revoke_execution_grants",
    }, f"timeout melewatkan pelepasan resource: {sorted(released)}"
    assert latency.active_count() == 0, "timeout melewati penutup latency"


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


def test_thread_start_gagal_tidak_meninggalkan_turn_task_atau_active(monkeypatch):
    """Kegagalan OS memulai worker harus terminal sebelum exception merambat.

    ``latency.start(session.id)``, registry submit, dan binding ``_active`` terjadi
    sebelum ``Thread.start()``. Fake ini membuat HANYA operasi start gagal, lalu
    mengukur tiga pemilik state setelah exception: latency, TaskRegistry, dan
    dispatch. Exception tetap dibiarkan merambat agar slice ini tidak mengubah
    kontrak error yang tidak diminta pengguna.
    """
    from jarvis.agent.tasks import TaskRegistry, TaskStatus

    class SilentBus:
        def publish(self, *_args, **_kwargs):
            return None

    class StartFailureThread:
        def __init__(self, *, target, daemon, name):
            self.target = target
            self.daemon = daemon
            self.name = name

        def start(self):
            raise RuntimeError("fake OS menolak thread baru")

    registry = TaskRegistry(bus=SilentBus(), max_concurrent=1, queue_max=2)
    _isolate_dispatch(monkeypatch, registry)
    monkeypatch.setattr(dispatch.threading, "Thread", StartFailureThread)

    try:
        with pytest.raises(RuntimeError, match="fake OS menolak thread baru"):
            dispatch.dispatch_task("offline worker start failure")

        views = registry.snapshot()
        measured = {
            "latency_active": latency.active_count(),
            "registry": [(view.id, view.status.value) for view in views],
            "registry_active": [view.id for view in registry.active()],
            "dispatch_active": dispatch.active_count(),
        }
        assert measured == {
            "latency_active": 0,
            "registry": [(views[0].id, TaskStatus.FAILED.value)],
            "registry_active": [],
            "dispatch_active": 0,
        }, (
            "Thread.start() gagal setelah seluruh state dibuka, tetapi cleanup "
            f"tidak atomik: {measured}"
        )
    finally:
        latency.reset()
        registry.clear()
        with dispatch._active_lock:
            dispatch._active.clear()


def test_thread_konstruksi_gagal_tidak_meninggalkan_turn_task_atau_active(
    monkeypatch,
):
    """Kegagalan KONSTRUKSI worker harus terminal sebelum exception merambat.

    Fase 54 hanya menjaga ``Thread.start()``. Konstruksi objek thread itu
    sendiri masih berada di luar penjaga itu, padahal ia terjadi SETELAH
    ``latency.start(session.id)``, registry submit, binding session, ACK, dan
    ``_active`` dibuka. Fake ini melempar dari ``__init__`` sehingga objek
    thread tidak pernah ada sama sekali, lalu mengukur tiga pemilik state yang
    sama dengan ukuran Fase 54 agar hasilnya dapat dibandingkan langsung.
    """
    from jarvis.agent.tasks import TaskRegistry, TaskStatus

    class SilentBus:
        def publish(self, *_args, **_kwargs):
            return None

    class ConstructorFailureThread:
        def __init__(self, *, target, daemon, name):
            raise RuntimeError("fake OS menolak konstruksi thread")

    registry = TaskRegistry(bus=SilentBus(), max_concurrent=1, queue_max=2)
    _isolate_dispatch(monkeypatch, registry)
    monkeypatch.setattr(dispatch.threading, "Thread", ConstructorFailureThread)

    try:
        with pytest.raises(RuntimeError,
                           match="fake OS menolak konstruksi thread"):
            dispatch.dispatch_task("offline worker construction failure")

        views = registry.snapshot()
        measured = {
            "latency_active": latency.active_count(),
            "registry": [(view.id, view.status.value) for view in views],
            "registry_active": [view.id for view in registry.active()],
            "dispatch_active": dispatch.active_count(),
        }
        assert measured == {
            "latency_active": 0,
            "registry": [(views[0].id, TaskStatus.FAILED.value)],
            "registry_active": [],
            "dispatch_active": 0,
        }, (
            "Konstruksi Thread gagal setelah seluruh state dibuka, tetapi "
            f"cleanup tidak atomik: {measured}"
        )
    finally:
        latency.reset()
        registry.clear()
        with dispatch._active_lock:
            dispatch._active.clear()


def test_timeout_non_numeric_tidak_meninggalkan_turn_task_atau_active(
    monkeypatch,
):
    """Kegagalan DI DALAM jendela terbuka tidak boleh meninggalkan yatim.

    Fase 54/55 menutup konstruksi dan start thread, tetapi keduanya berada di
    UJUNG jendela yang lebih panjang: ``latency.start(session.id)`` dibuka di
    baris 1084, sedangkan penjaga baru mulai di baris 1251. Pernyataan di
    antaranya yang paling mungkin melempar ialah

        hard_timeout = timeout_s or float(config.get("agent.task_timeout_s", 900))

    Ukuran langsung menjawabnya: ``timeout_s`` diteruskan pemanggil apa adanya,
    dan operator ``or`` berarti nilai truthy non-angka TIDAK pernah mencapai
    ``float()``. Jadi tidak ada raise sinkron — string itu lolos ke
    ``asyncio.wait_for`` dan baru meledak di DALAM worker sebagai
    ``TypeError: '<=' not supported between instances of 'str' and 'int'``,
    yaitu wilayah yang sudah dinaungi ``try/finally`` Fase 53.

    Karena itu berkas production tidak diubah: jalur ini terbukti TIDAK bocor.
    Tes ini dikembalikan ke bentuk karakterisasi yang mengunci invarian
    terukur itu, agar regresi kelak tertangkap.
    """
    from jarvis.agent.tasks import TaskRegistry, TaskStatus

    class SilentBus:
        def publish(self, *_args, **_kwargs):
            return None

    registry = TaskRegistry(bus=SilentBus(), max_concurrent=1, queue_max=2)
    _isolate_dispatch(monkeypatch, registry)
    delivered: dict = {}

    def on_error(text, **_kwargs):
        delivered["text"] = str(text)

    try:
        assert dispatch.dispatch_task(
            "offline timeout non-numeric",
            timeout_s="bukan angka",
            on_error=on_error,
        ) is not None, "dispatch seharusnya tetap mengembalikan task"

        assert _wait_until(lambda: dispatch.active_count() == 0, timeout=3.0), (
            "timeout non-numeric menggantung dan tidak pernah mencapai terminal"
        )

        views = registry.snapshot()
        measured = {
            "latency_active": latency.active_count(),
            "registry": [(view.id, view.status.value) for view in views],
            "registry_active": [view.id for view in registry.active()],
            "dispatch_active": dispatch.active_count(),
        }
        assert measured == {
            "latency_active": 0,
            "registry": [(views[0].id, TaskStatus.FAILED.value)],
            "registry_active": [],
            "dispatch_active": 0,
        }, (
            "Timeout non-numeric gagal di dalam worker setelah seluruh state "
            f"dibuka, dan cleanup tidak atomik: {measured}"
        )
        # Kegagalan memang harus sampai ke callback — bukan dilempar ke
        # pemanggil, tetapi juga tidak boleh ditelan diam-diam.
        assert "TypeError" in delivered.get("text", ""), (
            f"kegagalan timeout tidak pernah mencapai on_error: {delivered}"
        )
    finally:
        latency.reset()
        registry.clear()
        with dispatch._active_lock:
            dispatch._active.clear()


def test_system_exit_tidak_ditangkap_dan_state_tetap_bersih(monkeypatch):
    """``SystemExit`` HARUS dibiarkan merambat; state tetap harus bersih.

    Berbeda dari ``CancelledError`` (Fase 58) yang merupakan SEMANTIK pembatalan
    dan bagian normal asyncio, ``SystemExit``/``KeyboardInterrupt`` adalah sinyal
    KONTROL ALIR proses. Menangkapnya berarti menggagalkan shutdown: proses
    menolak mati karena tugasnya sibuk. Karena itu satu-satunya perilaku benar
    ialah membiarkannya lewat.

    Yang wajib tetap terjaga adalah keadaan: ``finally`` harus menutup turn,
    melepas slot, dan membersihkan ``_active`` meski ``SystemExit`` melewati
    semua penjaga ``except``. ``on_error`` memang tidak dipanggil — itu BENAR,
    karena shutdown bukan kegagalan tugas yang perlu dijelaskan ke pemakai.

    Tes ini mengukur keduanya: exception terbukti merambat (dibuktikan lewat
    ``threading.excepthook``, bukan sekadar tidak adanya error), dan tidak ada
    satu pun yatim tertinggal. Berkas production tidak diubah.
    """
    from jarvis.agent.tasks import TaskRegistry, TaskStatus

    class SilentBus:
        def publish(self, *_args, **_kwargs):
            return None

    async def exiting(*_args, **_kwargs):
        raise SystemExit("shutdown diminta")

    registry = TaskRegistry(bus=SilentBus(), max_concurrent=1, queue_max=2)
    _isolate_dispatch(monkeypatch, registry)
    monkeypatch.setattr("jarvis.agent.loop.run", exiting)

    propagated: list[tuple[str, str]] = []
    real_hook = threading.excepthook

    def spy_hook(args):
        propagated.append((args.exc_type.__name__, str(args.exc_value)[:80]))

    monkeypatch.setattr(threading, "excepthook", spy_hook)
    delivered: list[str] = []

    try:
        dispatch.dispatch_task(
            "offline system exit",
            on_error=lambda text, **_kwargs: delivered.append(str(text)),
        )

        assert _wait_until(lambda: dispatch.active_count() == 0, timeout=3.0), (
            "SystemExit membuat worker menggantung tanpa pernah terminal"
        )
        # Beri kesempatan excepthook berjalan, lalu ukur.
        time.sleep(0.3)

        # 1. Exception HARUS merambat — bukan ditelan penjaga yang baru.
        assert any(name == "SystemExit" for name, _ in propagated), (
            "SystemExit ditangkap oleh penjaga worker — shutdown proses akan "
            f"digagalkan. excepthook mencatat: {propagated}"
        )

        # 2. Keadaan HARUS bersih walau semua penjaga except dilewati.
        assert latency.active_count() == 0, (
            "SystemExit melewati penutup latency session.id"
        )
        views = registry.snapshot()
        measured = {
            "registry": [(view.id, view.status.value) for view in views],
            "registry_active": [view.id for view in registry.active()],
            "dispatch_active": dispatch.active_count(),
        }
        assert measured == {
            "registry": [(views[0].id, TaskStatus.FAILED.value)],
            "registry_active": [],
            "dispatch_active": 0,
        }, f"SystemExit meninggalkan yatim: {measured}"

        # 3. Shutdown bukan kegagalan tugas: wajar bila tidak ada penjelasan.
        assert delivered == [], (
            "SystemExit diperlakukan sebagai kegagalan tugas yang perlu "
            f"dijelaskan ke pemakai: {delivered}"
        )
    finally:
        monkeypatch.setattr(threading, "excepthook", real_hook)
        latency.reset()
        registry.clear()
        with dispatch._active_lock:
            dispatch._active.clear()


def test_base_exception_worker_tetap_menutup_turn_task_dan_aktif(monkeypatch):
    """``BaseException`` tidak boleh lolos dari penanganan terminal worker.

    Penjaga worker menangkap ``asyncio.TimeoutError`` lalu ``except Exception``.
    Tetapi ``asyncio.CancelledError`` sejak Python 3.8 adalah turunan
    ``BaseException``, BUKAN ``Exception`` — jadi ia melewati kedua penjaga itu
    dan hanya ditangani ``finally``.

    Akibatnya terukur: ``finally`` memang masih menutup state (jadi tidak ada
    yatim), tetapi terminal state yang tercatat hanyalah "selesai tanpa status"
    dan ``on_error`` TIDAK PERNAH dipanggil. Pemakai mendapat keheningan, bukan
    penjelasan — padahal task-nya gagal.

    RED ini mengukur dua hal sekaligus: keadaan akhir tetap bersih (agar
    perbaikan tidak mengorbankan Fase 53), dan kegagalan harus sungguh sampai
    ke callback terminal.
    """
    import asyncio

    from jarvis.agent.tasks import TaskRegistry, TaskStatus

    class SilentBus:
        def publish(self, *_args, **_kwargs):
            return None

    async def cancelled(*_args, **_kwargs):
        raise asyncio.CancelledError()

    registry = TaskRegistry(bus=SilentBus(), max_concurrent=1, queue_max=2)
    _isolate_dispatch(monkeypatch, registry)
    monkeypatch.setattr("jarvis.agent.loop.run", cancelled)
    delivered: list[str] = []

    # Pantau sesi agar pembatalan benar-benar terukur, bukan hanya diyakini.
    # Tanpa ini, mutan yang menghapus ``session.cancel()`` dari penjaga lolos.
    made: list = []
    real_session = session_module.Session

    class SpySession(real_session):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            made.append(self)

    monkeypatch.setattr("jarvis.agent.session.Session", SpySession)

    try:
        dispatch.dispatch_task(
            "offline base exception worker",
            on_error=lambda text, **_kwargs: delivered.append(str(text)),
        )

        assert _wait_until(lambda: dispatch.active_count() == 0, timeout=3.0), (
            "BaseException membuat worker menggantung tanpa pernah terminal"
        )
        assert latency.active_count() == 0, (
            "BaseException melewati penutup latency session.id"
        )

        views = registry.snapshot()
        assert [(view.id, view.status.value) for view in views] == [
            (views[0].id, TaskStatus.FAILED.value)
        ], f"task tidak mencapai terminal FAILED: {[(v.id, v.status.value) for v in views]}"
        assert registry.active() == [], "task BaseException masih aktif di registry"

        # Inti cacatnya: kegagalan harus sampai ke pemanggil, bukan sunyi.
        assert delivered, (
            "BaseException melewati penanganan terminal — on_error tidak pernah "
            "dipanggil dan pemakai hanya mendapat keheningan"
        )
        # CancelledError memang pembatalan, jadi pesannya wajar berbahasa
        # pemakai. Yang diuji adalah KETERANGAN itu sampai, dan tidak lagi
        # jatuh ke "selesai tanpa status" yang tidak menjelaskan apa pun.
        assert "dibatalkan" in delivered[0], (
            f"callback terminal tidak menjelaskan pembatalan: {delivered}"
        )
        # Pembatalan harus juga mencapai sesi agar loop lama berhenti bekerja,
        # bukan sekadar dicatat di registry.
        assert made, "spy sesi tidak menangkap apa pun — ukuran ini sia-sia"
        assert made[-1].cancelled, (
            "penjaga CancelledError tidak membatalkan sesi: loop lama bisa "
            "terus bekerja di balik task yang sudah terminal"
        )
    finally:
        latency.reset()
        registry.clear()
        with dispatch._active_lock:
            dispatch._active.clear()


def test_bus_publish_gagal_tidak_meninggalkan_turn_task_atau_active(monkeypatch):
    """Kegagalan publish di dalam jendela terbuka tidak boleh meninggalkan yatim.

    Jendela antara ``latency.start()`` (baris 1084) dan penjaga Fase 54/55
    (baris 1251) menyisakan satu panggilan terakhir yang bisa melempar:
    ``BUS.publish("agent.task.started", ...)``.

    ``EventBus.publish`` (``bus.py:54``) membungkus SETIAP subscriber dalam
    ``try/except``, jadi handler yang meledak tidak pernah merambat. Tetapi
    baris 64, ``self._ui_queue.put(...)``, berada DI LUAR penjaga itu. Bila
    antrean UI menolak item baru, exception merambat ke ``_dispatch`` — setelah
    turn dibuka, setelah registry submit, setelah ACK, dan sebelum worker
    memiliki kesempatan menjalankan satu baris pun.

    Fake di bawah membuat ``put`` melempar, mengembalikan ``BUS.publish`` asli
    yang distub ``_isolate_dispatch``, lalu mengukur tiga pemilik state yang
    sama agar hasilnya sebanding dengan Fase 54/55/56.
    """
    from jarvis.agent.tasks import TaskRegistry, TaskStatus
    from jarvis.core import bus as bus_module

    class SilentBus:
        def publish(self, *_args, **_kwargs):
            return None

    class ExplodingQueue:
        def put(self, *_args, **_kwargs):
            raise RuntimeError("fake antrean UI menolak item baru")

    registry = TaskRegistry(bus=SilentBus(), max_concurrent=1, queue_max=2)
    _isolate_dispatch(monkeypatch, registry)
    # _isolate_dispatch menstub BUS.publish; kembalikan yang asli agar jalur
    # nyata yang diukur, lalu ganti hanya antrean UI-nya.
    monkeypatch.setattr(dispatch.BUS, "publish", bus_module.EventBus.publish.__get__(
        dispatch.BUS, bus_module.EventBus))
    monkeypatch.setattr(dispatch.BUS, "_ui_queue", ExplodingQueue())
    monkeypatch.setattr(dispatch.BUS, "_ui_subs", {"agent.task.started": (lambda _d: None,)})

    try:
        with pytest.raises(RuntimeError,
                           match="fake antrean UI menolak item baru"):
            dispatch.dispatch_task("offline bus publish failure")

        views = registry.snapshot()
        measured = {
            "latency_active": latency.active_count(),
            "registry": [(view.id, view.status.value) for view in views],
            "registry_active": [view.id for view in registry.active()],
            "dispatch_active": dispatch.active_count(),
        }
        assert measured == {
            "latency_active": 0,
            "registry": [(views[0].id, TaskStatus.FAILED.value)],
            "registry_active": [],
            "dispatch_active": 0,
        }, (
            "BUS.publish gagal setelah seluruh state dibuka, tetapi cleanup "
            f"tidak atomik: {measured}"
        )
    finally:
        latency.reset()
        registry.clear()
        with dispatch._active_lock:
            dispatch._active.clear()
