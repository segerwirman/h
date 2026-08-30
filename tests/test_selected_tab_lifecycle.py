"""Offline lifecycle tests for one selected-tab CAPTCHA continuation."""
from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from types import SimpleNamespace

import pytest


class _Registry:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def resume_wait(self, _task_id, _token=None):
        self.events.append("resume_wait")
        return True

    def try_acquire(self, _task, _resources):
        raise AssertionError("browser-tab CAPTCHA must never acquire desktop")

    def begin_wait(self, _task_id, _reason):
        self.events.append("begin_wait")
        return True

    def clear_wait_continuation(self, _task_id, _token=None):
        self.events.append("clear_wait")
        return True

    def cancel(self, _task_id):
        self.events.append("cancel_task")
        return True


class _Coordinator:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def resume_handoff(self, _task_id):
        self.events.append("resume_surface")
        return True

    def begin_handoff(self, _task_id):
        self.events.append("repeat_handoff")
        return True

    def release_task(self, _task_id, reason=""):
        self.events.append(f"release_surface:{reason}")
        return True


class _BrowserTabAuthority:
    surface_kind = "browser_tab"

    def __init__(self, events: list[str], observations) -> None:
        self.events = events
        self.observations = iter(observations)

    def clear_session(self, session_id: str):
        self.events.append(f"clear_refs:{session_id}")
        return 1

    def observe_for(self, session_id: str):
        self.events.append(f"fresh_observe:{session_id}")
        result = next(self.observations)
        if isinstance(result, BaseException):
            raise result
        return result

    @staticmethod
    def observation_allowed(observation) -> bool:
        return bool(observation.ok)


def _resume(owner, request):
    return asyncio.run(
        owner.resume_for_test(
            request,
            bg_task=SimpleNamespace(id="T-selected", cancel=threading.Event()),
        )
    )


def test_browser_tab_captcha_resume_fresh_observes_without_desktop_resource(monkeypatch):
    from jarvis.agent import captcha_handoff

    events: list[str] = []
    monkeypatch.setattr(captcha_handoff, "REGISTRY", _Registry(events))
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", _Coordinator(events))
    authority = _BrowserTabAuthority(
        events,
        [SimpleNamespace(ok=True, state="observed")],
    )
    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: 100.0)
    request = owner.stage(
        session_id="session-selected",
        task_id="T-selected",
        authority=authority,
    )

    outcome = _resume(owner, request)

    assert outcome == "resumed"
    assert events == [
        "clear_refs:session-selected",
        "resume_wait",
        "resume_surface",
        "fresh_observe:session-selected",
        "clear_refs:session-selected",
        "clear_wait",
    ]
    assert owner._request is None


def test_browser_tab_marker_remaining_returns_to_same_waiting_continuation(monkeypatch):
    from jarvis.agent import captcha_handoff

    events: list[str] = []
    monkeypatch.setattr(captcha_handoff, "REGISTRY", _Registry(events))
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", _Coordinator(events))
    authority = _BrowserTabAuthority(
        events,
        [SimpleNamespace(ok=False, state="captcha_handoff")],
    )
    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: 100.0)
    request = owner.stage(
        session_id="session-selected",
        task_id="T-selected",
        authority=authority,
    )

    outcome = _resume(owner, request)

    assert outcome == "waiting"
    assert request.state == "waiting"
    assert events == [
        "clear_refs:session-selected",
        "resume_wait",
        "resume_surface",
        "fresh_observe:session-selected",
        "clear_refs:session-selected",
        "repeat_handoff",
        "begin_wait",
    ]
    assert owner._request is request


def test_browser_tab_disconnect_during_handoff_cancels_exact_task_and_surface(monkeypatch):
    from jarvis.agent import captcha_handoff

    events: list[str] = []
    monkeypatch.setattr(captcha_handoff, "REGISTRY", _Registry(events))
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", _Coordinator(events))
    authority = _BrowserTabAuthority(
        events,
        [RuntimeError("selected_tab_browser_disconnected")],
    )
    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: 100.0)
    request = owner.stage(
        session_id="session-selected",
        task_id="T-selected",
        authority=authority,
    )

    outcome = _resume(owner, request)

    assert outcome == "cancelled"
    assert events == [
        "clear_refs:session-selected",
        "resume_wait",
        "resume_surface",
        "fresh_observe:session-selected",
        "clear_refs:session-selected",
        "clear_wait",
        "cancel_task",
        "release_surface:fresh_observation_failed",
        "clear_refs:session-selected",
    ]
    assert owner._request is None


