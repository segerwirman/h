"""WhatsApp Web automation safety and routing contracts."""
from __future__ import annotations

from concurrent.futures import Future
import json
import threading
from types import SimpleNamespace

import pytest


@pytest.fixture
def contact_file(tmp_path, monkeypatch):
    from jarvis.integrations import whatsapp_web

    path = tmp_path / "contacts.json"
    path.write_text(
        json.dumps(
            {
                "contacts": [
                    {
                        "name": "Ibu",
                        "phone": "628123456789",
                        "allowed": True,
                    },
                    {
                        "name": "Belum Diizinkan",
                        "phone": "628987654321",
                        "allowed": False,
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(whatsapp_web, "_contacts_path", lambda: path)
    return path


def test_contact_resolution_is_exact_and_allowlisted(contact_file):
    from jarvis.integrations.whatsapp_web import resolve_contact

    resolved = resolve_contact("ibu")
    assert resolved.name == "Ibu"
    assert resolved.phone == "628123456789"


def test_contact_resolution_tolerates_unique_stt_error(contact_file, monkeypatch):
    from jarvis.integrations import whatsapp_web

    real_get = whatsapp_web.config.get
    monkeypatch.setattr(
        whatsapp_web.config,
        "get",
        lambda path, default=None: (
            0.68
            if path == "whatsapp_web.contact_fuzzy_threshold"
            else real_get(path, default)
        ),
    )
    assert whatsapp_web.resolve_contact("ibuu").name == "Ibu"


def test_contact_resolution_rejects_unapproved_contact(contact_file):
    from jarvis.integrations.whatsapp_web import (
        WhatsAppError,
        resolve_contact,
    )

    with pytest.raises(WhatsAppError, match="belum diizinkan"):
        resolve_contact("Belum Diizinkan")


def test_direct_number_is_default_deny(contact_file, monkeypatch):
    from jarvis.integrations import whatsapp_web

    real_get = whatsapp_web.config.get
    monkeypatch.setattr(
        whatsapp_web.config,
        "get",
        lambda path, default=None: (
            False
            if path == "whatsapp_web.allow_direct_numbers"
            else real_get(path, default)
        ),
    )
    with pytest.raises(whatsapp_web.WhatsAppError, match="allowlist"):
        whatsapp_web.resolve_contact("628111111111")


def test_tools_require_confirmation_for_external_actions(contact_file,
                                                        monkeypatch):
    """Fase 16 membuat gerbang panggilan bergantung mode, jadi mode dipilih
    eksplisit di sini. Tanpa itu test ini lulus hanya karena "Ibu" kebetulan
    tidak ada di allowlist nyata — lulus tanpa menguji apa pun."""
    from jarvis.agent.tools import whatsapp_web as tool_mod
    from jarvis.agent.tools.whatsapp_web import (
        WhatsAppAnswer,
        WhatsAppCall,
        WhatsAppHangup,
        WhatsAppSendMessage,
    )

    real = tool_mod.config
    monkeypatch.setattr(tool_mod, "config", type("_S", (), {
        "get": staticmethod(
            lambda path, default=None:
            "always" if path == "whatsapp_web.call_confirmation"
            else real.get(path, default)),
    })())

    assert WhatsAppCall().needs_confirmation(contact="Ibu")
    assert WhatsAppAnswer().needs_confirmation()
    assert WhatsAppSendMessage().needs_confirmation(
        contact="Ibu", message="Halo"
    )
    assert WhatsAppHangup().needs_confirmation() is False


def test_allowlisted_contact_skips_confirmation_by_default(contact_file):
    """Perilaku default Fase 16, diuji terhadap allowlist yang eksplisit."""
    from jarvis.agent.tools.whatsapp_web import WhatsAppCall

    assert WhatsAppCall().needs_confirmation(contact="Ibu") is False
    assert WhatsAppCall().needs_confirmation(
        contact="Belum Diizinkan") is True


def test_whatsapp_tool_shortlist_is_bounded(monkeypatch):
    from jarvis.agent import tool_selection

    monkeypatch.setattr(tool_selection.config, "get", lambda _p, d=None: d)
    WhatsAppTool = type(
        "WhatsAppTool",
        (),
        {"__module__": "jarvis.agent.tools.whatsapp_web"},
    )
    BrowserTool = type(
        "BrowserTool",
        (),
        {"__module__": "jarvis.agent.tools.browser"},
    )
    tools = {
        "whatsapp_call": WhatsAppTool(),
        "whatsapp_hangup": WhatsAppTool(),
        "browser_navigate": BrowserTool(),
    }

    selected = tool_selection.select_tool_names(
        "telepon Ibu lewat WhatsApp", tools
    )

    assert selected == ["whatsapp_call", "whatsapp_hangup"]


def test_plain_phone_request_uses_only_allowlisted_whatsapp_tools(monkeypatch):
    from jarvis.agent import tool_selection

    monkeypatch.setattr(tool_selection.config, "get", lambda _p, d=None: d)
    WhatsAppTool = type(
        "WhatsAppTool",
        (),
        {"__module__": "jarvis.agent.tools.whatsapp_web"},
    )
    tools = {"whatsapp_call": WhatsAppTool()}

    assert tool_selection.select_tool_names(
        "telepon dokter", tools
    ) == ["whatsapp_call"]


class _ChromiumLaunchHarness:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def launch_persistent_context(self, **kwargs):
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


def _playwright(outcomes):
    chromium = _ChromiumLaunchHarness(outcomes)
    return SimpleNamespace(chromium=chromium), chromium


def test_launch_never_removes_chromium_profile_locks(tmp_path, monkeypatch):
    from jarvis.integrations import whatsapp_web

    for name in ("SingletonLock", "DevToolsActivePort", "LOCK"):
        (tmp_path / name).write_text("owned", encoding="utf-8")
    monkeypatch.setattr(whatsapp_web, "_profile_dir", lambda: str(tmp_path))
    fake_context = object()
    playwright, _chromium = _playwright([fake_context])

    assert whatsapp_web.WhatsAppWebService()._launch(playwright) is fake_context
    contents = {
        path.name: path.read_text(encoding="utf-8")
        for path in tmp_path.iterdir()
    }
    assert all(
        contents.get(name) == "owned"
        for name in ("SingletonLock", "DevToolsActivePort", "LOCK")
    )


def test_profile_busy_fails_clearly_without_retry(tmp_path, monkeypatch):
    from jarvis.integrations import whatsapp_web

    monkeypatch.setattr(whatsapp_web, "_profile_dir", lambda: str(tmp_path))
    playwright, chromium = _playwright([
        RuntimeError(
            "Failed to create a ProcessSingleton for your profile directory. "
            "Aborting now to avoid profile corruption."
        )
    ])

    with pytest.raises(whatsapp_web.WhatsAppError, match="sedang dipakai"):
        whatsapp_web.WhatsAppWebService()._launch(playwright)

    assert len(chromium.calls) == 1


def test_missing_chrome_channel_falls_back_once_with_same_profile(
    tmp_path, monkeypatch
):
    from jarvis.integrations import whatsapp_web

    monkeypatch.setattr(whatsapp_web, "_profile_dir", lambda: str(tmp_path))
    fake_context = object()
    playwright, chromium = _playwright([
        RuntimeError("Chromium distribution 'chrome' is not found"),
        fake_context,
    ])

    assert whatsapp_web.WhatsAppWebService()._launch(playwright) is fake_context
    assert len(chromium.calls) == 2
    assert chromium.calls[0]["user_data_dir"] == str(tmp_path)
    assert chromium.calls[1]["user_data_dir"] == str(tmp_path)
    assert chromium.calls[0]["channel"] == "chrome"
    assert "channel" not in chromium.calls[1]


def test_unknown_launch_failure_is_not_retried(tmp_path, monkeypatch):
    from jarvis.integrations import whatsapp_web

    monkeypatch.setattr(whatsapp_web, "_profile_dir", lambda: str(tmp_path))
    playwright, chromium = _playwright([RuntimeError("unexpected launch fault")])

    with pytest.raises(whatsapp_web.WhatsAppError, match="gagal dibuka"):
        whatsapp_web.WhatsAppWebService()._launch(playwright)

    assert len(chromium.calls) == 1


def test_shutdown_existing_is_idempotent_and_does_not_create_service(monkeypatch):
    from jarvis.integrations import whatsapp_web

    class Existing:
        def __init__(self):
            self.stops = 0

        def stop(self):
            self.stops += 1

    existing = Existing()
    monkeypatch.setattr(
        whatsapp_web.WhatsAppWebService, "_instance", existing
    )

    whatsapp_web.shutdown_existing()
    whatsapp_web.shutdown_existing()

    assert existing.stops == 2

    monkeypatch.setattr(whatsapp_web.WhatsAppWebService, "_instance", None)
    monkeypatch.setattr(
        whatsapp_web.WhatsAppWebService,
        "get",
        classmethod(lambda cls: pytest.fail("shutdown must not create service")),
    )
    whatsapp_web.shutdown_existing()


def test_stop_rejects_new_calls_and_fails_queued_jobs(monkeypatch):
    from jarvis.integrations import whatsapp_web

    service = whatsapp_web.WhatsAppWebService()
    queued = Future()
    service._jobs.put((lambda _page: "must not run", queued))
    owner = SimpleNamespace(is_alive=lambda: True, join=lambda _timeout: None)
    service._thread = owner
    service._state = "accepting"

    assert service.stop(timeout=0) is False
    assert service._state == "closing"
    with pytest.raises(whatsapp_web.WhatsAppError, match="ditutup"):
        queued.result()
    monkeypatch.setattr(whatsapp_web, "available", lambda: True)
    with pytest.raises(whatsapp_web.WhatsAppError, match="ditutup"):
        service._call(lambda _page: None)


def test_call_and_stop_share_one_enqueue_boundary(monkeypatch):
    from jarvis.integrations import whatsapp_web

    service = whatsapp_web.WhatsAppWebService()
    owner = SimpleNamespace(is_alive=lambda: True, join=lambda _timeout: None)
    service._thread = owner
    service._state = "closing"
    monkeypatch.setattr(whatsapp_web, "available", lambda: True)

    with pytest.raises(whatsapp_web.WhatsAppError, match="ditutup"):
        service._call(lambda _page: "late")
    assert service._jobs.empty()


def test_stop_timeout_keeps_owner_and_closing_state():
    from jarvis.integrations import whatsapp_web

    service = whatsapp_web.WhatsAppWebService()
    owner = SimpleNamespace(is_alive=lambda: True, join=lambda _timeout: None)
    service._thread = owner
    service._state = "accepting"

    assert service.stop(timeout=0) is False
    assert service._thread is owner
    assert service._state == "closing"
    assert service.status()["state"] == "closing"


def test_repeated_stop_does_not_leave_sentinel_for_next_owner():
    from jarvis.integrations import whatsapp_web

    service = whatsapp_web.WhatsAppWebService()
    alive = True

    def is_alive():
        return alive

    owner = SimpleNamespace(is_alive=is_alive, join=lambda _timeout: None)
    service._thread = owner
    service._state = "accepting"

    assert service.stop(timeout=0) is False
    assert service.stop(timeout=0) is False
    assert service._jobs.qsize() == 1

    # Model the owner consuming its single terminal sentinel before exit.
    assert service._jobs.get_nowait() is None
    alive = False
    assert service.stop(timeout=0) is True
    assert service._jobs.empty()


def test_worker_failure_fails_queued_job_instead_of_hanging(monkeypatch):
    from jarvis.integrations import whatsapp_web

    service = whatsapp_web.WhatsAppWebService()
    service._thread = threading.current_thread()
    service._generation = 1
    service._state = "accepting"
    queued = Future()
    service._jobs.put((lambda _page: "must not run", queued))
    monkeypatch.setattr(
        service,
        "_launch",
        lambda _playwright: (_ for _ in ()).throw(RuntimeError("crash")),
    )

    class PlaywrightManager:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: PlaywrightManager(),
    )

    service._main(1)

    with pytest.raises(whatsapp_web.WhatsAppError, match="ditutup"):
        queued.result(timeout=0)


def test_start_failure_message_does_not_expose_unbounded_exception(monkeypatch):
    from jarvis.integrations import whatsapp_web

    service = whatsapp_web.WhatsAppWebService()
    service._thread = threading.current_thread()
    service._generation = 1
    service._state = "starting"
    secret = "provider-secret-" + "x" * 400
    monkeypatch.setattr(
        service,
        "_launch",
        lambda _playwright: (_ for _ in ()).throw(RuntimeError(secret)),
    )

    class PlaywrightManager:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: PlaywrightManager(),
    )

    service._main(1)

    assert secret not in service._failure
    assert service._failure == (
        "WhatsApp Web gagal dimulai. Periksa browser dan coba lagi."
    )


def test_dead_closing_owner_can_be_replaced_without_second_live_owner(
    monkeypatch,
):
    from jarvis.integrations import whatsapp_web

    service = whatsapp_web.WhatsAppWebService()
    service._thread = SimpleNamespace(is_alive=lambda: False)
    service._state = "closing"
    service._jobs.put(None)
    monkeypatch.setattr(whatsapp_web, "available", lambda: True)

    started = []

    class Worker:
        def __init__(self, *, target, args, daemon, name):
            started.append((target, args, daemon, name))

        def start(self):
            service._state = "accepting"
            service._started.set()

        def is_alive(self):
            return True

    monkeypatch.setattr(whatsapp_web.threading, "Thread", Worker)

    service._ensure()

    assert len(started) == 1
    assert service._state == "accepting"
    assert service._jobs.empty()


def test_old_owner_finally_cannot_clear_replacement_owner(monkeypatch):
    from jarvis.integrations import whatsapp_web

    service = whatsapp_web.WhatsAppWebService()
    old_owner = threading.current_thread()
    replacement = SimpleNamespace(is_alive=lambda: True)
    service._thread = old_owner
    service._generation = 1
    service._jobs.put(None)

    class Context:
        pages = []

        def close(self):
            service._thread = replacement
            service._generation = 2
            service._state = "accepting"

    monkeypatch.setattr(service, "_launch", lambda _playwright: Context())

    class PlaywrightManager:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: PlaywrightManager(),
    )

    service._main(1)

    assert service._thread is replacement
    assert service._state == "accepting"


def test_context_is_closed_once_when_service_thread_exits(monkeypatch):
    from jarvis.integrations import whatsapp_web

    class Context:
        pages = []

        def __init__(self):
            self.closed = 0

        def close(self):
            self.closed += 1

    context = Context()
    service = whatsapp_web.WhatsAppWebService()
    monkeypatch.setattr(service, "_launch", lambda _playwright: context)

    class PlaywrightManager:
        def __enter__(self):
            return object()

        def __exit__(self, *_args):
            return None

    monkeypatch.setattr(
        "playwright.sync_api.sync_playwright",
        lambda: PlaywrightManager(),
    )

    service._thread = threading.current_thread()
    service._generation = 1
    service._jobs.put(None)
    service._main(1)

    assert context.closed == 1
    assert service._state == "stopped"
    assert service._thread is None


def test_hermes_config_can_no_longer_reactivate_runtime():
    from jarvis.integrations.hermes import bridge

    # Hermes is a permanent runtime tombstone; no config seam remains that
    # could reactivate its retired process dependency.
    assert bridge.is_enabled() is False
    instance = bridge.HermesBridge.get()
    assert instance.available() is False
    assert instance._exe() is None

    bridge.HermesBridge._reset_for_tests()
