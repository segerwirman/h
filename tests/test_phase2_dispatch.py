"""Native dispatch lifecycle and YouTube evidence integration (Phase 2)."""
from __future__ import annotations

import threading
import time

import pytest

from jarvis.agent import dispatch
from jarvis.agent.base import ToolResult
from jarvis.agent.loop import RunResult
from jarvis.agent.task_contracts import detect_youtube_latest_play


TASK = "buka dan putar youtube deddy corbuzier terbaru"


def _wait(event: threading.Event) -> None:
    assert event.wait(2), "callback dispatch tidak selesai"


def _isolate(monkeypatch) -> None:
    monkeypatch.setattr(dispatch, "available", lambda: True)
    monkeypatch.setattr(dispatch, "render_ack", lambda _task: "ACK")
    monkeypatch.setattr(dispatch.BUS, "publish", lambda *a, **k: None)
    from jarvis.agent.tasks import REGISTRY
    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()


def _wait_dispatch_idle(timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if dispatch.active_count() == 0:
            return
        time.sleep(0.005)
    pytest.fail("dispatch worker tidak idle setelah terminal callback")


def _finish_dispatch_isolation() -> None:
    from jarvis.agent.tasks import REGISTRY
    _wait_dispatch_idle()
    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()


@pytest.fixture(autouse=True)
def _clean_dispatch_state():
    yield
    _finish_dispatch_isolation()


def test_native_ack_happens_before_worker_and_report_after(monkeypatch):
    _isolate(monkeypatch)
    from jarvis.agent import loop as agent_loop

    events: list[str] = []
    done = threading.Event()

    async def fake_run(task, **_kwargs):
        events.append("work")
        return RunResult(ok=True, text="Laporan konkret tersimpan.",
                         session_id="phase2")

    monkeypatch.setattr(agent_loop, "run", fake_run)

    started = dispatch.dispatch_async(
        "tolong riset dan buat laporan",
        on_ack=lambda _ack: events.append("ack"),
        on_done=lambda _result: (events.append("report"), done.set()),
    )

    assert started is True
    _wait(done)
    assert events == ["ack", "work", "report"]


def test_seam_bind_cleanup_is_required_before_following_phase2_dispatch(
        monkeypatch):
    """Characterize the seam-bind → phase2 ordering boundary.

    Waiting only for ``dispatch_async`` to return is insufficient: it returns
    before the worker starts. The terminal callback is the synchronization
    point, followed by the active-handle drain and registry cleanup.
    """
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.tasks import REGISTRY

    _isolate(monkeypatch)
    events: list[str] = []
    seam_done = threading.Event()
    phase_done = threading.Event()

    async def seam_run(_task, **_kwargs):
        return RunResult(ok=True, text="seam selesai", session_id="seam-bind")

    monkeypatch.setattr(agent_loop, "run", seam_run)
    with dispatch.source_scope(
        "voice-native", completion_owner="registry", conversation_id="voice-live"
    ):
        assert dispatch.dispatch_async(
            "seam bind task", on_done=lambda _result: seam_done.set()
        ) is True

    _wait(seam_done)
    _wait_dispatch_idle()
    assert len(REGISTRY.snapshot()) == 1

    REGISTRY.clear()
    with dispatch._active_lock:
        dispatch._active.clear()

    async def phase2_run(_task, **_kwargs):
        events.append("work")
        return RunResult(ok=True, text="fase dua selesai", session_id="phase2")

    monkeypatch.setattr(agent_loop, "run", phase2_run)
    assert dispatch.dispatch_async(
        "tolong riset dan buat laporan",
        on_ack=lambda _ack: events.append("ack"),
        on_done=lambda _result: (events.append("report"), phase_done.set()),
    ) is True
    _wait(phase_done)
    assert events == ["ack", "work", "report"]


def test_unavailable_native_agent_does_not_emit_false_ack(monkeypatch):
    _isolate(monkeypatch)
    monkeypatch.setattr(dispatch, "available", lambda: False)
    events: list[str] = []

    started = dispatch.dispatch_async(
        "tolong riset dan buat laporan",
        on_ack=lambda _ack: events.append("ack"),
        on_done=lambda _result: events.append("done"),
        on_error=lambda _error: events.append("error"),
    )

    assert started is False
    assert events == []


def _search_snapshot(contract) -> ToolResult:
    snapshot = {
        "url": contract.search_url,
        "title": "YouTube search",
        "text": "Hasil diurutkan menurut tanggal upload",
        "elements": [
            {"ref": "j2", "tag": "a", "text": "Tidak resmi"},
            {"ref": "j7", "tag": "a", "text": "Episode terbaru"},
            {"ref": "j9", "tag": "a", "text": "Episode lama"},
        ],
        "youtube_results": [
            {"rank": 1, "ref": "j2", "title": "Reupload baru",
             "channel": "Deddy Corbuzier",
             "channel_id": "UC-Fan",
             "channel_href": "https://youtube.com/channel/UC-Fan",
             "verified": False, "age": "1 hour ago",
             "href": "/watch?v=fan"},
            {"rank": 2, "ref": "j7", "title": "Episode terbaru",
             "channel": "Deddy Corbuzier",
             "channel_id": "UC-Deddy-Official",
             "channel_href": (
                 "https://youtube.com/channel/UC-Deddy-Official"),
             "verified": True, "age": "2 hours ago",
             "href": "/watch?v=new"},
            {"rank": 3, "ref": "j9", "title": "Episode lama",
             "channel": "Deddy Corbuzier",
             "channel_id": "UC-Deddy-Official",
             "channel_href": (
                 "https://youtube.com/channel/UC-Deddy-Official"),
             "verified": True, "age": "3 days ago",
             "href": "/watch?v=old"},
        ],
    }
    return ToolResult.success("snapshot hasil YouTube", snapshot=snapshot)


def _watch_snapshot() -> ToolResult:
    snapshot = {
        "url": "https://www.youtube.com/watch?v=new",
        "title": "Episode terbaru",
        "text": "Episode terbaru — Deddy Corbuzier official channel",
        "elements": [{"ref": "j1", "tag": "button", "text": "Play"}],
        "youtube_results": [],
        "youtube_watch": {
            "video_id": "new",
            "channel_name": "Deddy Corbuzier",
            "channel_id": "UC-Deddy-Official",
            "channel_href": (
                "https://youtube.com/channel/UC-Deddy-Official"),
            "title": "Episode terbaru",
        },
    }
    return ToolResult.success("snapshot watch Deddy Corbuzier",
                              snapshot=snapshot)


def _record_valid_youtube_trace(session, events: list[str]):
    contract = detect_youtube_latest_play(TASK)

    def record(name, args, result):
        events.append(name)
        # Kanal produksi (S-12): registry menyerahkan hasil UTUH ke
        # record_evidence, dan hasil yang SUDAH DIREDAKSI ke record_tool.
        # Menyuapi bukti lewat record_tool membuat tes ini hijau sementara
        # jalur nyata mustahil lolos.
        session.record_tool(name, args, result, 0.01)
        session.record_evidence(name, args, result)

    record("browser_navigate", {"url": contract.search_url},
           ToolResult.success("terbuka"))
    record("browser_snapshot", {}, _search_snapshot(contract))
    record("browser_click", {"ref": "j7"}, ToolResult.success("diklik"))
    record("browser_snapshot", {}, _watch_snapshot())
    record("browser_media", {
        "action": "play", "expected_video_id": "new",
    }, ToolResult.success({
        "url": "https://www.youtube.com/watch?v=new",
        "found": True,
        "paused": False,
        "ended": False,
        "readyState": 4,
        "currentTime": 2.1,
        "timeAdvanced": True,
        "playing": True,
        "targetVideoId": "new",
        "pageVideoId": "new",
        "playerVideoId": "new",
        "targetMatched": True,
        "isAd": False,
    }))


def test_youtube_sukses_menutup_sesi_dengan_hasil_terverifikasi(monkeypatch):
    """Sesi sukses yang BERKONTRAK wajib ditutup dengan hasil terverifikasi.

    RED untuk Fase 66. Uji mutasi membuktikan ``session.finish(text, ok=True)``
    pada ``dispatch.py:1209`` bisa dihapus ATAU nilainya diubah tanpa satu test
    pun berkedip — padahal ``Session.finish`` menulis ``ended_at``, ``result``,
    dan ``ok`` ke ``agent_sessions``, yang menjadi sumber ``session_search``.

    Mengapa ia tidak pernah ketahuan: ``_isolate`` di file ini (baris 243) dan
    fixture ``wired`` di test_command_plan men-stub ``Session.finish`` menjadi
    no-op. Stub itu membuat jalur sukses kebal terhadap kebocoran — pola yang
    sama dengan ``_isolate_dispatch`` pada Fase 64.

    Catatan batas: ``dispatch.py`` hanya memanggil ``session.finish`` untuk
    task BERKONTRAK. Task tanpa kontrak ditutup oleh ``loop.py:323``. Karena
    itu RED ini memakai task YouTube, bukan task biasa, agar benar-benar
    menempuh baris 1209.
    """
    _isolate(monkeypatch)
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.session import Session

    finishes: list[tuple[str, bool]] = []
    monkeypatch.setattr(
        Session, "finish",
        lambda self, result, ok=True: finishes.append((str(result), bool(ok))),
    )
    events: list[str] = []
    observed: dict[str, object] = {}
    done = threading.Event()

    async def fake_run(task, *, adapter, session, allowed_tools, **_kwargs):
        _record_valid_youtube_trace(session, events)
        await adapter.send("Selesai.")
        return RunResult(ok=True, text="Selesai.", session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)

    assert dispatch.dispatch_async(
        TASK,
        on_done=lambda result: (observed.__setitem__("result", result),
                                done.set()),
        on_error=lambda error: (observed.__setitem__("error", error),
                                done.set()),
    ) is True
    _wait(done)

    # 1. Sesi HARUS ditutup pada jalur sukses berkontrak.
    assert finishes, (
        "sesi sukses tidak pernah ditutup — ended_at/result/ok tidak akan "
        "pernah tercatat di agent_sessions dan session_search kehilangan jejak"
    )

    # 2. Ditutup sebagai SUKSES, bukan gagal.
    result, ok = finishes[-1]
    assert ok is True, f"sesi sukses ditutup dengan ok={ok}"

    # 3. Yang tertulis adalah hasil TERVERIFIKASI kontrak, bukan klaim model.
    #    Klaim modelnya adalah "Selesai."; hasil terverifikasi menyebut
    #    channel dan kata "diputar".
    assert result != "Selesai.", (
        "sesi ditutup dengan klaim model mentah, bukan hasil terverifikasi "
        f"kontrak: {result!r}"
    )
    assert "Deddy Corbuzier" in result.title(), (
        f"hasil sesi tidak menyebut channel target: {result!r}"
    )
    assert result == str(observed.get("result")), (
        f"hasil yang ditulis ke sesi tidak sama dengan yang dikirim pemanggil: "
        f"{result!r} vs {observed.get('result')!r}"
    )


def test_youtube_dispatch_restricts_schema_and_reports_only_after_evidence(
        monkeypatch):
    _isolate(monkeypatch)
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.session import Session

    monkeypatch.setattr(Session, "finish", lambda *a, **k: None)
    events: list[str] = []
    observed: dict[str, object] = {}
    done = threading.Event()

    async def fake_run(task, *, adapter, session, allowed_tools, **_kwargs):
        events.append("work")
        observed["task"] = task
        observed["tools"] = tuple(allowed_tools)
        _record_valid_youtube_trace(session, events)
        await adapter.send("Selesai.")
        return RunResult(ok=True, text="Selesai.", session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)

    started = dispatch.dispatch_async(
        TASK,
        on_ack=lambda _ack: events.append("ack"),
        on_done=lambda result: (
            observed.__setitem__("result", result),
            events.append("report"),
            done.set(),
        ),
        on_error=lambda error: (
            observed.__setitem__("error", error), done.set()),
    )

    assert started is True
    _wait(done)
    tools = set(observed["tools"])
    assert {"browser_navigate", "browser_snapshot", "browser_click",
            "browser_media"} <= tools
    assert not ({"open_app", "youtube_video", "computer_type", "terminal"}
                & tools)
    assert "KONTRAK YOUTUBE_LATEST_PLAY" in str(observed["task"])
    assert events.index("ack") < events.index("work")
    assert events.index("browser_media") < events.index("report")
    assert "Deddy Corbuzier" in str(observed["result"]).title()
    assert "diputar" in str(observed["result"]).casefold()
    assert "error" not in observed


def test_youtube_model_success_is_rejected_without_playback_evidence(
        monkeypatch):
    _isolate(monkeypatch)
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.session import Session

    monkeypatch.setattr(Session, "finish", lambda *a, **k: None)
    terminal: dict[str, str] = {}
    done = threading.Event()

    async def fake_run(_task, *, adapter, session, **_kwargs):
        await adapter.send("Video sudah diputar.")
        session.record_evidence(
            "browser_navigate", {"url": "https://youtube.com"},
            ToolResult.success("terbuka"))
        return RunResult(ok=True, text="Video sudah diputar.",
                         session_id=session.id)

    monkeypatch.setattr(agent_loop, "run", fake_run)

    assert dispatch.dispatch_async(
        TASK,
        on_done=lambda result: (terminal.__setitem__("done", result),
                                done.set()),
        on_error=lambda error: (terminal.__setitem__("error", error),
                                done.set()),
    )
    _wait(done)

    assert "done" not in terminal
    assert "Verifikasi alur YouTube gagal" in terminal["error"]
    assert "sudah diputar" not in terminal["error"].casefold()