def test_selected_tab_terminal_release_retires_host_lease_overlay_and_timer_once():
    from jarvis.automation.selected_tab_session import SelectedTabSessionOwner
    from jarvis.ui.screen_control import ScreenControlCoordinator

    events: list[str] = []

    class Desktop:
        def claim_authority(self, _owner):
            raise AssertionError("browser-tab lifecycle must not claim desktop")

    class Timer:
        def cancel(self):
            events.append("timer_cancelled")

    class Scheduler:
        def call_later(self, _delay, _callback):
            return Timer()

    class Overlay:
        def clear(self):
            events.append("overlay_cleared")

        def show_state(self, **_kwargs):
            events.append("overlay_state")

        def update_visual(self, **_kwargs):
            events.append("overlay_visual")

        def pause_for_capture(self):
            return True

        def resume_after_capture(self):
            return None

    selected_tabs = SelectedTabSessionOwner(clock=lambda: 100.0)
    coordinator = ScreenControlCoordinator(
        desktop=Desktop(),
        selected_tabs=selected_tabs,
        clock=lambda: 100.0,
        scheduler=Scheduler(),
        overlay=Overlay(),
        selected_tab_scope_check=lambda session_id, task_id: (
            session_id == "session-selected" and task_id == "T-selected"
        ),
        selected_tab_release=lambda target_id, generation: events.append(
            f"host_released:{target_id}:{generation}"
        ) or True,
    )
    assert coordinator.activate_browser_tab(
        "session-selected",
        "T-selected",
        target_id="target-selected",
        target_generation=4,
        ttl_s=30,
    )

    assert coordinator.release_task("T-selected", "task_terminal") is True
    assert coordinator.release_task("T-selected", "task_terminal") is False

    assert coordinator.snapshot().state == "off"
    assert selected_tabs.snapshot().active is False
    assert events.count("host_released:target-selected:4") == 1
    assert events.count("timer_cancelled") == 1
    assert events[-1] == "overlay_cleared"


def test_target_close_while_waiting_proactively_cancels_exact_handoff(monkeypatch):
    from jarvis.agent import captcha_handoff
    from jarvis.agent.tasks import TaskStatus
    from jarvis.core.bus import EventBus

    events: list[str] = []
    bus = EventBus()

    class Registry:
        def get(self, _task_id):
            return SimpleNamespace(status=TaskStatus.WAITING, cancelled=False)

        def clear_wait_continuation(self, task_id, token=None):
            del token
            events.append(f"clear_wait:{task_id}")
            return True

        def cancel(self, task_id):
            events.append(f"cancel_task:{task_id}")
            return True

    class Coordinator:
        def release_task(self, task_id, reason=""):
            events.append(f"release_surface:{task_id}:{reason}")
            return True

    monkeypatch.setattr(captcha_handoff, "REGISTRY", Registry())
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", Coordinator())
    owner = captcha_handoff.CaptchaHandoffOwner(
        clock=lambda: 100.0,
        bus=bus,
        subscribe=True,
    )
    request = owner.stage(
        session_id="session-selected",
        task_id="T-selected",
        authority=SimpleNamespace(
            clear_session=lambda session_id: events.append(
                f"clear_refs:{session_id}"
            )
        ),
    )
    request.state = "waiting"

    bus.publish(
        "screen_control.changed",
        state="off",
        active=False,
        reason="selected_tab_target_closed",
    )

    assert owner._request is None
    assert events == [
        "clear_refs:session-selected",
        "clear_refs:session-selected",
        "clear_wait:T-selected",
        "cancel_task:T-selected",
        "release_surface:T-selected:selected_tab_target_closed",
    ]


@pytest.mark.parametrize(
    "terminal_reason",
    (
        "selected_tab_target_closed",
        "selected_tab_browser_disconnected",
        "selected_tab_target_navigated",
        "selected_tab_lease_generation_mismatch",
    ),
)
def test_selected_tab_terminal_reason_cancels_waiting_handoff(
    monkeypatch,
    terminal_reason,
):
    from jarvis.agent import captcha_handoff
    from jarvis.agent.tasks import TaskStatus
    from jarvis.core.bus import EventBus

    events: list[str] = []
    bus = EventBus()

    class Registry:
        def get(self, _task_id):
            return SimpleNamespace(status=TaskStatus.WAITING, cancelled=False)

        def clear_wait_continuation(self, _task_id, token=None):
            del token
            return True

        def cancel(self, task_id):
            events.append(f"cancel:{task_id}")
            return True

    class Coordinator:
        def release_task(self, task_id, reason=""):
            events.append(f"release:{task_id}:{reason}")
            return True

    monkeypatch.setattr(captcha_handoff, "REGISTRY", Registry())
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", Coordinator())
    owner = captcha_handoff.CaptchaHandoffOwner(
        clock=lambda: 100.0,
        bus=bus,
        subscribe=True,
    )
    request = owner.stage(
        session_id="session-selected",
        task_id="T-selected",
        authority=SimpleNamespace(clear_session=lambda _session_id: None),
    )
    request.state = "waiting"

    bus.publish(
        "screen_control.changed",
        state="off",
        active=False,
        reason=terminal_reason,
    )

    assert owner._request is None
    assert events == [
        "cancel:T-selected",
        f"release:T-selected:{terminal_reason}",
    ]


