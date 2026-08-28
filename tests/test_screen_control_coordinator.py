"""Task 10 — process-local Screen Control authority and UI wiring.

All tests are offline. Desktop ownership, timers, and BUS delivery use fakes;
Qt runs offscreen and no native observation or pointer action is attempted.
"""
from __future__ import annotations

import os
import threading
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")


class _Bus:
    def __init__(self) -> None:
        self.subscribers: dict[str, list] = {}
        self.events: list[tuple[str, dict]] = []

    def subscribe(self, topic, handler, ui=False) -> None:
        assert ui is False
        self.subscribers.setdefault(topic, []).append(handler)

    def publish(self, topic, **data) -> None:
        self.events.append((topic, data))
        for handler in tuple(self.subscribers.get(topic, ())):
            handler(data)


class _Lease:
    def __init__(self) -> None:
        self.owner = ""
        self.authority_owner = ""
        self.claims: list[str] = []
        self.releases: list[str] = []

    def claim(self, owner: str) -> bool:
        self.claims.append(owner)
        if self.owner and self.owner != owner:
            return False
        self.owner = owner
        return True

    def release(self, owner: str) -> None:
        if self.owner == owner and self.authority_owner != owner:
            self.owner = ""

    def claim_authority(self, owner: str) -> bool:
        self.claims.append(owner)
        if self.owner and self.owner != owner:
            return False
        if self.authority_owner and self.authority_owner != owner:
            return False
        self.owner = owner
        self.authority_owner = owner
        return True

    def release_authority(self, owner: str) -> None:
        if self.authority_owner != owner:
            return
        self.releases.append(owner)
        self.authority_owner = ""
        if self.owner == owner:
            self.owner = ""


class _Scheduled:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.cancelled = False

    def cancel(self) -> None:
        self.cancelled = True

    def fire(self) -> None:
        if not self.cancelled:
            self.callback()


class _Scheduler:
    def __init__(self) -> None:
        self.calls: list[tuple[float, _Scheduled]] = []

    def call_later(self, delay_s: float, callback):
        scheduled = _Scheduled(callback)
        self.calls.append((delay_s, scheduled))
        return scheduled


@pytest.fixture()
def authority():
    from jarvis.ui.screen_control import ScreenControlCoordinator

    now = [100.0]
    lease = _Lease()
    bus = _Bus()
    scheduler = _Scheduler()
    coordinator = ScreenControlCoordinator(
        desktop=lease,
        bus=bus,
        clock=lambda: now[0],
        scheduler=scheduler,
    )
    return coordinator, lease, bus, scheduler, now


def test_activation_binds_exact_session_task_and_bounded_expiry(authority):
    coordinator, lease, _bus, scheduler, now = authority

    assert coordinator.activate("session-a", "T-a", ttl_s=30) is True
    snapshot = coordinator.snapshot()

    assert snapshot.state == "active"
    assert snapshot.session_id == "session-a"
    assert snapshot.task_id == "T-a"
    assert snapshot.expires_at == pytest.approx(130.0)
    assert lease.owner == "session-a"
    assert scheduler.calls[0][0] == pytest.approx(30.0)
    assert coordinator.activate("session-b", "T-b", ttl_s=30) is False
    assert coordinator.activate("", "T-a", ttl_s=30) is False
    assert coordinator.activate("session-a", "", ttl_s=30) is False
    assert coordinator.activate("session-a", "T-a", ttl_s=0) is False
    assert coordinator.activate("session-a", "T-a", ttl_s=3601) is False

    now[0] = 131.0
    scheduler.calls[0][1].fire()
    assert coordinator.snapshot().state == "off"
    assert lease.owner == ""
    assert lease.releases == ["session-a"]


def test_handoff_releases_authority_once_and_can_resume(authority):
    coordinator, lease, _bus, _scheduler, _now = authority
    assert coordinator.activate("session-a", "T-a", ttl_s=30)

    assert coordinator.begin_handoff("T-a") is True
    assert coordinator.snapshot().state == "handing_off"
    assert lease.releases == ["session-a"]
    assert coordinator.begin_handoff("T-a") is False

    assert coordinator.resume_handoff("T-a") is True
    assert coordinator.snapshot().state == "active"
    assert lease.owner == "session-a"
    assert coordinator.revoke("toggle_off") is True
    assert coordinator.revoke("toggle_off") is False
    assert lease.releases == ["session-a", "session-a"]


