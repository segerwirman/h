"""Task 14 — human-only CAPTCHA handoff, verified with offline fakes."""
from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace

import pytest

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _element(
    element_id: str,
    *,
    role: str = "button",
    name: str = "Continue",
    states: dict | None = None,
) -> UIElement:
    return UIElement(
        element_id=element_id,
        scope=ElementScope.PAGE_MAIN,
        role=role,
        name=name,
        states=dict(states or {}),
        rect=(10, 20, 100, 40),
        visible=True,
        confidence=0.95,
        provenance="uia",
    )


def _tree(*elements: UIElement) -> ScreenElementTree:
    tree = ScreenElementTree()
    for element in elements:
        tree.add(element)
    return tree


def _context(session_id: str = "desktop-a") -> ExecutionContext:
    return ExecutionContext.create(
        source="agent",
        actor_id="local",
        session_id=session_id,
        surface="desktop",
        toolsets=["desktop_safe"],
    )


def test_handoff_is_non_executable_without_changing_confirm_semantics():
    from jarvis.automation.cua_safety import ConfirmationClass, SafetyDecision

    assert SafetyDecision(ConfirmationClass.ALLOW, "allow").allowed is True
    confirm = SafetyDecision(ConfirmationClass.CONFIRM, "confirm")
    assert confirm.allowed is True
    assert confirm.requires_confirmation is True
    assert SafetyDecision(ConfirmationClass.BLOCK, "block").allowed is False
    handoff = SafetyDecision(ConfirmationClass.HANDOFF, "handoff")
    assert handoff.allowed is False
    assert handoff.requires_confirmation is False


def test_captcha_anywhere_in_observation_precedes_target_classification():
    from jarvis.automation.cua_safety import ConfirmationClass, CuaSafetyGate

    gate = CuaSafetyGate()
    observation = gate.observe(
        surface_id="uia:offline",
        tree=_tree(
            _element("uia-continue"),
            _element(
                "uia-human-check",
                role="unknown",
                name="I'm not a robot",
            ),
        ),
        now=100.0,
    )
    ref = gate.reference(observation.id, "uia-continue", now=100.0)

    decision = gate.evaluate(ref, action="click", now=100.0)

    assert decision.classification is ConfirmationClass.HANDOFF
    assert decision.allowed is False


def test_private_uia_marker_is_detected_but_generic_verification_is_not():
    from jarvis.automation.cua_safety import ConfirmationClass, CuaSafetyGate

    gate = CuaSafetyGate()
    captcha = gate.observe(
        surface_id="uia:captcha",
        tree=_tree(
            _element(
                "uia-challenge",
                role="unknown",
                name="",
                states={
                    "_uia_class_name": "g-recaptcha challenge-stage",
                    "_uia_automation_id": "offline-fixture",
                },
            ),
        ),
        now=100.0,
    )
    ordinary = gate.observe(
        surface_id="uia:settings",
        tree=_tree(
            _element(
                "uia-verification-settings",
                name="Verification settings",
            ),
        ),
        now=100.0,
    )

    assert gate.classify_observation(captcha).classification is ConfirmationClass.HANDOFF
    assert gate.classify_observation(ordinary).classification is ConfirmationClass.ALLOW


def test_detection_bound_exhaustion_fails_closed_without_exposing_late_refs():
    from jarvis.automation.cua_safety import ConfirmationClass, CuaSafetyGate

    elements = tuple(
        _element(f"uia-safe-{index}", name="Continue")
        for index in range(501)
    )
    gate = CuaSafetyGate()
    observation = gate.observe(
        surface_id="uia:bounded",
        tree=_tree(*elements),
        now=100.0,
    )

    decision = gate.classify_observation(observation)

    assert decision.classification is ConfirmationClass.HANDOFF
    assert decision.allowed is False


