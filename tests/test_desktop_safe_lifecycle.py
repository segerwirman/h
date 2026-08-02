"""Fase 7: lease, revoke, dan fault containment desktop-safe."""
from __future__ import annotations

import threading


def test_desktop_service_run_releases_lease_when_operation_raises():
    import pytest

    from jarvis.automation.desktop_service import DesktopService

    desktop = DesktopService()

    with pytest.raises(RuntimeError, match="boom"):
        desktop.run("session-a", lambda: (_ for _ in ()).throw(RuntimeError("boom")))

    assert desktop.claim("session-b") is True
