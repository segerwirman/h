"""Framework maturity Phase 4 — automation services serialize mutable control."""
from __future__ import annotations

import asyncio


def test_desktop_service_menolak_writer_kedua_sampai_lease_dilepas():
    from jarvis.automation.desktop_service import DesktopService

    service = DesktopService()
    assert service.claim("session-a") is True
    assert service.claim("session-b") is False
    service.release("session-a")
    assert service.claim("session-b") is True


def test_browser_service_reuses_resource_pool_per_profile():
    from jarvis.automation.browser_service import BrowserService

    service = BrowserService()
    calls = []
    first = service.get_or_create("chrome", lambda: calls.append(1) or object())
    second = service.get_or_create("chrome", lambda: calls.append(2) or object())

    assert first is second
    assert calls == [1]


def test_desktop_service_runs_callable_hanya_bila_owner_sama():
    from jarvis.automation.desktop_service import DesktopService

    service = DesktopService()
    assert service.run("session-a", lambda: "ok") == "ok"
    assert service.run("session-b", lambda: "bad") is None
    service.release("session-a")
    assert service.run("session-b", lambda: "ok-b") == "ok-b"


def test_computer_click_memakai_desktop_lease(monkeypatch):
    from jarvis.agent.tools import computer

    computer.DESKTOP.release("s1")
    monkeypatch.setattr(computer, "_pg", lambda: type("P", (), {
        "click": lambda *_a, **_k: None,
        "doubleClick": lambda *_a, **_k: None,
    })())

    result = asyncio.run(computer.ComputerClick().run(1, 2, _session=type("S", (), {"id": "s1"})()))

    assert result.ok is True
    assert computer.DESKTOP.claim("other") is False
    computer.DESKTOP.release("s1")