def test_desktop_observe_emits_no_refs_or_source_text_for_captcha_observation(monkeypatch):
    from jarvis.agent.tools.desktop_observe import DesktopObserve
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    source_label = "OFFLINE CAPTCHA SOURCE LABEL"
    tree = _tree(
        _element("uia-safe", name="Continue"),
        _element(
            "uia-captcha-source",
            role="unknown",
            name=source_label,
            states={"_uia_class_name": "h-captcha"},
        ),
    )
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(
            gate,
            lambda: CaptureFrame("uia:offline", tree),
        ),
        click_rect=lambda _rect: None,
    )
    runtime_session = type(
        "Session",
        (),
        {
            "id": "desktop-a",
            "registry_task_id": "T-offline",
        },
    )()
    stages = []
    monkeypatch.setattr(
        "jarvis.agent.captcha_handoff.OWNER.stage",
        lambda **binding: stages.append(binding) or SimpleNamespace(),
    )

    result = asyncio.run(
        DesktopObserve(session=authority).run(
            _session=runtime_session,
            _context=_context(),
        )
    )
    visible = " ".join(
        (
            str(result.content),
            str(result.display),
            str(result.error),
            str(result.meta),
            result.for_llm(),
        )
    )

    assert result.ok is False
    assert source_label not in visible
    assert "uia-safe" not in visible
    assert "uia-captcha-source" not in visible
    assert len(stages) == 1
    assert stages[0]["session_id"] == "desktop-a"
    assert stages[0]["task_id"] == "T-offline"
    assert stages[0]["authority"] is authority
    assert not authority._owners
    assert not gate._observations


def test_uia_private_detection_metadata_is_bounded_and_not_agent_visible():
    from jarvis.agent.tools.desktop_observe import _safe_descriptor
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import _element_from_control

    class Rect:
        left, top, right, bottom = 10, 20, 110, 60

    private_class = "x" * 400
    control = SimpleNamespace(
        element_info=SimpleNamespace(
            control_type="Custom",
            class_name=private_class,
            automation_id="g-recaptcha-widget",
            is_dialog=False,
            runtime_id=(1, 2),
        ),
        window_text=lambda: "",
        friendly_class_name=lambda: "Custom",
        rectangle=lambda: Rect(),
        is_visible=lambda: True,
        is_enabled=lambda: True,
    )

    element = _element_from_control(control, 1)
    assert element is not None
    assert len(element.states["_uia_class_name"]) == 160
    assert element.states["_uia_automation_id"] == "g-recaptcha-widget"

    gate = CuaSafetyGate()
    observation = gate.observe(
        surface_id="uia:private",
        tree=_tree(element),
        now=100.0,
    )
    authority = SimpleNamespace(gate=gate)
    assert _safe_descriptor(
        authority,
        observation.id,
        element,
        ElementScope.PAGE_MAIN.value,
    ) is None


