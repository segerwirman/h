"""Task 1 — Telegram inter-process poller lease (offline, injected fs/PID/clock)."""
from __future__ import annotations

import threading
import time

import pytest

from jarvis.integrations.poller_lease import (
    DEFAULT_STALE_SECONDS,
    LeaseAcquireResult,
    PollerLease,
)


class FakePid:
    """PID milik satu proses; registry alive BERSAMA antar instance
    (simulasi satu OS — PID A terlihat hidup oleh proses B)."""

    alive: set[int] = set()

    def __init__(self, me: int = 100):
        self.me = me
        FakePid.alive.add(me)

    def __call__(self) -> int:
        return self.me

    @classmethod
    def checker(cls):
        def _alive(pid: int) -> bool:
            return pid in cls.alive
        return _alive

    @classmethod
    def kill(cls, pid: int) -> None:
        cls.alive.discard(pid)


class FakeClock:
    def __init__(self, start: float = 1_000_000.0):
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def make_lease(tmp_path, fake_pid: FakePid, clock: FakeClock, **kw):
    return PollerLease(
        tmp_path / "telegram_poller.lease",
        incarnation=f"{fake_pid.me}-test",
        pid_fn=fake_pid,
        now_fn=clock,
        alive_fn=FakePid.checker(),
        **kw,
    )


@pytest.fixture(autouse=True)
def _reset_fake_os():
    """Registry PID bersama adalah class-level — reset tiap test."""
    FakePid.alive.clear()
    yield
    FakePid.alive.clear()


def test_two_fake_processes_contend_first_wins(tmp_path):
    """Proses A acquire; proses B gagal cepat dengan lease_held (no storm)."""
    pid_a, pid_b = FakePid(100), FakePid(200)
    clock = FakeClock()
    lease_a = make_lease(tmp_path, pid_a, clock)
    lease_b = make_lease(tmp_path, pid_b, clock)

    res_a = lease_a.acquire()
    assert res_a.acquired and res_a.lease is lease_a
    assert res_a.reason == "acquired"

    res_b = lease_b.acquire()
    assert not res_b.acquired
    assert res_b.reason == "lease_held"
    assert res_b.lease is None
    # Tidak ada file kedua, tidak ada retry tersimpan.
    assert lease_a.held and not lease_b.held


def test_stale_lease_dead_pid_taken_over(tmp_path):
    """Lease milik PID mati → diambil alih (stale_taken_over)."""
    pid_a, pid_b = FakePid(100), FakePid(200)
    clock = FakeClock()
    lease_a = make_lease(tmp_path, pid_a, clock, stale_seconds=60.0)
    assert lease_a.acquire().acquired
    # Simulasi crash proses A: PID mati, file tertinggal.
    FakePid.kill(100)
    clock.advance(61.0)

    res = make_lease(tmp_path, pid_b, clock, stale_seconds=60.0).acquire()
    assert res.acquired
    assert res.reason == "stale_taken_over"
    # Pemilik baru tercatat.
    text = (tmp_path / "telegram_poller.lease").read_text(encoding="utf-8")
    assert "pid=200" in text


def test_live_pid_lease_never_stolen(tmp_path):
    """Lease milik PID hidup tidak pernah diambil walau umur melebihi stale."""
    pid_a, pid_b = FakePid(100), FakePid(200)
    clock = FakeClock()
    lease_a = make_lease(tmp_path, pid_a, clock, stale_seconds=60.0)
    assert lease_a.acquire().acquired
    clock.advance(3600.0)  # jauh melewati stale

    res = make_lease(tmp_path, pid_b, clock, stale_seconds=60.0).acquire()
    assert not res.acquired
    assert res.reason == "lease_held"
    # File tetap milik A.
    text = (tmp_path / "telegram_poller.lease").read_text(encoding="utf-8")
    assert "pid=100" in text


def test_unverifiable_pid_young_lease_fails_closed(tmp_path):
    """PID tak bisa diverifikasi + lease muda → gagal tertutup (jangan curi)."""
    pid_b = FakePid(200)
    clock = FakeClock()
    path = tmp_path / "telegram_poller.lease"
    # Simulasi: file sudah ada, pemilik tak terverifikasi (alive_fn=None).
    path.write_text(f"pid=999999\nincarnation=unknown\n"
                    f"written={clock()}\n", encoding="utf-8")

    res = PollerLease(path, incarnation="200-x", pid_fn=pid_b,
                      now_fn=clock, alive_fn=lambda p: None,
                      stale_seconds=60.0).acquire()
    assert not res.acquired
    assert res.reason == "lease_held"


