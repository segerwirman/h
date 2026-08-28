"""Task 13 — click-through Screen Control overlay and capture exclusion.

All tests run with Qt offscreen. Windows APIs, monitor geometry, UIA, and pixel
capture are injected fakes; no real desktop observation or input occurs.
"""
from __future__ import annotations

import inspect
import os
from contextlib import contextmanager
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")


class _Coordinates:
    def __init__(self, rect=(-1280, -100, 3200, 1180)) -> None:
        self.rect = rect
        self.calls = []

    def virtual_rect(self, *, space: str):
        self.calls.append(space)
        return self.rect


class _Exclusion:
    def __init__(self, supported: bool) -> None:
        self.supported = supported
        self.handles = []

    def exclude(self, handle: int) -> bool:
        self.handles.append(handle)
        return self.supported


class _Lease:
    def __init__(self) -> None:
        self.owner = ""
        self.releases = []

    def claim_authority(self, owner: str) -> bool:
        if self.owner and self.owner != owner:
            return False
        self.owner = owner
        return True

    def release_authority(self, owner: str) -> None:
        if self.owner == owner:
            self.releases.append(owner)
            self.owner = ""


class _Bus:
    def __init__(self) -> None:
        self.subscribers = {}

    def subscribe(self, topic, handler, ui=False) -> None:
        assert ui is False
        self.subscribers.setdefault(topic, []).append(handler)

    def publish(self, topic, **data) -> None:
        for handler in tuple(self.subscribers.get(topic, ())):
            handler(data)


class _Timer:
    def cancel(self) -> None:
        return None


class _Scheduler:
    def call_later(self, _delay, _callback):
        return _Timer()


def _app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def _coordinator(overlay):
    from jarvis.ui.screen_control import ScreenControlCoordinator

    coordinator = ScreenControlCoordinator(
        desktop=_Lease(),
        bus=_Bus(),
        clock=lambda: 100.0,
        scheduler=_Scheduler(),
    )
    assert coordinator.attach_overlay(overlay) is True
    return coordinator


def test_overlay_is_top_level_click_through_and_uses_shared_virtual_geometry():
    from PyQt6.QtCore import Qt
    from jarvis.ui.screen_cursor_overlay import ScreenCursorOverlay

    app = _app()
    coordinates = _Coordinates()
    exclusion = _Exclusion(True)
    overlay = ScreenCursorOverlay(
        coordinates=coordinates,
        capture_exclusion=exclusion,
        clock=lambda: 100.0,
    )

    assert overlay.parentWidget() is None
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    assert overlay.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
    assert overlay.windowFlags() & Qt.WindowType.FramelessWindowHint
    assert overlay.windowFlags() & Qt.WindowType.WindowTransparentForInput
    assert overlay.windowFlags() & Qt.WindowType.WindowStaysOnTopHint
    assert overlay.geometry().getRect() == (-1280, -100, 3200, 1180)
    assert coordinates.calls == ["logical"]
    assert exclusion.handles == [int(overlay.winId())]
    assert overlay.capture_excluded is True

    overlay.close()
    app.processEvents()


def test_overlay_module_has_no_automation_import_or_input_handlers():
    import jarvis.ui.screen_cursor_overlay as module

    source = inspect.getsource(module)
    assert "jarvis.automation" not in source
    for name in (
        "mousePressEvent",
        "mouseReleaseEvent",
        "mouseMoveEvent",
        "mouseDoubleClickEvent",
        "wheelEvent",
        "keyPressEvent",
        "keyReleaseEvent",
        "touchEvent",
        "tabletEvent",
        "dragEnterEvent",
        "dropEvent",
    ):
        assert name not in source


def test_coordinator_drives_overlay_state_and_revocation_clears_visuals():
    from jarvis.ui.screen_cursor_overlay import ScreenCursorOverlay

    app = _app()
    overlay = ScreenCursorOverlay(
        coordinates=_Coordinates(),
        capture_exclusion=_Exclusion(True),
        clock=lambda: 100.0,
    )
    coordinator = _coordinator(overlay)

    assert coordinator.activate("session-a", "T-a", ttl_s=30)
    assert overlay.isVisible()
    assert overlay.mode == "active"
    assert overlay.expires_at == 130.0

    assert coordinator.update_visual(
        cursor=(-1200, 50),
        target_rect=(-1220, 20, 120, 60),
        status="target_ready",
    )
    assert overlay.cursor == (-1200, 50)
    assert overlay.target_rect == (-1220, 20, 120, 60)
    assert overlay.status == "target_ready"

    assert coordinator.revoke("emergency.stop")
    assert not overlay.isVisible()
    assert overlay.mode == "off"
    assert overlay.cursor is None
    assert overlay.target_rect is None
    assert overlay.status == ""

    overlay.close()
    app.processEvents()


def test_handoff_state_remains_visible_without_desktop_authority():
    from jarvis.ui.screen_cursor_overlay import ScreenCursorOverlay

    app = _app()
    overlay = ScreenCursorOverlay(
        coordinates=_Coordinates(),
        capture_exclusion=_Exclusion(True),
    )
    coordinator = _coordinator(overlay)

    assert coordinator.activate("session-a", "T-a", ttl_s=30)
    assert coordinator.update_visual(
        cursor=(-1200, 50),
        target_rect=(-1220, 20, 120, 60),
        status="target_ready",
    )
    assert coordinator.begin_handoff("T-a")

    assert overlay.isVisible()
    assert overlay.mode == "handing_off"
    assert overlay.status == "handoff"
    assert overlay.cursor is None
    assert overlay.target_rect is None

    coordinator.revoke("cancelled")
    overlay.close()
    app.processEvents()