def test_handoff_wait_starts_only_after_dynamic_desktop_resource_is_released(
    monkeypatch,
):
    from jarvis.agent import captcha_handoff
    from jarvis.agent import loop as agent_loop
    from jarvis.agent.base import Tool, ToolResult
    from jarvis.agent.llm_client import ToolCall

    events: list[str] = []

    class OfflineObserve(Tool):
        name = "desktop_observe"
        description = "offline handoff fixture"
        read_only = True

        async def run(self, **_):
            captcha_handoff.OWNER.stage(
                session_id="session-a",
                task_id="T-offline",
                authority=SimpleNamespace(),
            )
            return ToolResult.fail("desktop_handoff_required")

    class Registry:
        def all_tools(self):
            return {"desktop_observe": OfflineObserve()}

        async def execute(self, name, args, adapter, session, context):
            assert name == "desktop_observe"
            return await OfflineObserve().run()

        def release_held(self, held):
            assert held == ["desktop"]
            events.append("dynamic_desktop_released")

    class Coordinator:
        def begin_handoff(self, task_id):
            events.append(f"screen_handoff:{task_id}")
            return True

    class WaitRegistry:
        def register_wait_continuation(self, task_id, token):
            events.append(f"register:{task_id}")
            return True

        def begin_wait(self, task_id, reason):
            events.append(f"wait:{task_id}:{reason}")
            return True

        def get(self, _task_id):
            return SimpleNamespace(status=SimpleNamespace(value="waiting"))

        def cancel(self, task_id):
            events.append(f"cancel:{task_id}")
            return True

        def clear_wait_continuation(self, task_id, token=None):
            events.append(f"clear:{task_id}")
            return True

    runtime_session = SimpleNamespace(
        id="session-a",
        registry_task_id="T-offline",
        captcha_handoff_id="",
        cancelled=False,
    )
    bg_task = SimpleNamespace(
        id="T-offline",
        cancel=threading.Event(),
    )

    monkeypatch.setattr(agent_loop, "registry", Registry())
    monkeypatch.setattr(
        agent_loop,
        "_acquire_for",
        lambda *_args: _async_value(["desktop"]),
    )
    monkeypatch.setattr(agent_loop, "_mark_pending_tool", lambda *_: None)
    monkeypatch.setattr(agent_loop, "_clear_pending_tool", lambda *_: None)
    monkeypatch.setattr(
        agent_loop,
        "_release_dynamic_resources",
        lambda held: Registry().release_held(held),
    )
    monkeypatch.setattr(agent_loop, "_task_update", lambda *_args, **_kwargs: None)
    captcha_handoff.OWNER.cancel_all("offline_test_reset")
    monkeypatch.setattr(captcha_handoff, "REGISTRY", WaitRegistry())
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", Coordinator())
    monkeypatch.setattr(
        captcha_handoff.OWNER,
        "_wait_for_completion",
        lambda *_args, **_kwargs: _async_value("cancelled"),
    )

    result = asyncio.run(
        agent_loop._execute_calls(
            [ToolCall(id="observe-1", name="desktop_observe", arguments={})],
            SimpleNamespace(progress=lambda _text: _async_value(None)),
            runtime_session,
            _context(),
            bg_task,
        )
    )

    assert result[0].ok is False
    assert events[:3] == [
        "dynamic_desktop_released",
        "register:T-offline",
        "screen_handoff:T-offline",
    ]
    assert "wait:T-offline:captcha_handoff" in events


def test_only_exact_local_completion_resumes_matching_live_handoff(monkeypatch):
    from jarvis.agent import captcha_handoff
    from jarvis.ui import window_commands

    calls: list[str] = []
    monkeypatch.setattr(
        captcha_handoff.OWNER,
        "complete_local",
        lambda text: calls.append(text) or True,
    )
    monkeypatch.setattr(window_commands, "_agent_ask_active", lambda: False)

    def window():
        target = SimpleNamespace(
            _pending_close_decision=None,
            _pending_voice_proposal_id=None,
            _skip_next_intercept=False,
            reply_flow=SimpleNamespace(
                handle_utterance=lambda _text: pytest.fail("reached reply flow")
            ),
            logs=[],
        )
        target.write_log = target.logs.append
        return target

    exact = window()
    window_commands.CommandRoutingMixin.handle_command(exact, "  cApTcHa selesai  ")

    assert calls == ["  cApTcHa selesai  "]
    assert exact.logs == ["SYS: CAPTCHA handoff dilanjutkan secara lokal."]

    calls.clear()
    monkeypatch.setattr(
        captcha_handoff.OWNER,
        "complete_local",
        lambda text: calls.append(text) or False,
    )
    prose = window()
    prose.reply_flow.handle_utterance = lambda _text: True
    window_commands.CommandRoutingMixin.handle_command(
        prose,
        "CAPTCHA selesai sekarang",
    )
    assert calls == ["CAPTCHA selesai sekarang"]
    assert prose.logs == ["You: CAPTCHA selesai sekarang"]


def test_remote_text_cannot_complete_process_local_handoff():
    from jarvis.agent.captcha_handoff import CaptchaHandoffOwner

    owner = CaptchaHandoffOwner(clock=lambda: 100.0)
    assert owner.complete_local("CAPTCHA selesai") is False
    assert not hasattr(owner, "complete_remote")
    assert not hasattr(owner, "complete_gateway")