def test_screen_control_icon_opens_fake_picker_before_lifecycle_flow(monkeypatch):
    from jarvis.agent.dispatch import ScreenControlScope
    from jarvis.ui import screen_control
    from jarvis.ui.window_panels import WindowPanelsMixin

    calls: list[tuple[str, str, int, int]] = []
    sheet = SimpleNamespace(
        present=lambda scope, width, height: calls.append(
            (scope.session_id, scope.task_id, width, height)
        ) or True,
    )
    window = SimpleNamespace(
        tab_share_sheet=sheet,
        centralWidget=lambda: SimpleNamespace(width=lambda: 900, height=lambda: 700),
        write_log=lambda _message: None,
        notifications=SimpleNamespace(push=lambda *_args: None),
    )
    monkeypatch.setattr(
        screen_control.COORDINATOR,
        "snapshot",
        lambda: screen_control.ScreenControlSnapshot(),
    )
    monkeypatch.setattr(
        "jarvis.core.config.get",
        lambda key, default=None: (
            True if key == "screen_control.enabled" else default
        ),
    )
    monkeypatch.setattr(
        "jarvis.agent.dispatch.screen_control_scope",
        lambda: ScreenControlScope("session-selected", "T-selected"),
    )

    WindowPanelsMixin._toggle_screen_control(window)

    assert calls == [("session-selected", "T-selected", 900, 700)]


@dataclass(frozen=True)
class _Candidate:
    candidate_id: str
    title: str
    origin: str


class _LifecycleHost:
    def __init__(self) -> None:
        self.refs: dict[str, str] = {}
        self.preview_id = ""
        self.target_active = False
        self.stopped = 0
        self.observation_generation = 0
        self.observe_results = iter(
            ("observed", "captcha_handoff", "observed", "observed")
        )

    def begin_picker(self):
        return SimpleNamespace(
            ok=True,
            state="tabs_available",
            picker_id="picker-opaque",
            candidates=(
                _Candidate("candidate-opaque", "Offline tab", "https://safe.test"),
            ),
        )

    def select_candidate(self, picker_id: str, candidate_id: str):
        assert (picker_id, candidate_id) == (
            "picker-opaque",
            "candidate-opaque",
        )
        self.target_active = True
        return SimpleNamespace(
            ok=True,
            state="sharing",
            target=SimpleNamespace(
                target_id="target-opaque",
                target_generation=7,
            ),
        )

    def observe_selected(self, **binding):
        assert binding == {
            "session_id": "session-selected",
            "task_id": "T-selected",
            "target_id": "target-opaque",
            "target_generation": 7,
        }
        state = next(self.observe_results)
        if state == "captcha_handoff":
            self.refs.clear()
            self.preview_id = ""
            return SimpleNamespace(
                ok=False,
                state=state,
                reason="selected_tab_captcha_handoff_required",
            )
        self.observation_generation += 1
        observation_id = f"observation-{state}-{self.observation_generation}"
        element_id = f"element-{self.observation_generation}"
        self.refs[observation_id] = element_id
        return SimpleNamespace(
            ok=True,
            state="observed",
            observation_id=observation_id,
            elements=(SimpleNamespace(element_id=element_id),),
        )

    def act_selected(self, *, observation_id: str, element_id: str, **_binding):
        if self.refs.pop(observation_id, "") != element_id:
            return SimpleNamespace(
                ok=False,
                state="blocked",
                attempted=False,
                executed=False,
                verified=False,
                ambiguous=False,
            )
        self.preview_id = "preview-opaque"
        return SimpleNamespace(
            ok=True,
            state="verified",
            attempted=True,
            executed=True,
            verified=True,
            ambiguous=False,
            preview_id=self.preview_id,
        )

    def clear_semantic_session(self, _session_id: str):
        count = len(self.refs)
        self.refs.clear()
        self.preview_id = ""
        return count

    def stop_selected(self, target_id: str, target_generation: int):
        if not self.target_active:
            return False
        assert (target_id, target_generation) == ("target-opaque", 7)
        self.target_active = False
        self.refs.clear()
        self.preview_id = ""
        self.stopped += 1
        return True


