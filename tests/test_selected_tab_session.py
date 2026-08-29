"""Task 3 — exact process-local lease for a selected Chrome tab.

All tests are offline. Browser targets, timers, BUS delivery, and desktop authority
use fakes; no Chrome/CDP/Playwright or native pointer operation is attempted.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest


class _Desktop:
    def __init__(self) -> None:
        self.claims: list[str] = []
        self.releases: list[str] = []
        self.owner = ""

    def claim_authority(self, owner: str) -> bool:
        self.claims.append(owner)
        if self.owner and self.owner != owner:
            return False
        self.owner = owner
        return True

    def release_authority(self, owner: str) -> None:
        self.releases.append(owner)
        if self.owner == owner:
            self.owner = ""


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


class _Timer:
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
        self.calls: list[tuple[float, _Timer]] = []

    def call_later(self, delay_s: float, callback):
        timer = _Timer(callback)
        self.calls.append((delay_s, timer))
        return timer


@pytest.fixture()
def browser_authority():
    from jarvis.automation.selected_tab_session import SelectedTabSessionOwner
    from jarvis.ui.screen_control import ScreenControlCoordinator

    now = [100.0]
    desktop = _Desktop()
    selected_tabs = SelectedTabSessionOwner(clock=lambda: now[0])
    bus = _Bus()
    scheduler = _Scheduler()
    coordinator = ScreenControlCoordinator(
        desktop=desktop,
        selected_tabs=selected_tabs,
        bus=bus,
        clock=lambda: now[0],
        scheduler=scheduler,
        selected_tab_scope_check=lambda session_id, task_id: (
            session_id in {"session-a", "session-b"}
            and task_id in {"T-a", "T-b"}
        ),
    )
    return coordinator, selected_tabs, desktop, bus, scheduler, now


def test_selected_tab_lease_requires_exact_bounded_identity_and_expires():
    from jarvis.automation.selected_tab_session import SelectedTabSessionOwner

    now = [10.0]
    owner = SelectedTabSessionOwner(clock=lambda: now[0])

    assert owner.activate(
        "session-a",
        "T-a",
        "target-opaque-a",
        target_generation=7,
        ttl_s=20,
    ) is True
    snapshot = owner.snapshot()
    assert snapshot.active is True
    assert snapshot.session_id == "session-a"
    assert snapshot.task_id == "T-a"
    assert snapshot.target_id == "target-opaque-a"
    assert snapshot.target_generation == 7
    assert snapshot.expires_at == pytest.approx(30.0)
    assert owner.binding_error(
        session_id="session-a",
        task_id="T-a",
        target_id="target-opaque-a",
        target_generation=7,
    ) == ""
    assert owner.binding_error(
        session_id="session-b",
        task_id="T-a",
        target_id="target-opaque-a",
        target_generation=7,
    ) == "selected_tab_lease_session_mismatch"
    assert owner.binding_error(
        session_id="session-a",
        task_id="T-b",
        target_id="target-opaque-a",
        target_generation=7,
    ) == "selected_tab_lease_task_mismatch"
    assert owner.binding_error(
        session_id="session-a",
        task_id="T-a",
        target_id="target-opaque-b",
        target_generation=7,
    ) == "selected_tab_lease_target_mismatch"
    assert owner.binding_error(
        session_id="session-a",
        task_id="T-a",
        target_id="target-opaque-a",
        target_generation=8,
    ) == "selected_tab_lease_generation_mismatch"

    now[0] = 31.0
    assert owner.activate(
        "session-b",
        "T-b",
        "target-opaque-b",
        target_generation=8,
        ttl_s=20,
    ) is False
    assert owner.binding_error(
        session_id="session-a",
        task_id="T-a",
        target_id="target-opaque-a",
        target_generation=7,
    ) == "selected_tab_lease_expired"
    assert owner.activate(
        "session-b",
        "T-b",
        "target-opaque-b",
        target_generation=8,
        ttl_s=20,
    ) is True


@pytest.mark.parametrize(
    "kwargs",
    [
        {"session_id": "", "task_id": "T-a", "target_id": "target-a", "target_generation": 1, "ttl_s": 10},
        {"session_id": "session-a", "task_id": "", "target_id": "target-a", "target_generation": 1, "ttl_s": 10},
        {"session_id": "session-a", "task_id": "T-a", "target_id": "", "target_generation": 1, "ttl_s": 10},
        {"session_id": "session-a", "task_id": "T-a", "target_id": "target-a", "target_generation": 0, "ttl_s": 10},
        {"session_id": "session-a", "task_id": "T-a", "target_id": "target-a", "target_generation": 1, "ttl_s": 0},
        {"session_id": "session-a", "task_id": "T-a", "target_id": "target-a", "target_generation": 1, "ttl_s": 3601},
    ],
)
def test_selected_tab_lease_rejects_incomplete_or_unbounded_claim(kwargs):
    from jarvis.automation.selected_tab_session import SelectedTabSessionOwner

    assert SelectedTabSessionOwner(clock=lambda: 10.0).activate(**kwargs) is False


def test_browser_tab_activation_requires_exact_live_task_scope():
    from jarvis.automation.selected_tab_session import SelectedTabSessionOwner
    from jarvis.ui.screen_control import ScreenControlCoordinator

    desktop = _Desktop()
    selected_tabs = SelectedTabSessionOwner(clock=lambda: 100.0)
    coordinator = ScreenControlCoordinator(
        desktop=desktop,
        selected_tabs=selected_tabs,
        bus=_Bus(),
        clock=lambda: 100.0,
        scheduler=_Scheduler(),
        selected_tab_scope_check=lambda session_id, task_id: (
            session_id == "session-live" and task_id == "T-live"
        ),
    )

    assert coordinator.activate_browser_tab(
        "session-other",
        "T-live",
        target_id="target-a",
        target_generation=1,
        ttl_s=30,
    ) is False
    assert coordinator.activate_browser_tab(
        "session-live",
        "T-other",
        target_id="target-a",
        target_generation=1,
        ttl_s=30,
    ) is False
    assert coordinator.snapshot().state == "off"
    assert selected_tabs.snapshot().active is False
    assert desktop.claims == []


def test_browser_tab_activation_never_claims_desktop_service(browser_authority):
    coordinator, selected_tabs, desktop, _bus, scheduler, _now = browser_authority

    assert coordinator.activate_browser_tab(
        "session-a",
        "T-a",
        target_id="target-opaque-a",
        target_generation=4,
        ttl_s=30,
    ) is True
    snapshot = coordinator.snapshot()

    assert snapshot.state == "active"
    assert snapshot.surface_kind == "browser_tab"
    assert snapshot.session_id == "session-a"
    assert snapshot.task_id == "T-a"
    assert snapshot.surface_id == "target-opaque-a"
    assert snapshot.surface_generation == 4
    assert selected_tabs.snapshot().active is True
    assert desktop.claims == []
    assert desktop.releases == []
    assert scheduler.calls[0][0] == pytest.approx(30.0)

    assert coordinator.begin_handoff("T-a") is True
    assert coordinator.resume_handoff("T-a") is True
    assert coordinator.revoke("toggle_off") is True
    assert selected_tabs.snapshot().active is False
    assert desktop.claims == []
    assert desktop.releases == []


def test_surface_contention_is_fail_closed(browser_authority):
    coordinator, _selected_tabs, desktop, _bus, _scheduler, _now = browser_authority

    assert coordinator.activate_browser_tab(
        "session-a",
        "T-a",
        target_id="target-a",
        target_generation=1,
        ttl_s=30,
    ) is True
    assert coordinator.activate("session-b", "T-b", ttl_s=30) is False
    assert desktop.claims == []

    assert coordinator.revoke("switch") is True
    assert coordinator.activate("session-b", "T-b", ttl_s=30) is True
    assert coordinator.activate_browser_tab(
        "session-a",
        "T-a",
        target_id="target-a",
        target_generation=1,
        ttl_s=30,
    ) is False
    assert desktop.claims == ["session-b"]


def test_selected_tab_policy_requires_exact_active_browser_binding(
    browser_authority,
    monkeypatch,
):
    from jarvis.agent import policy
    from jarvis.agent.execution_context import ExecutionContext
    from jarvis.ui import screen_control

    coordinator, _selected_tabs, _desktop, _bus, _scheduler, _now = browser_authority
    monkeypatch.setattr(screen_control, "COORDINATOR", coordinator)
    context = ExecutionContext.create(
        source="ui",
        actor_id="local-user",
        session_id="session-a",
        surface="browser_tab",
        toolsets={"selected_tab"},
    )
    runtime = SimpleNamespace(id="session-a", registry_task_id="T-a")

    assert policy.selected_tab_context_error(
        context,
        capability="selected_tab.observe",
        risk="low",
        runtime_session=runtime,
    ) == "selected_tab_not_active"
    assert coordinator.activate_browser_tab(
        "session-a",
        "T-a",
        target_id="target-a",
        target_generation=2,
        ttl_s=30,
    )
    assert policy.selected_tab_context_error(
        context,
        capability="selected_tab.observe",
        risk="low",
        runtime_session=runtime,
    ) == ""
    assert policy.selected_tab_context_error(
        context,
        capability="selected_tab.observe",
        risk="low",
        runtime_session=SimpleNamespace(id="session-a", registry_task_id="T-other"),
    ) == "selected_tab_task_mismatch"
    wrong_context = ExecutionContext.create(
        source="ui",
        actor_id="local-user",
        session_id="session-other",
        surface="browser_tab",
        toolsets={"selected_tab"},
    )
    assert policy.selected_tab_context_error(
        wrong_context,
        capability="selected_tab.observe",
        risk="low",
        runtime_session=runtime,
    ) == "selected_tab_context_session_mismatch"


def test_selected_tab_coordinator_rejects_wrong_target_and_generation(
    browser_authority,
):
    coordinator, selected_tabs, _desktop, _bus, _scheduler, _now = browser_authority
    assert coordinator.activate_browser_tab(
        "session-a",
        "T-a",
        target_id="target-a",
        target_generation=5,
        ttl_s=30,
    )

    assert coordinator.selected_tab_binding_error(
        session_id="session-a",
        task_id="T-a",
        target_id="target-other",
        target_generation=5,
    ) == "selected_tab_lease_target_mismatch"
    assert coordinator.selected_tab_binding_error(
        session_id="session-a",
        task_id="T-a",
        target_id="target-a",
        target_generation=6,
    ) == "selected_tab_lease_generation_mismatch"
    assert coordinator.revoke_browser_tab(
        target_id="target-other",
        target_generation=5,
        reason="selected_tab_target_closed",
    ) is False
    assert coordinator.revoke_browser_tab(
        target_id="target-a",
        target_generation=6,
        reason="selected_tab_target_closed",
    ) is False
    assert coordinator.snapshot().state == "active"
    assert selected_tabs.snapshot().active is True

    assert coordinator.revoke_browser_tab(
        target_id="target-a",
        target_generation=5,
        reason="selected_tab_target_closed",
    ) is True
    assert coordinator.snapshot().state == "off"
    assert selected_tabs.snapshot().active is False


def test_cross_surface_policy_denies_native_and_selected_tab_authority():
    from jarvis.agent import policy
    from jarvis.agent.execution_context import ExecutionContext

    browser_context = ExecutionContext.create(
        source="ui",
        actor_id="local-user",
        session_id="session-a",
        surface="browser_tab",
        toolsets={"desktop_safe", "selected_tab"},
    )
    desktop_context = ExecutionContext.create(
        source="ui",
        actor_id="local-user",
        session_id="session-a",
        surface="desktop",
        toolsets={"desktop_safe", "selected_tab"},
    )

    assert policy.decide(
        browser_context,
        capability="desktop_safe.desktop_observe",
        risk="low",
    ).allowed is False
    assert policy.decide(
        desktop_context,
        capability="selected_tab.observe",
        risk="low",
    ).allowed is False
    assert policy.decide(
        browser_context,
        capability="selected_tab.observe",
        risk="low",
    ).allowed is True


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
def test_browser_tab_bus_boundaries_revoke_once_without_desktop_authority(
    browser_authority,
    topic,
    payload,
):
    coordinator, selected_tabs, desktop, bus, _scheduler, _now = browser_authority
    assert coordinator.activate_browser_tab(
        "session-a",
        "T-a",
        target_id="target-a",
        target_generation=3,
        ttl_s=30,
    )

    bus.publish(topic, **payload)
    bus.publish(topic, **payload)

    assert coordinator.snapshot().state == "off"
    assert selected_tabs.snapshot().active is False
    assert desktop.claims == []
    assert desktop.releases == []


def test_browser_tab_timer_and_dispatch_cleanup_revoke_exact_lease(
    browser_authority,
    monkeypatch,
):
    from jarvis.agent import dispatch
    from jarvis.ui import screen_control

    coordinator, selected_tabs, desktop, _bus, scheduler, _now = browser_authority
    monkeypatch.setattr(screen_control, "COORDINATOR", coordinator)
    assert coordinator.activate_browser_tab(
        "session-a",
        "T-a",
        target_id="target-a",
        target_generation=3,
        ttl_s=30,
    )

    dispatch._release_screen_control_session("session-other")
    assert selected_tabs.snapshot().active is True
    dispatch._release_screen_control_session("session-a")
    assert selected_tabs.snapshot().active is False
    assert desktop.claims == []
    assert desktop.releases == []

    assert coordinator.activate_browser_tab(
        "session-b",
        "T-b",
        target_id="target-b",
        target_generation=4,
        ttl_s=15,
    )
    scheduler.calls[-1][1].fire()
    assert coordinator.snapshot().state == "off"
    assert selected_tabs.snapshot().active is False
    assert desktop.claims == []
    assert desktop.releases == []