def test_voice_and_gateway_modules_have_no_local_completion_hook():
    import inspect

    from jarvis.agent import captcha_handoff
    from jarvis.agent import dispatch
    from jarvis.agent.adapters import telegram
    from jarvis.gateway import runtime
    from jarvis.integrations import voice_native_tools

    for module in (dispatch, telegram, runtime, voice_native_tools):
        source = inspect.getsource(module)
        assert "complete_local" not in source
        assert "CaptchaHandoffOwner" not in source
    assert "complete_local" in inspect.getsource(captcha_handoff)


def test_resume_requires_fresh_marker_gone_observation_and_old_refs_stay_invalid(
    monkeypatch,
):
    from jarvis.agent import captcha_handoff
    from jarvis.agent.tasks import TaskStatus
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate, StaleObservationError

    safe_tree = _tree(_element("uia-safe", name="Continue"))
    captcha_tree = _tree(
        _element(
            "uia-challenge",
            role="unknown",
            name="I'm not a robot",
        )
    )
    frames = iter(
        (
            CaptureFrame("uia:offline", safe_tree),
            CaptureFrame("uia:offline", captcha_tree),
            CaptureFrame("uia:offline", safe_tree),
        )
    )
    gate = CuaSafetyGate(max_age_s=1000)
    authority = SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda _rect: None,
    )
    old = authority.observe_for("session-a")
    old_ref = gate.reference(old.id, "uia-safe")
    authority.clear_session("session-a")

    events: list[str] = []

    class Registry:
        def __init__(self):
            self.status = TaskStatus.WAITING

        def get(self, task_id):
            return SimpleNamespace(status=self.status, cancelled=False)

        def register_wait_continuation(self, task_id, token):
            events.append("register")
            return True

        def begin_wait(self, task_id, reason):
            self.status = TaskStatus.WAITING
            events.append("begin_wait")
            return True

        def resume_wait(self, task_id, token=None):
            self.status = TaskStatus.RUNNING
            events.append("resume_wait")
            return True

        def clear_wait_continuation(self, task_id, token=None):
            events.append("clear")
            return True

        def cancel(self, task_id):
            self.status = TaskStatus.CANCELLED
            events.append("cancel")
            return True

        def try_acquire(self, _task, resources):
            events.append("desktop_acquired")
            return ["desktop"]

        def release_held(self, held):
            events.append("desktop_released")

    class Coordinator:
        def begin_handoff(self, task_id):
            events.append("screen_handoff")
            return True

        def resume_handoff(self, task_id):
            events.append("screen_resumed")
            return True

        def release_task(self, task_id, reason=""):
            events.append("screen_released")
            return True

    registry = Registry()
    monkeypatch.setattr(captcha_handoff, "REGISTRY", registry)
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", Coordinator())

    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: 100.0)
    request = owner.stage(
        session_id="session-a",
        task_id="T-offline",
        authority=authority,
    )
    request.completed.set()
    outcome = asyncio.run(
        owner.resume_for_test(
            request,
            bg_task=SimpleNamespace(id="T-offline", cancel=threading.Event()),
        )
    )

    assert outcome == "waiting"
    assert events.index("resume_wait") < events.index("screen_resumed")
    assert events.index("screen_resumed") < events.index("desktop_acquired")
    assert events.index("desktop_acquired") < events.index("desktop_released")
    assert authority._owners == {}
    with pytest.raises(StaleObservationError):
        gate.evaluate(old_ref, action="click")