def test_worker_thread_state_update_is_queued_to_qt_owner():
    import threading

    from jarvis.ui.screen_cursor_overlay import ScreenCursorOverlay

    app = _app()
    overlay = ScreenCursorOverlay(
        coordinates=_Coordinates(),
        capture_exclusion=_Exclusion(True),
    )

    worker = threading.Thread(
        target=lambda: overlay.show_state(
            mode="active",
            expires_at=130.0,
            status="worker_update",
        ),
    )
    worker.start()
    worker.join(timeout=2)
    app.processEvents()

    assert overlay.isVisible()
    assert overlay.mode == "active"
    assert overlay.status == "worker_update"

    overlay.close()
    app.processEvents()


def test_capture_exclusion_uses_injected_windows_setter_and_fails_closed():
    from jarvis.ui.screen_cursor_overlay import (
        WDA_EXCLUDEFROMCAPTURE,
        WindowsCaptureExclusion,
    )

    calls = []
    supported = WindowsCaptureExclusion(
        setter=lambda hwnd, affinity: calls.append((hwnd, affinity)) or 1,
        platform="win32",
    )
    unavailable = WindowsCaptureExclusion(
        setter=lambda _hwnd, _affinity: 0,
        platform="win32",
    )
    wrong_platform = WindowsCaptureExclusion(
        setter=lambda _hwnd, _affinity: 1,
        platform="linux",
    )

    assert supported.exclude(1234) is True
    assert calls == [(1234, WDA_EXCLUDEFROMCAPTURE)]
    assert unavailable.exclude(1234) is False
    assert wrong_platform.exclude(1234) is False


def test_capture_pause_keeps_excluded_overlay_visible():
    from jarvis.ui.screen_cursor_overlay import ScreenCursorOverlay

    app = _app()
    overlay = ScreenCursorOverlay(
        coordinates=_Coordinates(),
        capture_exclusion=_Exclusion(True),
    )
    coordinator = _coordinator(overlay)
    assert coordinator.activate("session-a", "T-a", ttl_s=30)

    with coordinator.capture_pause():
        assert overlay.isVisible()
        assert overlay.capture_paused is False

    assert overlay.isVisible()
    overlay.close()
    app.processEvents()


def test_capture_pause_synchronously_hides_fallback_and_restores_after_capture():
    from jarvis.ui.screen_cursor_overlay import ScreenCursorOverlay

    app = _app()
    overlay = ScreenCursorOverlay(
        coordinates=_Coordinates(),
        capture_exclusion=_Exclusion(False),
    )
    coordinator = _coordinator(overlay)
    assert coordinator.activate("session-a", "T-a", ttl_s=30)
    states = []

    with coordinator.capture_pause():
        states.append((overlay.isVisible(), overlay.capture_paused))

    states.append((overlay.isVisible(), overlay.capture_paused))
    assert states == [(False, True), (True, False)]

    overlay.close()
    app.processEvents()


def test_worker_thread_fallback_pause_fails_closed_before_capture():
    import threading

    from jarvis.automation.visual_observe import VisualObserveService
    from jarvis.ui.screen_cursor_overlay import ScreenCursorOverlay

    app = _app()
    overlay = ScreenCursorOverlay(
        coordinates=_Coordinates(),
        capture_exclusion=_Exclusion(False),
    )
    coordinator = _coordinator(overlay)
    assert coordinator.activate("session-a", "T-a", ttl_s=30)
    captures = []
    service = VisualObserveService(
        foreground=lambda: ("Editor", "Editor"),
        capture=lambda: captures.append("capture") or object(),
        denylisted=lambda _title, _app: False,
        capture_pause=coordinator.capture_pause,
    )
    results = []

    worker = threading.Thread(
        target=lambda: results.append(service.observe(session_id="session-a")),
    )
    worker.start()
    worker.join(timeout=2)

    assert results == [None]
    assert captures == []
    assert overlay.isVisible()

    coordinator.revoke("test_done")
    overlay.close()
    app.processEvents()


def test_visual_observe_capture_runs_inside_injected_pause_context():
    from jarvis.automation.visual_observe import VisualObserveService

    events = []

    @contextmanager
    def pause():
        events.append("hide")
        try:
            yield
        finally:
            events.append("show")

    image = SimpleNamespace(convert=lambda _mode: SimpleNamespace())
    service = VisualObserveService(
        foreground=lambda: ("Editor", "Editor"),
        capture=lambda: events.append("capture") or image,
        denylisted=lambda _title, _app: False,
        capture_pause=pause,
    )

    import jarvis.automation.visual_observe as module
    original = module._summarize
    module._summarize = lambda _image: {"visual_observation_id": "offline"}
    try:
        assert service.observe(session_id="session-a") == {
            "visual_observation_id": "offline",
        }
    finally:
        module._summarize = original

    assert events == ["hide", "capture", "show"]


def test_uia_observation_runs_inside_injected_pause_context():
    from jarvis.automation.uia_capture import UIACaptureBackend

    events = []

    @contextmanager
    def pause():
        events.append("hide")
        try:
            yield
        finally:
            events.append("show")

    window = SimpleNamespace(
        handle=41,
        window_text=lambda: "Offline Editor",
        descendants=lambda: events.append("capture") or [],
    )
    desktop = SimpleNamespace(get_active=lambda: window)
    backend = UIACaptureBackend(desktop=desktop, capture_pause=pause)

    frame = backend.capture()

    assert frame.surface_id == "uia:41"
    assert events == ["hide", "capture", "show"]