@pytest.mark.parametrize(
    ("topic", "payload"),
    [
        ("agent.tasks.cancel_all", {}),
        ("emergency.stop", {"source": "offline_test"}),
        ("screen_control.unsafe", {"reason": "unsafe_state"}),
        ("window.closing", {}),
        ("application.shutdown", {}),
        ("task.finished", {"task": {"id": "T-a"}}),
    ],
)
def test_every_bus_revocation_trigger_releases_exactly_once(authority, topic, payload):
    coordinator, lease, bus, _scheduler, _now = authority
    assert coordinator.activate("session-a", "T-a", ttl_s=30)

    bus.publish(topic, **payload)
    bus.publish(topic, **payload)

    assert coordinator.snapshot().state == "off"
    assert lease.releases == ["session-a"]


def test_unrelated_task_finish_does_not_revoke(authority):
    coordinator, lease, bus, _scheduler, _now = authority
    assert coordinator.activate("session-a", "T-a", ttl_s=30)

    bus.publish("task.finished", task={"id": "T-other"})

    assert coordinator.snapshot().state == "active"
    assert lease.releases == []


def test_same_session_operation_release_keeps_authority_reserved(authority):
    coordinator, lease, _bus, _scheduler, _now = authority
    assert coordinator.activate("session-a", "T-a", ttl_s=30)

    assert lease.claim("session-a") is True
    lease.release("session-a")

    assert lease.owner == "session-a"
    assert lease.claim("session-b") is False
    assert coordinator.revoke("toggle_off") is True
    assert lease.owner == ""
    assert lease.claim("session-b") is True


def test_real_desktop_service_authority_survives_same_owner_borrow():
    from jarvis.automation.desktop_service import DesktopService
    from jarvis.ui.screen_control import ScreenControlCoordinator

    desktop = DesktopService()
    coordinator = ScreenControlCoordinator(
        desktop=desktop,
        bus=_Bus(),
        clock=lambda: 100.0,
        scheduler=_Scheduler(),
    )
    assert coordinator.activate("session-a", "T-a", ttl_s=30)

    assert desktop.claim("session-a") is True
    desktop.release("session-a")

    assert desktop.claim("session-b") is False
    assert coordinator.revoke("toggle_off") is True
    assert desktop.claim("session-b") is True


def test_real_desktop_service_authority_claim_is_exclusive_under_contention():
    from jarvis.automation.desktop_service import DesktopService

    desktop = DesktopService()
    start = threading.Barrier(3)
    results = []
    guard = threading.Lock()

    def claim(owner: str) -> None:
        start.wait()
        accepted = desktop.claim_authority(owner)
        with guard:
            results.append((owner, accepted))

    first = threading.Thread(target=claim, args=("session-a",))
    second = threading.Thread(target=claim, args=("session-b",))
    first.start()
    second.start()
    start.wait()
    first.join(timeout=2)
    second.join(timeout=2)

    assert sorted(accepted for _, accepted in results) == [False, True]
    winner = next(owner for owner, accepted in results if accepted)
    desktop.release_authority(winner)
    loser = next(owner for owner, accepted in results if not accepted)
    assert desktop.claim_authority(loser) is True


def test_real_desktop_service_revocation_is_immediate_with_inflight_borrow():
    from jarvis.automation.desktop_service import DesktopService

    desktop = DesktopService()
    assert desktop.claim_authority("session-a") is True
    assert desktop.claim("session-a") is True

    desktop.release_authority("session-a")

    assert desktop.claim("session-b") is True
    desktop.release("session-a")
    assert desktop.claim("session-c") is False
    desktop.release("session-b")
    assert desktop.claim("session-c") is True


def test_real_desktop_service_stale_release_cannot_clear_reacquired_owner():
    from jarvis.automation.desktop_service import DesktopService

    desktop = DesktopService()
    assert desktop.claim_authority("session-a") is True
    assert desktop.claim("session-a") is True
    desktop.release_authority("session-a")

    assert desktop.claim_authority("session-a") is False
    desktop.release("session-a")
    assert desktop.claim_authority("session-a") is True
    desktop.release("session-a")

    assert desktop.claim("session-b") is False
    desktop.release_authority("session-a")
    assert desktop.claim("session-b") is True


def test_stale_session_cleanup_cannot_revoke_newer_activation(authority):
    coordinator, lease, _bus, _scheduler, _now = authority
    assert coordinator.activate("session-a", "T-a", ttl_s=30)

    original_release = lease.release_authority
    activation_attempts = []

    def release_then_try_activate(owner: str) -> None:
        original_release(owner)
        activation_attempts.append(
            coordinator.activate("session-b", "T-b", ttl_s=30)
        )

    lease.release_authority = release_then_try_activate

    assert coordinator.release_session("session-a") is True
    assert activation_attempts == [False]
    assert coordinator.activate("session-b", "T-b", ttl_s=30) is True
    snapshot = coordinator.snapshot()
    assert snapshot.state == "active"
    assert snapshot.session_id == "session-b"
    assert snapshot.task_id == "T-b"