def test_offline_selected_tab_end_to_end_captcha_resume_and_stop(monkeypatch):
    from jarvis.agent import captcha_handoff
    from jarvis.agent.tools.selected_tab import _SelectedTabCaptchaAuthority
    from jarvis.agent.tasks import TaskStatus
    from jarvis.automation.selected_tab_session import SelectedTabSessionOwner
    from jarvis.ui.screen_control import ScreenControlCoordinator

    events: list[str] = ["icon_opened"]
    host = _LifecycleHost()
    picker = host.begin_picker()
    events.append(picker.state)
    selected = host.select_candidate(
        picker.picker_id,
        picker.candidates[0].candidate_id,
    )
    target = selected.target
    events.append(selected.state)

    class Desktop:
        def claim_authority(self, _owner):
            raise AssertionError("offline browser-tab flow must not claim desktop")

    class Timer:
        def cancel(self):
            events.append("timer_cancelled")

    class Scheduler:
        def call_later(self, _delay, _callback):
            return Timer()

    selected_tabs = SelectedTabSessionOwner(clock=lambda: 100.0)
    coordinator = ScreenControlCoordinator(
        desktop=Desktop(),
        selected_tabs=selected_tabs,
        clock=lambda: 100.0,
        scheduler=Scheduler(),
        selected_tab_scope_check=lambda *_binding: True,
        selected_tab_release=host.stop_selected,
    )
    assert coordinator.activate_browser_tab(
        "session-selected",
        "T-selected",
        target_id=target.target_id,
        target_generation=target.target_generation,
        ttl_s=30,
    )
    events.append("share_active")

    first = host.observe_selected(
        session_id="session-selected",
        task_id="T-selected",
        target_id=target.target_id,
        target_generation=target.target_generation,
    )
    old_observation = first.observation_id
    action = host.act_selected(
        session_id="session-selected",
        task_id="T-selected",
        target_id=target.target_id,
        target_generation=target.target_generation,
        observation_id=first.observation_id,
        element_id=first.elements[0].element_id,
    )
    assert action.verified is True
    events.append("visual_verified")

    captcha = host.observe_selected(
        session_id="session-selected",
        task_id="T-selected",
        target_id=target.target_id,
        target_generation=target.target_generation,
    )
    assert captcha.state == "captcha_handoff"
    assert host.refs == {}
    assert host.preview_id == ""

    class Registry:
        def __init__(self):
            self.status = TaskStatus.RUNNING
            self.token = None

        def get(self, _task_id):
            return SimpleNamespace(status=self.status, cancelled=False)

        def register_wait_continuation(self, _task_id, token):
            self.token = token
            return True

        def begin_wait(self, _task_id, _reason):
            self.status = TaskStatus.WAITING
            events.append("waiting")
            return True

        def resume_wait(self, _task_id, token=None):
            assert token is self.token
            self.status = TaskStatus.RUNNING
            events.append("wait_resumed")
            return True

        def clear_wait_continuation(self, _task_id, token=None):
            assert token is self.token
            self.token = None
            return True

        def cancel(self, _task_id):
            self.status = TaskStatus.CANCELLED
            return True

        def try_acquire(self, _task, _resources):
            raise AssertionError("selected-tab CAPTCHA must not acquire desktop")

    registry = Registry()
    monkeypatch.setattr(captcha_handoff, "REGISTRY", registry)
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", coordinator)
    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: 100.0)
    authority = _SelectedTabCaptchaAuthority(
        host,
        task_id="T-selected",
        target_id=target.target_id,
        target_generation=target.target_generation,
    )
    request = owner.stage(
        session_id="session-selected",
        task_id="T-selected",
        authority=authority,
    )
    session = SimpleNamespace(
        id="session-selected",
        registry_task_id="T-selected",
    )
    bg_task = SimpleNamespace(id="T-selected", cancel=threading.Event())

    async def exercise():
        pending = asyncio.create_task(owner.suspend_if_staged(session, bg_task))
        for _ in range(100):
            if request.state == "waiting":
                break
            await asyncio.sleep(0.01)
        assert request.state == "waiting"
        assert owner.complete_local("CAPTCHA selesai") is True
        return await asyncio.wait_for(pending, timeout=1.0)

    assert asyncio.run(exercise()) == "resumed"
    assert registry.status is TaskStatus.RUNNING
    assert old_observation not in host.refs
    assert host.refs == {}
    fresh = host.observe_selected(
        session_id="session-selected",
        task_id="T-selected",
        target_id=target.target_id,
        target_generation=target.target_generation,
    )
    assert fresh.ok is True
    assert fresh.observation_id != old_observation
    events.append("captcha_resumed")

    assert coordinator.release_task("T-selected", "user_stop_sharing") is True
    assert coordinator.release_task("T-selected", "user_stop_sharing") is False
    assert host.target_active is False
    assert host.refs == {}
    assert host.preview_id == ""
    assert selected_tabs.snapshot().active is False
    assert coordinator.snapshot().state == "off"
    assert host.stopped == 1
    events.append("stopped")

    assert events == [
        "icon_opened",
        "tabs_available",
        "sharing",
        "share_active",
        "visual_verified",
        "waiting",
        "wait_resumed",
        "captcha_resumed",
        "timer_cancelled",
        "stopped",
    ]