def test_unverifiable_pid_old_lease_taken_over(tmp_path):
    """PID tak terverifikasi + umur > stale → ambil alih."""
    pid_b = FakePid(200)
    clock = FakeClock()
    path = tmp_path / "telegram_poller.lease"
    path.write_text(f"pid=999999\nincarnation=unknown\n"
                    f"written={clock()}\n", encoding="utf-8")
    clock.advance(3600.0)

    res = PollerLease(path, incarnation="200-x", pid_fn=pid_b,
                      now_fn=clock, alive_fn=lambda p: None,
                      stale_seconds=60.0).acquire()
    assert res.acquired


def test_corrupt_metadata_treated_as_stale(tmp_path):
    """Metadata tidak parseable (tanpa pid valid) → file invalid.

    Keputusan desain: file yang TIDAK BISA diverifikasi pemiliknya
    diperlakukan sama dengan file tak terbaca — fail closed
    (``lease_held``), BUKAN diambil alih. Pengambilan alih hanya untuk
    lease yang jelas terlantar (PID mati) atau tak terverifikasi + tua.
    """
    pid_b = FakePid(200)
    clock = FakeClock()
    path = tmp_path / "telegram_poller.lease"
    path.write_text("garbage-not-parseable", encoding="utf-8")

    res = PollerLease(path, incarnation="200-x", pid_fn=pid_b,
                      now_fn=clock, alive_fn=FakePid.checker(),
                      stale_seconds=0.0).acquire()
    assert not res.acquired
    assert res.reason == "lease_held"


def test_race_between_two_creators(tmp_path):
    """Balapan create-exclusive: hanya satu proses yang menang."""
    pid_a, pid_b = FakePid(100), FakePid(200)
    clock = FakeClock()
    path = tmp_path / "telegram_poller.lease"
    winner_flag = []
    start_barrier = threading.Barrier(2)

    def contender(lease):
        start_barrier.wait()
        res = lease.acquire()
        winner_flag.append(res.acquired)

    lease_a = PollerLease(path, incarnation="100-a", pid_fn=pid_a,
                          now_fn=clock, alive_fn=FakePid.checker())
    lease_b = PollerLease(path, incarnation="200-b", pid_fn=pid_b,
                          now_fn=clock, alive_fn=FakePid.checker())
    t1 = threading.Thread(target=contender, args=(lease_a,))
    t2 = threading.Thread(target=contender, args=(lease_b,))
    t1.start(); t2.start(); t1.join(); t2.join()

    assert winner_flag.count(True) == 1


def test_release_then_reacquire(tmp_path):
    pid = FakePid(300)
    clock = FakeClock()
    lease = make_lease(tmp_path, pid, clock)
    assert lease.acquire().acquired
    lease.release()
    assert not lease.held
    res = lease.acquire()
    assert res.acquired
    lease.release()


def test_release_refuses_foreign_lease(tmp_path):
    """Release tidak menghapus file milik inkarnasi lain."""
    pid_a, pid_b = FakePid(100), FakePid(200)
    clock = FakeClock()
    lease_a = make_lease(tmp_path, pid_a, clock)
    assert lease_a.acquire().acquired
    # B menganggap dirinya memegang (state rusak) lalu release — file A aman.
    lease_b = make_lease(tmp_path, pid_b, clock)
    lease_b._held = True  # state korup disimulasikan
    lease_b.release()
    path = tmp_path / "telegram_poller.lease"
    assert path.exists()
    assert "pid=100" in path.read_text(encoding="utf-8")


def test_lease_metadata_never_contains_token_material(tmp_path):
    """Keamanan: metadata lease hanya PID + incarnation — tanpa token/URL."""
    pid = FakePid(400)
    clock = FakeClock()
    lease = make_lease(tmp_path, pid, clock)
    assert lease.acquire().acquired
    text = (tmp_path / "telegram_poller.lease").read_text(encoding="utf-8")
    # Pola kredensial Telegram bot token: "<digits>:<A-Za-z0-9_-35>".
    import re
    token_pattern = re.compile(r"\b\d{8,10}:[A-Za-z0-9_-]{35}\b")
    assert not token_pattern.search(text)
    assert "https://" not in text and "http://" not in text
    assert "token" not in text.lower()


def test_default_stale_seconds_sane():
    assert DEFAULT_STALE_SECONDS >= 3600  # minimal 1 jam


def test_double_acquire_same_object_is_idempotent(tmp_path):
    pid = FakePid(500)
    clock = FakeClock()
    lease = make_lease(tmp_path, pid, clock)
    first = lease.acquire()
    second = lease.acquire()
    assert first.acquired and second.acquired
    assert second.lease is lease


def test_acquire_result_shape():
    res = LeaseAcquireResult(True, None, "acquired")
    assert res.acquired and res.reason == "acquired"