def test_action_panel_has_no_screen_control_execution_logic():
    import inspect
    from jarvis.ui.actionpanel import ActionPanel

    source = inspect.getsource(ActionPanel)
    assert "jarvis.automation" not in source
    assert "COORDINATOR" not in source
    assert "screen_control_clicked.emit" not in source
    assert "btn.clicked.connect(sig[name].emit)" in source


def test_action_panel_screen_control_signal_and_config_removal(monkeypatch):
    from PyQt6.QtWidgets import QApplication, QWidget
    from jarvis.core import config
    from jarvis.ui.actionpanel import ActionPanel, _ICONS

    app = QApplication.instance() or QApplication([])
    host = QWidget()
    panel = ActionPanel(host)
    hits = []
    panel.screen_control_clicked.connect(lambda: hits.append("screen_control"))

    assert "screen_control" in _ICONS
    assert "screen_control" in panel._buttons
    assert panel._buttons["screen_control"].accessibleName()
    assert panel._buttons["screen_control"].toolTip()
    panel._buttons["screen_control"].click()
    assert hits == ["screen_control"]

    original_section = config.section

    def without_screen_control(name: str):
        section = dict(original_section(name))
        if name == "action_panel":
            section["icons"] = [
                item for item in section.get("icons", [])
                if item != "screen_control"
            ]
        return section

    monkeypatch.setattr(config, "section", without_screen_control)
    reduced = ActionPanel(host)
    assert "screen_control" not in reduced._buttons
    reduced.set_indicator("screen_control", True)
    reduced.deleteLater()
    panel.deleteLater()
    host.close()
    app.processEvents()


def test_dispatch_scope_requires_one_live_running_task(monkeypatch):
    from jarvis.agent import dispatch
    from jarvis.agent.session import Session

    first = Session(task="one")
    first.registry_task_id = "T-a"
    handle = dispatch.TaskHandle("one", first)
    handle.bg_task = SimpleNamespace(id="T-a")
    with dispatch._active_lock:
        previous = dict(dispatch._active)
        dispatch._active.clear()
        dispatch._active["one"] = handle

    live = SimpleNamespace(active=True, cancelled=False, status="running")
    monkeypatch.setattr("jarvis.agent.tasks.REGISTRY.get", lambda tid: live if tid == "T-a" else None)
    try:
        scope = dispatch.screen_control_scope()
        assert scope is not None
        assert scope.session_id == first.id
        assert scope.task_id == "T-a"

        second = Session(task="two")
        second.registry_task_id = "T-b"
        other = dispatch.TaskHandle("two", second)
        other.bg_task = SimpleNamespace(id="T-b")
        with dispatch._active_lock:
            dispatch._active["two"] = other
        assert dispatch.screen_control_scope() is None
    finally:
        with dispatch._active_lock:
            dispatch._active.clear()
            dispatch._active.update(previous)


def test_dispatch_cleanup_releases_matching_screen_control_session(monkeypatch):
    from jarvis.agent import dispatch
    from jarvis.ui import screen_control

    calls = []
    monkeypatch.setattr(
        screen_control.COORDINATOR,
        "release_session",
        lambda session_id, reason="task_terminal": calls.append((session_id, reason)) or True,
    )

    dispatch._release_screen_control_session("session-a")

    assert calls == [("session-a", "task_terminal")]


def test_window_close_wrapper_publishes_revocation_before_legacy_close(monkeypatch):
    from jarvis.ui import screen_control

    calls = []

    class Window:
        def closeEvent(self, event):
            calls.append(("legacy", event))
            return "closed"

    monkeypatch.setattr(
        screen_control.BUS,
        "publish",
        lambda topic, **_data: calls.append((topic, None)),
    )

    assert screen_control.install(Window) is True
    event = object()
    assert Window().closeEvent(event) == "closed"
    assert calls == [("window.closing", None), ("legacy", event)]
    assert screen_control.install(Window) is True


def test_shutdown_publishes_application_boundary(monkeypatch):
    from jarvis.ui import screen_control

    calls = []
    monkeypatch.setattr(
        screen_control.BUS,
        "publish",
        lambda topic, **_data: calls.append(topic),
    )

    screen_control.shutdown()

    assert calls == ["application.shutdown"]


def test_canonical_main_registers_screen_control_supervisor_stop():
    import inspect
    from jarvis import main

    source = inspect.getsource(main.run)
    assert 'supervisor.add_stop("screen_control", screen_control.shutdown)' in source


