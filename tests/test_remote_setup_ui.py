"""Fase 15S UI: sheet approval lokal untuk secure remote setup."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _oauth_json() -> bytes:
    return json.dumps({
        "installed": {
            "client_id": "abc.apps.googleusercontent.com",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "SECRET-NEVER-DISPLAY",
        }
    }).encode()


def test_sheet_shows_metadata_only_and_never_secret():
    _app()
    from jarvis.agent.remote_setup import SetupQueue
    from jarvis.ui.remote_setup_sheet import RemoteSetupSheet

    queue = SetupQueue()
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:123",
        filename="client_secret.json", payload=_oauth_json(),
    )
    sheet = RemoteSetupSheet(queue)
    sheet.present(request.id)

    text = sheet.summary_text()
    assert "google_oauth_client" in text
    assert request.hash_suffix in text
    assert "telegram:123" not in text
    assert "Pemohon remote terverifikasi" in text
    assert "SECRET-NEVER-DISPLAY" not in text
    assert "installed" not in text


def test_sheet_never_displays_raw_remote_requester_identity():
    _app()
    from jarvis.agent.remote_setup import SetupQueue
    from jarvis.ui.remote_setup_sheet import RemoteSetupSheet

    queue = SetupQueue()
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:SECRET-ACTOR-ID\nINJECTED",
        filename="client_secret.json", payload=_oauth_json(),
    )
    sheet = RemoteSetupSheet(queue)
    assert sheet.present(request.id) is True

    text = sheet.summary_text()
    assert "SECRET-ACTOR-ID" not in text
    assert "INJECTED" not in text
    assert "Pemohon remote terverifikasi" in text


def test_sheet_approve_button_imports_and_clears(monkeypatch):
    _app()
    from jarvis.agent import remote_setup
    from jarvis.agent.remote_setup import SetupQueue
    from jarvis.ui.remote_setup_sheet import RemoteSetupSheet

    imported = {}
    monkeypatch.setattr(remote_setup, "_import_to_secret_store",
                        lambda provider, payload: imported.setdefault(provider, True) or True)

    queue = SetupQueue()
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:123",
        filename="client_secret.json", payload=_oauth_json(),
    )
    sheet = RemoteSetupSheet(queue)
    sheet.present(request.id)
    sheet._approve()
    assert sheet._import_done.wait(5), "import worker harus selesai"

    assert imported == {"google_oauth_client": True}
    assert queue.get(request.id) is None


def test_sheet_approve_imports_off_ui_thread(monkeypatch):
    _app()
    import threading
    from jarvis.agent import remote_setup
    from jarvis.agent.remote_setup import SetupQueue
    from jarvis.ui.remote_setup_sheet import RemoteSetupSheet

    main_thread = threading.get_ident()
    seen_threads = []

    def fake_import(provider, payload):
        seen_threads.append(threading.get_ident())
        return True

    monkeypatch.setattr(remote_setup, "_import_to_secret_store", fake_import)

    queue = SetupQueue()
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:123",
        filename="client_secret.json", payload=_oauth_json(),
    )
    sheet = RemoteSetupSheet(queue)
    sheet.present(request.id)
    sheet._approve()
    assert sheet._import_done.wait(5), "import worker harus selesai"

    assert seen_threads, "import harus dipanggil"
    assert seen_threads[0] != main_thread, \
        "import tidak boleh berjalan di UI thread"
    assert queue.get(request.id) is None


def test_sheet_cancel_removes_staging_without_import(monkeypatch):
    _app()
    from jarvis.agent import remote_setup
    from jarvis.agent.remote_setup import SetupQueue
    from jarvis.ui.remote_setup_sheet import RemoteSetupSheet

    monkeypatch.setattr(remote_setup, "_import_to_secret_store",
                        lambda *_: (_ for _ in ()).throw(AssertionError("must not import")))

    queue = SetupQueue()
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:123",
        filename="client_secret.json", payload=_oauth_json(),
    )
    sheet = RemoteSetupSheet(queue)
    sheet.present(request.id)
    sheet._cancel()

    assert queue.get(request.id) is None
