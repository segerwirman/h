"""Phase O — async-safe OAuth login lifecycle."""
from __future__ import annotations

import importlib
import threading


def test_service_melaporkan_connected_dan_mereset_client(monkeypatch):
    try:
        service = importlib.import_module("jarvis.integrations.openai_oauth_service")
    except ModuleNotFoundError as exc:
        assert exc.name == "jarvis.integrations.openai_oauth_service"
        raise

    done = threading.Event()
    seen: list[dict] = []

    monkeypatch.setattr(service.openai_oauth, "start_login", lambda: {
        "provider": "openai_oauth", "connected": True,
    })
    monkeypatch.setattr(service.openai_oauth, "status", lambda: {
        "connected": True, "needs_reauth": False,
        "token_refresh_due": False, "last_error_code": "",
    })
    state = service.start(on_update=lambda item: (seen.append(item), done.set()
                                                  if item["state"] == "connected" else None))

    assert state["state"] == "browser_open"
    assert done.wait(1)
    assert seen[-1]["state"] == "connected"
    assert seen[-1]["connected"] is True
    assert seen[-1]["error"] == ""


def test_service_menyaring_error_login(monkeypatch):
    service = importlib.import_module("jarvis.integrations.openai_oauth_service")
    done = threading.Event()
    seen: list[dict] = []

    monkeypatch.setattr(service.openai_oauth, "start_login",
                        lambda: (_ for _ in ()).throw(RuntimeError("token-rahasia")))
    service.start(on_update=lambda item: (seen.append(item), done.set()
                                          if item["state"] == "failed" else None))

    assert done.wait(1)
    assert seen[-1]["state"] == "failed"
    assert seen[-1]["error"] == "login gagal"
    assert "rahasia" not in repr(seen[-1])