def test_screen_control_indicator_reflects_active_state():
    from jarvis.ui.window_panels import WindowPanelsMixin

    indicators = []
    tooltips = []
    logs = []
    notices = []
    host = SimpleNamespace(
        action_panel=SimpleNamespace(
            set_indicator=lambda *args: indicators.append(args),
            set_button_state=lambda *args: tooltips.append(args),
        ),
        write_log=logs.append,
        notifications=SimpleNamespace(
            push=lambda *args: notices.append(args),
        ),
    )

    WindowPanelsMixin._on_screen_control_changed(
        host,
        {"active": True, "reason": "activated"},
    )
    WindowPanelsMixin._on_screen_control_changed(
        host,
        {"active": False, "reason": "toggle_off"},
    )

    assert indicators == [("screen_control", True), ("screen_control", False)]
    assert "AKTIF" in tooltips[0][1]
    assert "kontrol desktop semantik lokal" in tooltips[1][1]
    assert logs == [
        "SYS: Screen Control AKTIF untuk tugas agent lokal.",
        "SYS: Screen Control nonaktif.",
    ]
    assert notices[0][2] == "info"
    assert notices[1][2] == "warning"


def test_toggle_screen_control_refuses_when_local_config_is_disabled(monkeypatch):
    from jarvis.ui import screen_control
    from jarvis.ui.window_panels import WindowPanelsMixin

    logs = []
    notices = []
    host = SimpleNamespace(
        write_log=logs.append,
        notifications=SimpleNamespace(
            push=lambda *args: notices.append(args),
        ),
    )
    monkeypatch.setattr(screen_control.COORDINATOR, "snapshot", lambda: screen_control.ScreenControlSnapshot())
    monkeypatch.setattr("jarvis.core.config.get", lambda key, default=None: False if key == "screen_control.enabled" else default)

    WindowPanelsMixin._toggle_screen_control(host)

    assert "belum diizinkan" in logs[-1]
    assert notices[-1][1] == "Dinonaktifkan di konfigurasi"


def test_toggle_screen_control_requires_one_unambiguous_live_task(monkeypatch):
    from jarvis.ui import screen_control
    from jarvis.ui.window_panels import WindowPanelsMixin

    logs = []
    notices = []
    host = SimpleNamespace(
        write_log=logs.append,
        notifications=SimpleNamespace(
            push=lambda *args: notices.append(args),
        ),
    )
    monkeypatch.setattr(screen_control.COORDINATOR, "snapshot", lambda: screen_control.ScreenControlSnapshot())
    monkeypatch.setattr("jarvis.core.config.get", lambda key, default=None: True if key == "screen_control.enabled" else default)
    monkeypatch.setattr("jarvis.agent.dispatch.screen_control_scope", lambda: None)

    WindowPanelsMixin._toggle_screen_control(host)

    assert "tepat satu tugas" in logs[-1]
    assert notices[-1][1] == "Tidak ada satu tugas aktif yang jelas"


def test_toggle_screen_control_activates_one_task_then_toggles_off(monkeypatch):
    from jarvis.agent.dispatch import ScreenControlScope
    from jarvis.ui import screen_control
    from jarvis.ui.window_panels import WindowPanelsMixin

    state = [screen_control.ScreenControlSnapshot()]
    calls = []
    host = SimpleNamespace(
        write_log=lambda _message: None,
        notifications=SimpleNamespace(push=lambda *_args: None),
    )
    monkeypatch.setattr(screen_control.COORDINATOR, "snapshot", lambda: state[0])
    monkeypatch.setattr("jarvis.core.config.get", lambda key, default=None: True if key == "screen_control.enabled" else default)
    monkeypatch.setattr(
        "jarvis.agent.dispatch.screen_control_scope",
        lambda: ScreenControlScope("session-a", "T-a"),
    )

    def activate(session_id, task_id, *, ttl_s):
        calls.append(("activate", session_id, task_id, ttl_s))
        state[0] = screen_control.ScreenControlSnapshot(
            screen_control.ACTIVE,
            session_id,
            task_id,
            130.0,
        )
        return True

    def revoke(reason):
        calls.append(("revoke", reason))
        state[0] = screen_control.ScreenControlSnapshot()
        return True

    monkeypatch.setattr(screen_control.COORDINATOR, "activate", activate)
    monkeypatch.setattr(screen_control.COORDINATOR, "revoke", revoke)
    monkeypatch.setattr(screen_control, "default_ttl_s", lambda: 30.0)

    WindowPanelsMixin._toggle_screen_control(host)
    WindowPanelsMixin._toggle_screen_control(host)

    assert calls == [
        ("activate", "session-a", "T-a", 30.0),
        ("revoke", "toggle_off"),
    ]