def test_marker_remaining_requires_second_local_completion_before_resuming(
    monkeypatch,
):
    from jarvis.agent import captcha_handoff
    from jarvis.agent.tasks import TaskStatus
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    captcha_tree = _tree(
        _element(
            "uia-challenge",
            role="unknown",
            name="I'm not a robot",
        )
    )
    safe_tree = _tree(_element("uia-safe", name="Continue"))
    frames = iter(
        (
            CaptureFrame("uia:captcha", captcha_tree),
            CaptureFrame("uia:safe", safe_tree),
        )
    )
    gate = CuaSafetyGate(max_age_s=1000)
    authority = SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda _rect: None,
    )
    events: list[str] = []

    class Registry:
        def __init__(self):
            self.status = TaskStatus.RUNNING
            self.continuation = None

        def get(self, _task_id):
            return SimpleNamespace(
                status=self.status,
                cancelled=self.status is TaskStatus.CANCELLED,
            )

        def register_wait_continuation(self, _task_id, token):
            self.continuation = token
            events.append("register")
            return self.status is TaskStatus.RUNNING

        def begin_wait(self, _task_id, _reason):
            if self.status is not TaskStatus.RUNNING or self.continuation is None:
                return False
            self.status = TaskStatus.WAITING
            events.append("begin_wait")
            return True

        def resume_wait(self, _task_id, token=None):
            if self.status is not TaskStatus.WAITING or token is not self.continuation:
                return False
            self.status = TaskStatus.RUNNING
            events.append("resume_wait")
            return True

        def clear_wait_continuation(self, _task_id, token=None):
            if token is not None and token is not self.continuation:
                return False
            self.continuation = None
            events.append("clear")
            return True

        def cancel(self, _task_id):
            self.status = TaskStatus.CANCELLED
            events.append("cancel")
            return True

        def try_acquire(self, _task, resources):
            assert resources == {"desktop"}
            events.append("desktop_acquired")
            return ["desktop"]

        def release_held(self, held):
            assert held == ["desktop"]
            events.append("desktop_released")

    class Coordinator:
        def begin_handoff(self, _task_id):
            events.append("screen_handoff")
            return True

        def resume_handoff(self, _task_id):
            events.append("screen_resumed")
            return True

        def release_task(self, _task_id, reason=""):
            events.append(f"screen_released:{reason}")
            return True

    class Bus:
        def __init__(self):
            self.events = []

        def publish(self, topic, **data):
            self.events.append((topic, data))

    registry = Registry()
    bus = Bus()
    monkeypatch.setattr(captcha_handoff, "REGISTRY", registry)
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", Coordinator())
    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: 100.0, bus=bus)
    request = owner.stage(
        session_id="session-a",
        task_id="T-offline",
        authority=authority,
    )
    session = SimpleNamespace(id="session-a", registry_task_id="T-offline")
    bg_task = SimpleNamespace(id="T-offline", cancel=threading.Event())

    async def exercise():
        pending = asyncio.create_task(owner.suspend_if_staged(session, bg_task))
        await _wait_until(lambda: request.state == "waiting")
        assert owner.complete_local("  CAPTCHA selesai  ") is True
        await _wait_until(lambda: events.count("begin_wait") == 2)
        assert pending.done() is False
        assert owner.complete_local("captcha SELESAI") is True
        return await asyncio.wait_for(pending, timeout=1.0)

    outcome = asyncio.run(exercise())

    assert outcome == "resumed"
    assert events.count("begin_wait") == 2
    assert events.count("resume_wait") == 2
    assert events.count("desktop_acquired") == 2
    assert events.count("desktop_released") == 2
    assert [topic for topic, _data in bus.events] == [
        "captcha.handoff.required",
        "captcha.handoff.required",
    ]
    assert owner._request is None
    assert authority._owners == {}
    assert gate._observations == {}


