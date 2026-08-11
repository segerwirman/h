"""Phase 15B — canonical runtime owns bounded shutdown."""
from __future__ import annotations


def test_supervisor_menutup_callback_terbalik_dan_idempoten():
    from jarvis.runtime.supervisor import RuntimeSupervisor

    events = []
    supervisor = RuntimeSupervisor()
    supervisor.add_stop("first", lambda: events.append("first"))
    supervisor.add_stop("second", lambda: events.append("second"))

    supervisor.shutdown()
    supervisor.shutdown()

    assert events == ["second", "first"]


def test_supervisor_tetap_menutup_lainnya_saat_callback_gagal():
    from jarvis.runtime.supervisor import RuntimeSupervisor

    events = []
    supervisor = RuntimeSupervisor()
    supervisor.add_stop("first", lambda: events.append("first"))

    def broken():
        events.append("broken")
        raise RuntimeError("expected")

    supervisor.add_stop("broken", broken)
    supervisor.shutdown()

    assert events == ["broken", "first"]


def test_supervisor_join_thread_hidup_dengan_timeout_bounded():
    from jarvis.runtime.supervisor import RuntimeSupervisor

    class Thread:
        def __init__(self):
            self.joined = []

        def is_alive(self):
            return True

        def join(self, timeout):
            self.joined.append(timeout)

    thread = Thread()
    supervisor = RuntimeSupervisor(join_timeout=0.25)
    supervisor.add_thread("voice", thread)

    supervisor.shutdown()

    assert thread.joined == [0.25]


def test_supervisor_thread_tidak_daemon():
    from jarvis.runtime.supervisor import RuntimeSupervisor

    supervisor = RuntimeSupervisor()

    assert supervisor.thread_daemon is False


def test_canonical_main_mengekspos_supervisor_runtime_dan_ui_factory():
    import inspect
    from jarvis import main
    from jarvis.runtime.supervisor import RuntimeSupervisor

    assert main.RuntimeSupervisor is RuntimeSupervisor
    assert "ui_factory" in inspect.signature(main.run).parameters


def test_whatsapp_shutdown_registration_does_not_create_browser(monkeypatch):
    from jarvis import main
    from jarvis.integrations import whatsapp_web
    from jarvis.runtime.supervisor import RuntimeSupervisor

    calls = []
    monkeypatch.setattr(
        whatsapp_web.WhatsAppWebService,
        "get",
        classmethod(lambda cls: calls.append("get")),
    )
    monkeypatch.setattr(
        whatsapp_web,
        "shutdown_existing",
        lambda: calls.append("shutdown"),
    )
    supervisor = RuntimeSupervisor()

    main._register_whatsapp_shutdown(supervisor)

    assert calls == []
    supervisor.shutdown()
    assert calls == ["shutdown"]


def test_legacy_voice_memiliki_request_stop_idempoten():
    import main as legacy

    live = object.__new__(legacy.JarvisLive)
    live._stop_requested = None
    live._async_stop = None

    live.request_stop()
    live.request_stop()

    assert live._stop_requested.is_set()


async def _voice_run_stops_before_client(monkeypatch):
    import main as legacy

    live = object.__new__(legacy.JarvisLive)
    live._stop_requested = None
    live._async_stop = None
    live.ui = type("UI", (), {"set_state": lambda *_args: None})()
    live.request_stop()

    await live.run()


def test_legacy_voice_run_berhenti_sebelum_membuat_client(monkeypatch):
    import asyncio

    asyncio.run(_voice_run_stops_before_client(monkeypatch))


def test_voice_launcher_mengembalikan_thread_non_daemon_tanpa_menjalankan_legacy(monkeypatch):
    import threading
    from jarvis import main

    calls = []
    monkeypatch.setattr(threading.Thread, "start", lambda self: calls.append(self))

    thread = main._start_voice_pipeline(object())

    assert thread.name == "jarvis-live"
    assert thread.daemon is False
    assert callable(thread.request_stop)
    assert calls == [thread]
