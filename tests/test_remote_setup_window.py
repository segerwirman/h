"""Fase 15S desktop wiring: BUS remote_setup.pending → RemoteSetupSheet."""
from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

from PyQt6.QtWidgets import QApplication

from jarvis.core.bus import BUS

_APP = None


def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP


def _drain():
    BUS.drain_ui()
    _app().processEvents()


def _oauth_bytes() -> bytes:
    return json.dumps({
        "installed": {
            "client_id": "abc.apps.googleusercontent.com",
            "token_uri": "https://oauth2.googleapis.com/token",
            "client_secret": "WINDOW-SECRET-NOLEAK",
        }
    }).encode()


def test_remote_setup_pending_presents_sheet_with_metadata_only():
    _app()
    from jarvis.agent.remote_setup import get_setup_queue
    from jarvis.ui.window import MainWindow

    win = MainWindow()
    win.show()
    for _ in range(6):
        _drain()

    queue = get_setup_queue()
    request = queue.stage(
        provider="google_oauth_client", requester="telegram:42",
        filename="client_secret.json", payload=_oauth_bytes(),
    )
    # BUS carries only the opaque request id; the window owns the queue.
    BUS.publish("remote_setup.pending", request_id=request.id)
    for _ in range(6):
        _drain()

    sheet = getattr(win, "remote_setup_sheet", None)
    assert sheet is not None
    assert sheet.isVisible()
    text = sheet.summary_text()
    assert "google_oauth_client" in text
    assert request.hash_suffix in text
    assert "WINDOW-SECRET-NOLEAK" not in text
    win.close()


def test_remote_setup_pending_ignores_caller_supplied_queue():
    _app()
    from jarvis.agent.remote_setup import get_setup_queue
    from jarvis.ui.window import MainWindow

    class ForeignQueue:
        def get(self, _request_id):
            raise AssertionError("caller-supplied queue must not be queried")

    win = MainWindow()
    win.show()
    for _ in range(6):
        _drain()

    request = get_setup_queue().stage(
        provider="google_oauth_client", requester="telegram:42",
        filename="client_secret.json", payload=_oauth_bytes(),
    )
    # even a genuine-but-foreign queue object in the event must be ignored
    BUS.publish("remote_setup.pending", request_id=request.id, queue=ForeignQueue())
    for _ in range(6):
        _drain()

    assert win.remote_setup_sheet.isVisible()
    win.close()


def test_remote_setup_pending_rejects_unknown_request_id_before_presenting():
    _app()
    from jarvis.ui.window import MainWindow

    win = MainWindow()
    win.show()
    for _ in range(3):
        _drain()

    win._on_remote_setup_pending({"request_id": "forged"})

    assert not win.remote_setup_sheet.isVisible()
    win.close()
