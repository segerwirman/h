"""Browser session lease and dispatch cleanup contracts (Phase 2).

These tests deliberately use an in-memory host/page and an inline worker so
they never start Playwright, a browser process, a real worker thread, or the
network.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
import threading
from types import SimpleNamespace

import pytest

from jarvis.agent import dispatch
from jarvis.agent.loop import RunResult
from jarvis.agent.tools import browser


@dataclass(frozen=True)
class _LeaseSession:
    id: str


class _FakePage:
    def __init__(self) -> None:
        self.url = "about:blank"
        self.touches: list[tuple[str, str]] = []

    def goto(self, url: str, **_kwargs) -> None:
        self.touches.append(("goto", url))
        self.url = url

    def title(self) -> str:
        self.touches.append(("title", self.url))
        return "Fake page"


class _FakeLeaseHost:
    """Small contract fake for the public host lease boundary."""

    def __init__(self) -> None:
        self.page = _FakePage()
        self.owner = ""
        self.claims: list[str] = []
        self.releases: list[str] = []

    def claim_session(self, owner: str) -> None:
        owner = str(owner or "")
        self.claims.append(owner)
        if not owner:
            raise RuntimeError("browser lease requires a session owner")
        if self.owner and self.owner != owner:
            raise RuntimeError("browser is leased by another session")
        self.owner = owner

    def release_session(self, owner: str) -> None:
        owner = str(owner or "")
        self.releases.append(owner)
        if self.owner == owner:
            self.owner = ""

    def invalidate_snapshot(self) -> None:
        pass

    def call(self, fn, timeout: float = 60):
        del timeout
        return fn(self.page)


async def _inline_to_thread(fn, /, *args, **kwargs):
    return fn(*args, **kwargs)


def _run(coro):
    return asyncio.run(coro)


def test_stateful_browser_tool_holds_lease_until_public_release(monkeypatch):
    """A second session must be rejected before it can touch the page."""

    release = getattr(browser, "release_browser_session", None)
    assert callable(release), (
        "browser tools must expose release_browser_session(session_id)"
    )

    host = _FakeLeaseHost()
    monkeypatch.setattr(
        browser._BrowserHost, "get", classmethod(lambda cls: host)
    )
    monkeypatch.setattr(browser.asyncio, "to_thread", _inline_to_thread)

    tool = browser.BrowserNavigate()
    assert tool.wants_context is True
    session_a = _LeaseSession("session-a")
    session_b = _LeaseSession("session-b")

    first = _run(tool.run("https://example.test/a", _session=session_a))
    assert first.ok is True
    touches_after_first = list(host.page.touches)

    same_owner = _run(
        tool.run("https://example.test/a-again", _session=session_a)
    )
    assert same_owner.ok is True
    assert len(host.page.touches) > len(touches_after_first)
    touches_before_rejection = list(host.page.touches)

    with pytest.raises(RuntimeError, match="session|lease"):
        _run(tool.run("https://example.test/b", _session=session_b))
    assert host.page.touches == touches_before_rejection
    assert host.owner == "session-a"

    release("session-a")
    assert host.releases == ["session-a"]
    assert host.owner == ""

    after_release = _run(
        tool.run("https://example.test/b", _session=session_b)
    )
    assert after_release.ok is True
    assert host.owner == "session-b"
    assert host.claims == [
        "session-a",
        "session-a",
        "session-b",
        "session-b",
    ]


def test_subagent_browser_owner_is_inherited_from_parent(monkeypatch):
    from jarvis.agent.tools.delegate import DelegateTask
    from jarvis.agent import loop as agent_loop

    seen = {}

    async def fake_run(_task, *, session, **_kwargs):
        seen["owner"] = browser._owner_id(session)
        return RunResult(ok=True, text="done", session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)
    parent = SimpleNamespace(id="parent-session", is_subagent=False)

    result = _run(DelegateTask().run("subtask", _session=parent))

    assert result.ok is True
    assert seen["owner"] == "parent-session"


def test_release_cleans_snapshot_and_dialog_before_next_claim(monkeypatch):
    host = browser._BrowserHost()
    host.claim_session("session-a")
    host.set_dialog("accept", "secret answer")
    host.record_snapshot({"url": "https://a.test", "elements": []},
                         owner="session-a")

    cleanup_entered = threading.Event()
    allow_cleanup = threading.Event()
    session_b_claimed = threading.Event()
    original_invalidate = host.invalidate_snapshot

    def blocking_invalidate():
        cleanup_entered.set()
        assert allow_cleanup.wait(2)
        original_invalidate()

    monkeypatch.setattr(host, "invalidate_snapshot", blocking_invalidate)
    release_thread = threading.Thread(
        target=host.release_session, args=("session-a",))
    release_thread.start()
    assert cleanup_entered.wait(2)

    def claim_b():
        host.claim_session("session-b")
        session_b_claimed.set()

    claim_thread = threading.Thread(target=claim_b)
    claim_thread.start()
    assert not session_b_claimed.wait(0.05)

    allow_cleanup.set()
    release_thread.join(2)
    claim_thread.join(2)

    assert not release_thread.is_alive()
    assert not claim_thread.is_alive()
    assert session_b_claimed.is_set()
    assert host._lease_owner == "session-b"
    assert host._dialog_action is None
    assert host._snapshot_ready is False


class _ClosingRaceHost(browser._BrowserHost):
    """Controlled lifecycle: generation one closes, generation two works."""

    def __init__(self):
        super().__init__()
        self.generation = 0
        self.allow_close = threading.Event()
        self.closing = threading.Event()
        self.allow_finish = threading.Event()

    def _main(self):
        self.generation += 1
        generation = self.generation
        page = SimpleNamespace(generation=generation)
        with self._lock:
            self._state = "accepting"
        self._started.set()
        try:
            if generation == 1:
                assert self.allow_close.wait(2)
                with self._lock:
                    self._state = "closing"
                self.closing.set()
                assert self.allow_finish.wait(2)
                return
            fn, future = self._jobs.get(timeout=2)
            future.set_result(fn(page))
        finally:
            with self._lock:
                self._state = "stopped"
                self._thread = None


def test_call_does_not_enqueue_stale_job_during_idle_close():
    host = _ClosingRaceHost()
    host._ensure()
    host.allow_close.set()
    assert host.closing.wait(2)

    finished = threading.Event()
    result = {}

    def caller():
        result["generation"] = host.call(
            lambda page: page.generation, timeout=2)
        finished.set()

    caller_thread = threading.Thread(target=caller)
    caller_thread.start()
    assert not finished.wait(0.05)
    assert host._jobs.empty()

    host.allow_finish.set()
    caller_thread.join(3)

    assert not caller_thread.is_alive()
    assert result["generation"] == 2
    assert host.generation == 2
    assert host._jobs.empty()


class _InlineThread:
    """Drop-in Thread subset that runs the dispatch worker synchronously."""

    def __init__(self, *, target, **_kwargs) -> None:
        self._target = target

    def start(self) -> None:
        self._target()


@pytest.mark.parametrize("outcome", ["success", "failure", "timeout"])
def test_dispatch_releases_browser_lease_for_every_terminal_outcome(
        monkeypatch, outcome):
    release = getattr(browser, "release_browser_session", None)
    assert callable(release), (
        "browser tools must expose release_browser_session(session_id)"
    )

    from jarvis.agent import loop as agent_loop
    from jarvis.agent import session as session_module

    events: list[str] = []
    created_sessions = []

    class _FakeSession:
        def __init__(self, task: str, adapter_name: str) -> None:
            self.task = task
            self.adapter_name = adapter_name
            self.id = f"dispatch-{outcome}"
            self.cancelled = False
            self.finished: list[tuple[str, bool]] = []
            created_sessions.append(self)

        def cancel(self) -> None:
            self.cancelled = True

        def finish(self, result: str, ok: bool = True) -> None:
            # Fase 68 — double ini ketinggalan kontrak ``Session``. Ketiadaan
            # metode ini membuat test LOLOS sebelum perbaikan produksi (jalan
            # timeout tidak memanggilnya) lalu GAGAL sesudahnya, meski
            # perbaikan itu benar. Sebuah fake yang tidak memodelkan kontrak
            # akan mendeteksi perubahan yang salah pada saat yang salah.
            self.finished.append((str(result), bool(ok)))

    async def fake_agent_loop(_task, **_kwargs):
        if outcome == "timeout":
            raise asyncio.TimeoutError
        return RunResult(
            ok=outcome == "success",
            text="done" if outcome == "success" else "failed",
            session_id=f"dispatch-{outcome}",
        )

    def fake_release(session_id: str) -> None:
        events.append(f"release:{session_id}")

    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(dispatch, "render_ack", lambda _task: "ACK")
    monkeypatch.setattr(dispatch.BUS, "publish", lambda *args, **kwargs: None)
    monkeypatch.setattr(dispatch.threading, "Thread", _InlineThread)
    monkeypatch.setattr(session_module, "Session", _FakeSession)
    monkeypatch.setattr(agent_loop, "run", fake_agent_loop)
    monkeypatch.setattr(browser, "release_browser_session", fake_release)
    with dispatch._active_lock:
        dispatch._active.clear()

    started = dispatch.dispatch_async(
        f"browser lease terminal {outcome}",
        adapter=SimpleNamespace(name="lease-test"),
        timeout_s=0.01,
        on_done=lambda _text: events.append("done"),
        on_error=lambda _text: events.append("error"),
    )

    assert started is True
    assert len(created_sessions) == 1
    expected_terminal = "done" if outcome == "success" else "error"
    assert events == [
        expected_terminal,
        f"release:dispatch-{outcome}",
    ]
    assert created_sessions[0].cancelled is (outcome == "timeout")
    # Fase 68 — sesi yang berakhir GAGAL atau TIMEOUT wajib ditutup sebagai
    # gagal. Tanpa ini baris arsipnya tetap ``ended_at=None`` dan permukaan
    # kelola membacanya "running" selamanya.
    if outcome == "success":
        assert created_sessions[0].finished == [], (
            "task ini tidak berkontrak, jadi penutupannya ada di loop.run — "
            "dispatch tidak boleh menutupnya dua kali")
    else:
        assert created_sessions[0].finished, (
            f"sesi outcome '{outcome}' tidak pernah ditutup — operator akan "
            "melihatnya menggantung selamanya di permukaan kelola")
        _result, ok = created_sessions[0].finished[-1]
        assert ok is False, (
            f"sesi outcome '{outcome}' ditutup sebagai SUKSES padahal gagal")
    assert dispatch.active_count() == 0