def test_background_task_cancellation_terminates_waiting_handoff(monkeypatch):
    from jarvis.agent import captcha_handoff
    from jarvis.agent.tasks import TaskStatus

    events = []

    class Registry:
        def __init__(self):
            self.status = TaskStatus.RUNNING

        def get(self, _task_id):
            return SimpleNamespace(
                status=self.status,
                cancelled=self.status is TaskStatus.CANCELLED,
            )

        def register_wait_continuation(self, _task_id, _token):
            return True

        def begin_wait(self, _task_id, _reason):
            self.status = TaskStatus.WAITING
            return True

        def clear_wait_continuation(self, _task_id, token=None):
            events.append("clear")
            return True

        def cancel(self, _task_id):
            self.status = TaskStatus.CANCELLED
            events.append("cancel")
            return True

    class Coordinator:
        def begin_handoff(self, _task_id):
            return True

        def release_task(self, _task_id, reason=""):
            events.append(f"release:{reason}")
            return True

    registry = Registry()
    monkeypatch.setattr(captcha_handoff, "REGISTRY", registry)
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", Coordinator())
    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: 100.0)
    request = owner.stage(
        session_id="session-a",
        task_id="T-offline",
        authority=SimpleNamespace(clear_session=lambda _session_id: None),
    )
    session = SimpleNamespace(id="session-a", registry_task_id="T-offline")
    bg_task = SimpleNamespace(id="T-offline", cancel=threading.Event())

    async def exercise():
        pending = asyncio.create_task(owner.suspend_if_staged(session, bg_task))
        await _wait_until(lambda: request.state == "waiting")
        bg_task.cancel.set()
        return await asyncio.wait_for(pending, timeout=1.0)

    outcome = asyncio.run(exercise())

    assert outcome == "cancelled"
    assert registry.status is TaskStatus.CANCELLED
    assert events == ["clear", "cancel", "release:cancelled"]
    assert owner._request is None


def test_timeout_cancels_exact_waiting_registry_task_and_retires_request(
    monkeypatch,
):
    from jarvis.agent import captcha_handoff
    from jarvis.agent.tasks import TaskRegistry, TaskStatus

    class Bus:
        def publish(self, _topic, **_data):
            return None

    class Coordinator:
        def __init__(self):
            self.releases = []

        def begin_handoff(self, _task_id):
            return True

        def release_task(self, task_id, reason=""):
            self.releases.append((task_id, reason))
            return True

    cleared = []
    authority = SimpleNamespace(
        clear_session=lambda session_id: cleared.append(session_id)
    )
    now = [100.0]
    registry = TaskRegistry(bus=Bus(), max_concurrent=1, queue_max=2)
    task = registry.submit("offline captcha handoff", resources={"desktop"})
    assert task is not None
    assert registry.acquire_slot(task) is True
    assert registry.mark_running(task.id) is not None
    coordinator = Coordinator()
    monkeypatch.setattr(captcha_handoff, "REGISTRY", registry)
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", coordinator)
    monkeypatch.setattr(captcha_handoff, "_timeout_s", lambda: 10.0)
    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: now[0], bus=Bus())
    request = owner.stage(
        session_id="session-a",
        task_id=task.id,
        authority=authority,
    )
    now[0] = 111.0

    outcome = asyncio.run(
        owner.suspend_if_staged(
            SimpleNamespace(id="session-a", registry_task_id=task.id),
            task,
        )
    )

    assert outcome == "cancelled"
    assert registry.get(task.id).status is TaskStatus.CANCELLED
    assert registry.resume_wait(task.id, request.token) is False
    assert coordinator.releases == [(task.id, "timeout")]
    assert owner._request is None
    assert cleared == ["session-a", "session-a"]


def test_mismatched_wait_continuation_cancels_instead_of_resuming(monkeypatch):
    from jarvis.agent import captcha_handoff
    from jarvis.agent.tasks import TaskStatus

    events = []

    class Registry:
        def __init__(self):
            self.status = TaskStatus.RUNNING
            self.continuation = None

        def get(self, _task_id):
            return SimpleNamespace(status=self.status, cancelled=False)

        def register_wait_continuation(self, _task_id, token):
            self.continuation = token
            return True

        def begin_wait(self, _task_id, _reason):
            self.status = TaskStatus.WAITING
            return True

        def resume_wait(self, _task_id, token=None):
            events.append("resume_attempt")
            return token is self.continuation

        def clear_wait_continuation(self, _task_id, token=None):
            events.append("clear")
            if token is not None and token is not self.continuation:
                return False
            self.continuation = None
            return True

        def cancel(self, _task_id):
            self.status = TaskStatus.CANCELLED
            events.append("cancel")
            return True

    class Coordinator:
        def begin_handoff(self, _task_id):
            return True

        def release_task(self, _task_id, reason=""):
            events.append(f"release:{reason}")
            return True

    registry = Registry()
    monkeypatch.setattr(captcha_handoff, "REGISTRY", registry)
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", Coordinator())
    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: 100.0)
    request = owner.stage(
        session_id="session-a",
        task_id="T-offline",
        authority=SimpleNamespace(clear_session=lambda _session_id: None),
    )
    session = SimpleNamespace(id="session-a", registry_task_id="T-offline")
    bg_task = SimpleNamespace(id="T-offline", cancel=threading.Event())

    async def exercise():
        pending = asyncio.create_task(owner.suspend_if_staged(session, bg_task))
        await _wait_until(lambda: request.state == "waiting")
        registry.continuation = object()
        assert owner.complete_local("CAPTCHA selesai") is True
        return await asyncio.wait_for(pending, timeout=1.0)

    outcome = asyncio.run(exercise())

    assert outcome == "cancelled"
    assert registry.status is TaskStatus.CANCELLED
    assert events == [
        "resume_attempt",
        "clear",
        "cancel",
        "release:resume_wait_failed",
    ]
    assert owner._request is None


def test_screen_control_expiry_proactively_cancels_waiting_handoff(monkeypatch):
    from jarvis.agent import captcha_handoff
    from jarvis.agent.tasks import TaskStatus
    from jarvis.core.bus import EventBus

    bus = EventBus()
    events = []

    class Registry:
        def clear_wait_continuation(self, task_id, token=None):
            events.append(f"clear:{task_id}")
            return True

        def cancel(self, task_id):
            events.append(f"cancel:{task_id}")
            return True

        def get(self, _task_id):
            return SimpleNamespace(status=TaskStatus.WAITING, cancelled=False)

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
        session_id="session-a",
        task_id="T-offline",
        authority=SimpleNamespace(clear_session=lambda _session_id: None),
    )
    request.state = "waiting"

    bus.publish(
        "screen_control.changed",
        state="off",
        active=False,
        reason="expired",
        expires_at=0.0,
    )

    assert owner._request is None
    assert events == [
        "clear:T-offline",
        "cancel:T-offline",
        "release:T-offline:screen_control_expired",
    ]


@pytest.mark.parametrize(
    "topic",
    (
        "emergency.stop",
        "window.closing",
        "application.shutdown",
        "agent.tasks.cancel_all",
    ),
)
def test_global_terminal_boundaries_cancel_waiting_handoff(monkeypatch, topic):
    from jarvis.agent import captcha_handoff
    from jarvis.core.bus import EventBus

    bus = EventBus()
    events = []

    class Registry:
        def clear_wait_continuation(self, task_id, token=None):
            events.append(f"clear:{task_id}")
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
        session_id="session-a",
        task_id="T-offline",
        authority=SimpleNamespace(clear_session=lambda _session_id: None),
    )
    request.state = "waiting"

    bus.publish(topic)

    assert owner._request is None
    assert events == [
        "clear:T-offline",
        "cancel:T-offline",
        f"release:T-offline:{topic}",
    ]


def test_matching_task_finish_cancels_but_unrelated_finish_does_not(monkeypatch):
    from jarvis.agent import captcha_handoff
    from jarvis.core.bus import EventBus

    bus = EventBus()
    events = []

    class Registry:
        def clear_wait_continuation(self, task_id, token=None):
            events.append(f"clear:{task_id}")
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
        session_id="session-a",
        task_id="T-offline",
        authority=SimpleNamespace(clear_session=lambda _session_id: None),
    )
    request.state = "waiting"

    bus.publish("task.finished", task={"id": "T-other"})
    assert owner._request is request
    assert events == []

    bus.publish("task.finished", task={"id": "T-offline"})
    assert owner._request is None
    assert events == [
        "clear:T-offline",
        "cancel:T-offline",
        "release:T-offline:task_terminal",
    ]


def test_reentrant_task_finished_cleanup_is_idempotent(monkeypatch):
    from jarvis.agent import captcha_handoff
    from jarvis.core.bus import EventBus

    bus = EventBus()
    events = []

    class Registry:
        def clear_wait_continuation(self, task_id, token=None):
            events.append(f"clear:{task_id}")
            return True

        def cancel(self, task_id):
            events.append(f"cancel:{task_id}")
            if events.count(f"cancel:{task_id}") == 1:
                bus.publish("task.finished", task={"id": task_id})
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
        session_id="session-a",
        task_id="T-offline",
        authority=SimpleNamespace(clear_session=lambda _session_id: None),
    )
    request.state = "waiting"

    assert owner.cancel_all("offline_cancel") is True

    assert events == [
        "clear:T-offline",
        "cancel:T-offline",
        "release:T-offline:offline_cancel",
    ]
    assert owner._request is None


def test_dispatch_cancellation_clears_handoff_before_task_identity(monkeypatch):
    import inspect

    from jarvis.agent import dispatch
    from jarvis.agent.session import Session

    events = []
    session = Session(task="offline")
    session.registry_task_id = "T-offline"
    handle = dispatch.TaskHandle("offline", session)
    handle.bg_task = SimpleNamespace(id="T-offline")
    monkeypatch.setattr(
        dispatch,
        "_clear_captcha_handoff_session",
        lambda session_id, reason="task_terminal": events.append(
            ("captcha", session_id, reason, session.registry_task_id)
        ),
    )
    monkeypatch.setattr(
        dispatch,
        "_release_screen_control_session",
        lambda session_id, reason="task_terminal": events.append(
            ("screen", session_id, reason, session.registry_task_id)
        ),
    )
    monkeypatch.setattr(dispatch, "_revoke_execution_grants", lambda _task_id: None)
    monkeypatch.setattr(handle, "cancel", lambda: events.append(("cancel",)))
    with dispatch._active_lock:
        previous = dict(dispatch._active)
        dispatch._active.clear()
        dispatch._active["offline"] = handle
    try:
        assert dispatch.cancel_task("T-offline") is True
    finally:
        with dispatch._active_lock:
            dispatch._active.clear()
            dispatch._active.update(previous)

    assert events[:2] == [
        ("captcha", session.id, "task_cancelled", "T-offline"),
        ("screen", session.id, "task_cancelled", "T-offline"),
    ]
    assert session.registry_task_id == ""
    source = inspect.getsource(dispatch.cancel_all)
    assert source.index("_clear_captcha_handoff_session") < source.index(
        'h.session.registry_task_id = ""'
    )


def test_handoff_module_has_no_solving_network_or_external_service_path():
    import inspect

    from jarvis.agent import captcha_handoff

    source = inspect.getsource(captcha_handoff).casefold()
    forbidden = (
        "2captcha",
        "anti-captcha",
        "anticaptcha",
        "captcha_solver",
        "captcha solver",
        "solve_captcha",
        "requests.",
        "httpx",
        "aiohttp",
        "urllib",
        "websocket",
    )
    assert all(marker not in source for marker in forbidden)


def test_local_notification_renderer_ignores_untrusted_payload_fields():
    from jarvis.ui.window_voice import WindowVoiceMixin

    source_secret = "OFFLINE CAPTCHA SOURCE SECRET"
    logs = []
    notifications = []
    target = SimpleNamespace(
        write_log=logs.append,
        notifications=SimpleNamespace(
            push=lambda title, body, level: notifications.append(
                (title, body, level)
            )
        ),
    )

    WindowVoiceMixin._on_captcha_handoff_required(
        target,
        {
            "title": source_secret,
            "body": source_secret,
            "observation_id": source_secret,
            "element_id": source_secret,
            "continuation": source_secret,
        },
    )

    visible = str((logs, notifications))
    assert source_secret not in visible
    assert notifications == [
        (
            "CAPTCHA memerlukan tindakan",
            "Selesaikan CAPTCHA secara manual, lalu ketik "
            "‘CAPTCHA selesai’ di aplikasi lokal.",
            "warning",
        )
    ]


async def _wait_until(predicate, *, attempts: int = 100) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.01)
    pytest.fail("offline handoff state did not settle")


def _async_value(value):
    async def resolve():
        return value

    return resolve()
