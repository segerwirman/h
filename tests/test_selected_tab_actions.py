"""Task 6 — one-attempt selected-tab actions with honest evidence.

All Page, ElementHandle, clock, coordinator, and registry dependencies are fakes.
The suite never launches Chrome, opens CDP, captures a screenshot, or performs
browser/native input outside the in-memory fakes in this file.
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from pydantic import ValidationError


class _Handle:
    def __init__(
        self,
        *,
        checked=None,
        click_error=None,
        click_started: threading.Event | None = None,
        click_release: threading.Event | None = None,
        click_delay: float = 0.0,
    ) -> None:
        self.box = {"x": 10, "y": 20, "width": 100, "height": 40}
        self.visible = True
        self.attached = True
        self.checked = checked
        self.value = ""
        self.click_error = click_error
        self.click_started = click_started
        self.click_release = click_release
        self.click_delay = click_delay
        self.click_calls = 0
        self.fill_calls: list[str] = []
        self.bounding_box_calls = 0
        self.on_click = None

    async def is_visible(self):
        return self.visible and self.attached

    async def bounding_box(self):
        self.bounding_box_calls += 1
        return self.box if self.attached else None

    async def click(self):
        self.click_calls += 1
        if self.click_started is not None:
            self.click_started.set()
        if self.click_release is not None:
            await asyncio.to_thread(self.click_release.wait, 2)
        if self.click_delay:
            await asyncio.sleep(self.click_delay)
        if callable(self.on_click):
            self.on_click()
        if self.click_error is not None:
            raise self.click_error

    async def fill(self, text):
        self.fill_calls.append(text)
        self.value = text

    async def input_value(self):
        return self.value

    async def is_checked(self):
        if not isinstance(self.checked, bool):
            raise RuntimeError("not-checkable")
        return self.checked

    async def get_attribute(self, name):
        if name == "aria-checked" and isinstance(self.checked, bool):
            return "true" if self.checked else "false"
        return None

    async def evaluate(self, expression):
        if "aria-expanded" in expression:
            return {
                "checked": self.checked,
                "selected": None,
                "expanded": None,
                "pressed": None,
                "value": self.value or None,
            }
        return None


class _Mouse:
    def __init__(self, page) -> None:
        self.page = page
        self.wheel_calls: list[tuple[int, int]] = []

    async def wheel(self, delta_x, delta_y):
        self.wheel_calls.append((delta_x, delta_y))
        self.page.scroll_y += delta_y


class _Page:
    def __init__(self) -> None:
        self.url = "https://safe.test/path?private=query#fragment"
        self.closed = False
        self.listeners: dict[str, list] = {}
        self.main_frame = object()
        self.scroll_y = 0
        self.mouse = _Mouse(self)

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    async def title(self):
        return "Private local title"

    def is_closed(self):
        return self.closed

    async def evaluate(self, _expression):
        return self.scroll_y


class _Context:
    def __init__(self, page) -> None:
        self.pages = [page]


class _Browser:
    def __init__(self, page) -> None:
        self.contexts = [_Context(page)]
        self.listeners: dict[str, list] = {}
        self.closed = False

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    async def close(self):
        self.closed = True


def _record(handle, *, role="button", name="Continue", text="", elem_type="", states=None):
    return {
        "handle": handle,
        "tag": "input" if role in {"checkbox", "text_field"} else "button",
        "role": role,
        "name": name,
        "label": "",
        "text": text,
        "type": elem_type,
        "container": "main",
        "visible": True,
        "rect": {"x": 10, "y": 20, "w": 100, "h": 40},
        "states": dict(states or {}),
    }


def _selected_host(records_provider):
    from jarvis.integrations.selected_tab_browser import SelectedTabBrowserHost

    page = _Page()
    browser = _Browser(page)
    page.browser = browser
    host = SelectedTabBrowserHost(
        connector=lambda _port: browser,
        enabled_check=lambda: True,
        port_provider=lambda: 9222,
        id_factory=iter(("picker", "candidate", "target")).__next__,
    )
    host._semantic_harvester = lambda _page: records_provider()
    host._semantic_binding_check = lambda *_args: ""
    serial = iter(range(1000))
    host._semantic_id_factory = lambda: f"opaque-{next(serial)}"
    picker = host.begin_picker()
    selection = host.select_candidate(
        picker.picker_id,
        picker.candidates[0].candidate_id,
    )
    assert selection.ok is True
    return host, page, selection.target


def _observe(host, target):
    return host.observe_selected(
        session_id="session-a",
        task_id="T-a",
        target_id=target.target_id,
        target_generation=target.target_generation,
    )


def _act(host, target, observation, element_id, action, **kwargs):
    method = getattr(host, "act_selected", None)
    assert callable(method), "act_selected host seam missing"
    return method(
        action=action,
        session_id="session-a",
        task_id="T-a",
        target_id=target.target_id,
        target_generation=target.target_generation,
        observation_id=observation.observation_id,
        element_id=element_id,
        **kwargs,
    )


def _classify(host, target, observation, element_id, action, **kwargs):
    method = getattr(host, "classify_action", None)
    assert callable(method), "classify_action host seam missing"
    return method(
        action=action,
        session_id="session-a",
        task_id="T-a",
        target_id=target.target_id,
        target_generation=target.target_generation,
        observation_id=observation.observation_id,
        element_id=element_id,
        **kwargs,
    )


def _evidence(result):
    return (
        result.attempted,
        result.executed,
        result.verified,
        result.ambiguous,
    )


class _NoopAdapter:
    async def ask(self, _question, _options):
        return "Batal"


class _Session:
    id = "session-a"
    registry_task_id = "T-a"

    def __init__(self):
        self.denied_confirmations = set()


class _Adapter:
    def __init__(self, answer="Batal") -> None:
        self.answer = answer
        self.questions = []

    async def ask(self, question, options):
        self.questions.append((question, tuple(options)))
        return self.answer


def _run(coro):
    return asyncio.run(coro)


def _tool_runtime(host, target):
    from jarvis.agent.execution_context import ExecutionContext

    context = ExecutionContext.create(
        source="ui",
        actor_id="local",
        session_id="session-a",
        surface="browser_tab",
        toolsets={"selected_tab"},
    )
    snapshot = SimpleNamespace(
        surface_id=target.target_id,
        surface_generation=target.target_generation,
    )
    return _Session(), context, snapshot


# Schema contract is intentionally tested through auto-discovery: selected-tab
# writers must stay protected by the existing capability overlay machinery.


def _selected_action_tools():
    from jarvis.agent import registry

    tools = registry.all_tools(refresh=True)
    names = (
        "selected_tab_click",
        "selected_tab_type",
        "selected_tab_scroll",
    )
    missing = [name for name in names if name not in tools]
    assert not missing, f"selected-tab action tools missing: {missing}"
    return {name: tools[name] for name in names}


def test_selected_tab_action_schemas_are_strict_and_opaque():
    tools = _selected_action_tools()
    expected = {
        "selected_tab_click": {"observation_id", "element_id"},
        "selected_tab_type": {"observation_id", "element_id", "text"},
        "selected_tab_scroll": {
            "observation_id",
            "element_id",
            "direction",
            "count",
        },
    }

    for name, tool in tools.items():
        schema = tool.json_schema()
        assert set(schema.get("properties", {})) == expected[name]
        assert set(schema.get("required", ())) == expected[name]
        assert schema.get("additionalProperties") is False
        visible = json.dumps(schema, sort_keys=True).casefold()
        for forbidden in (
            "target_id",
            "target_generation",
            "document_generation",
            "observation_generation",
            "selector",
            "xpath",
            '"x"',
            '"y"',
            "coordinate",
            "tab_index",
            "javascript",
            "cdp",
            "cookie",
            "storage",
            "pixel",
            "delta",
            "path",
        ):
            assert forbidden not in visible


def test_selected_tab_action_schemas_reject_extra_fields_and_bound_values():
    tools = _selected_action_tools()
    common = {"observation_id": "obs", "element_id": "element"}

    for tool in tools.values():
        with pytest.raises(ValidationError):
            tool.params_schema.model_validate({**common, "selector": "#private"})

    type_schema = tools["selected_tab_type"].params_schema
    type_schema.model_validate({**common, "text": "a" * 500})
    for text in ("", "a" * 501):
        with pytest.raises(ValidationError):
            type_schema.model_validate({**common, "text": text})

    scroll_schema = tools["selected_tab_scroll"].params_schema
    for direction in ("up", "down"):
        for count in (1, 5):
            parsed = scroll_schema.model_validate({
                **common,
                "direction": direction,
                "count": count,
            })
            assert parsed.direction == direction
            assert parsed.count == count
    for invalid in (
        {**common, "direction": "left", "count": 1},
        {**common, "direction": "down", "count": 0},
        {**common, "direction": "down", "count": 6},
        {**common, "direction": "down", "count": 1.5},
    ):
        with pytest.raises(ValidationError):
            scroll_schema.model_validate(invalid)


def test_click_consumes_ref_before_exact_one_attempt_and_verifies_state_change():
    handle = _Handle(checked=False)
    records = [_record(handle, role="checkbox", states={"checked": False})]
    host, _page, target = _selected_host(lambda: records)
    try:
        observation = _observe(host, target)
        element_id = observation.elements[0].element_id

        def change_state():
            handle.checked = True
            records[0] = _record(
                handle,
                role="checkbox",
                states={"checked": True},
            )

        handle.on_click = change_state
        result = _act(host, target, observation, element_id, "click")

        assert result.ok is True
        assert result.state == "verified"
        assert _evidence(result) == (True, True, True, False)
        assert handle.click_calls == 1
        assert result.after_observation is not None
        assert result.after_observation.observation_id != observation.observation_id

        reused = _act(host, target, observation, element_id, "click")
        assert reused.ok is False
        assert _evidence(reused) == (False, False, False, False)
        assert handle.click_calls == 1
    finally:
        host.shutdown()


@pytest.mark.parametrize("teardown", ("stop", "clear", "navigation", "close", "disconnect", "shutdown"))
def test_teardown_waits_for_inflight_action_semantic_critical_section(teardown):
    click_started = threading.Event()
    click_release = threading.Event()
    handle = _Handle(
        checked=False,
        click_started=click_started,
        click_release=click_release,
    )
    records = [_record(handle, role="checkbox", states={"checked": False})]
    host, page, target = _selected_host(lambda: records)
    observation = _observe(host, target)
    element_id = observation.elements[0].element_id

    def change_state():
        handle.checked = True
        records[0] = _record(
            handle,
            role="checkbox",
            states={"checked": True},
        )

    handle.on_click = change_state
    action_result = {}
    teardown_result = {}
    teardown_called = threading.Event()
    teardown_finished = threading.Event()

    def run_action():
        try:
            action_result["value"] = _act(
                host,
                target,
                observation,
                element_id,
                "click",
            )
        except BaseException as exc:
            action_result["error"] = exc

    async def emit_lifecycle_event_and_probe():
        if teardown == "navigation":
            frame = SimpleNamespace(url="https://safe.test/next")
            page.main_frame = frame
            for callback in tuple(page.listeners.get("framenavigated", ())):
                callback(frame)
        elif teardown == "close":
            page.closed = True
            for callback in tuple(page.listeners.get("close", ())):
                callback()
        else:
            for callback in tuple(page.browser.listeners.get("disconnected", ())):
                callback()
        await asyncio.sleep(0)
        return (
            host._semantic_lifecycle_lock().locked(),
            host._selected is not None,
        )

    def run_teardown():
        teardown_called.set()
        try:
            if teardown == "stop":
                teardown_result["value"] = host.stop_selected(
                    target.target_id,
                    target.target_generation,
                )
            elif teardown == "clear":
                teardown_result["value"] = host.clear_semantic_session("session-a")
            elif teardown in {"navigation", "close", "disconnect"}:
                teardown_result["during_action"] = host._call(
                    emit_lifecycle_event_and_probe
                )
            else:
                host.shutdown()
                teardown_result["value"] = "shutdown"
        except BaseException as exc:
            teardown_result["error"] = exc
        finally:
            teardown_finished.set()

    action_thread = threading.Thread(target=run_action)
    teardown_thread = threading.Thread(target=run_teardown)
    action_thread.start()
    assert click_started.wait(1)
    teardown_thread.start()
    assert teardown_called.wait(1)

    try:
        if teardown in {"stop", "clear", "shutdown"}:
            assert teardown_finished.wait(0.1) is False, teardown
        else:
            assert teardown_finished.wait(1), teardown
            assert teardown_result["during_action"] == (True, True)
    finally:
        click_release.set()
        action_thread.join(timeout=2)
        teardown_thread.join(timeout=2)
        after_action_snapshot = (
            host.active_snapshot() if teardown != "shutdown" else None
        )
        if teardown != "shutdown":
            host.shutdown()

    assert action_thread.is_alive() is False
    assert teardown_thread.is_alive() is False
    assert "error" not in action_result
    assert "error" not in teardown_result
    assert action_result["value"].attempted is True
    assert action_result["value"].executed is True
    assert handle.click_calls == 1
    if teardown in {"navigation", "close", "disconnect"}:
        assert after_action_snapshot.active is False
        assert action_result["value"].state == "executed_unverified"
        assert _evidence(action_result["value"]) == (True, True, False, True)
    else:
        assert "value" in teardown_result


def test_internal_action_timeout_preserves_ambiguous_attempt_evidence():
    handle = _Handle(click_delay=0.05)
    host, _page, target = _selected_host(lambda: [_record(handle)])
    host._action_timeout_s = 0.01
    try:
        observation = _observe(host, target)
        element_id = observation.elements[0].element_id

        result = _act(host, target, observation, element_id, "click")

        assert result.state == "attempt_ambiguous"
        assert _evidence(result) == (True, False, False, True)
        assert handle.click_calls == 1
        reused = _act(host, target, observation, element_id, "click")
        assert _evidence(reused) == (False, False, False, False)
        assert handle.click_calls == 1
    finally:
        host.shutdown()


def test_post_action_recapture_exception_preserves_executed_evidence():
    handle = _Handle(checked=False)
    records = [_record(handle, role="checkbox", states={"checked": False})]
    host, _page, target = _selected_host(lambda: records)
    try:
        observation = _observe(host, target)

        def break_recapture():
            handle.checked = True
            host._semantic_harvester = lambda _page: (_ for _ in ()).throw(
                RuntimeError("private recapture failure")
            )

        handle.on_click = break_recapture
        result = _act(
            host,
            target,
            observation,
            observation.elements[0].element_id,
            "click",
        )

        assert result.ok is False
        assert result.reason == "selected_tab_post_action_capture_failed"
        assert _evidence(result) == (True, True, False, True)
        assert handle.click_calls == 1
    finally:
        host.shutdown()


def test_playwright_exception_is_ambiguous_and_consumed_without_retry():
    handle = _Handle(click_error=RuntimeError("private page failure"))
    host, _page, target = _selected_host(lambda: [_record(handle)])
    try:
        observation = _observe(host, target)
        element_id = observation.elements[0].element_id

        result = _act(host, target, observation, element_id, "click")

        assert result.ok is False
        assert result.state == "attempt_ambiguous"
        assert _evidence(result) == (True, False, False, True)
        assert handle.click_calls == 1
        visible = json.dumps(asdict(result), default=str).casefold()
        assert "private page failure" not in visible

        reused = _act(host, target, observation, element_id, "click")
        assert _evidence(reused) == (False, False, False, False)
        assert handle.click_calls == 1
    finally:
        host.shutdown()


def test_click_without_explicit_postcondition_is_executed_unverified():
    handle = _Handle()
    host, _page, target = _selected_host(lambda: [_record(handle)])
    try:
        observation = _observe(host, target)
        result = _act(
            host,
            target,
            observation,
            observation.elements[0].element_id,
            "click",
        )

        assert result.ok is False
        assert result.state == "executed_unverified"
        assert _evidence(result) == (True, True, False, True)
        assert handle.click_calls == 1
    finally:
        host.shutdown()


def test_type_uses_fill_once_and_verifies_exact_value_without_leaking_text():
    secret = "OFFLINE VALUE MUST STAY PRIVATE"
    handle = _Handle()
    records = [_record(handle, role="text_field", elem_type="text")]
    host, _page, target = _selected_host(lambda: records)
    try:
        observation = _observe(host, target)
        result = _act(
            host,
            target,
            observation,
            observation.elements[0].element_id,
            "type",
            text=secret,
        )

        assert result.ok is True
        assert _evidence(result) == (True, True, True, False)
        assert handle.fill_calls == [secret]
        visible = json.dumps(asdict(result), default=str)
        assert secret not in visible
    finally:
        host.shutdown()


def test_scroll_uses_fixed_internal_delta_and_verifies_direction():
    handle = _Handle()
    records = [_record(handle, role="button", name="Article")]
    host, page, target = _selected_host(lambda: records)
    try:
        observation = _observe(host, target)
        result = _act(
            host,
            target,
            observation,
            observation.elements[0].element_id,
            "scroll",
            direction="down",
            count=2,
        )

        assert result.ok is True
        assert _evidence(result) == (True, True, True, False)
        assert len(page.mouse.wheel_calls) == 1
        delta_x, delta_y = page.mouse.wheel_calls[0]
        assert delta_x == 0
        assert delta_y > 0
        assert delta_y == page.scroll_y
    finally:
        host.shutdown()


def test_sensitive_full_label_is_not_issued_as_an_actionable_ref():
    handle = _Handle()
    records = [_record(handle, name="Continue", text="Transfer payment now")]
    host, _page, target = _selected_host(lambda: records)
    try:
        observation = _observe(host, target)
        assert observation.elements == ()
        assert handle.click_calls == 0
    finally:
        host.shutdown()


def test_destructive_term_in_element_text_requires_private_confirmation():
    handle = _Handle()
    records = [_record(handle, name="Continue", text="Send public reply")]
    host, _page, target = _selected_host(lambda: records)
    try:
        observation = _observe(host, target)
        element_id = observation.elements[0].element_id

        classification = _classify(
            host,
            target,
            observation,
            element_id,
            "click",
        )
        assert classification.allowed is True
        assert classification.requires_confirmation is True

        blocked = _act(host, target, observation, element_id, "click")

        assert blocked.ok is False
        assert blocked.state == "confirmation_required"
        assert blocked.requires_confirmation is True
        assert _evidence(blocked) == (False, False, False, False)
        assert handle.click_calls == 0
    finally:
        host.shutdown()


def test_destructive_action_executes_only_with_private_confirmation_marker():
    handle = _Handle(checked=False)
    records = [
        _record(
            handle,
            role="checkbox",
            name="Continue",
            text="Send public reply",
            states={"checked": False},
        )
    ]
    host, _page, target = _selected_host(lambda: records)
    try:
        observation = _observe(host, target)
        element_id = observation.elements[0].element_id

        def change_state():
            handle.checked = True
            records[0] = _record(
                handle,
                role="checkbox",
                name="Continue",
                text="Send public reply",
                states={"checked": True},
            )

        handle.on_click = change_state
        result = _act(
            host,
            target,
            observation,
            element_id,
            "click",
            confirmation=True,
        )

        assert result.ok is True
        assert _evidence(result) == (True, True, True, False)
        assert handle.click_calls == 1
    finally:
        host.shutdown()


def test_action_tool_maps_only_verified_host_result_to_success(monkeypatch):
    from jarvis.agent.tools.selected_tab import SelectedTabClick

    handle = _Handle(checked=False)
    records = [_record(handle, role="checkbox", states={"checked": False})]
    host, _page, target = _selected_host(lambda: records)
    session, context, snapshot = _tool_runtime(host, target)
    monkeypatch.setattr(
        "jarvis.agent.policy.selected_tab_context_error",
        lambda *_args, **_kwargs: "",
    )
    try:
        observation = _observe(host, target)
        element_id = observation.elements[0].element_id

        def change_state():
            handle.checked = True
            records[0] = _record(
                handle,
                role="checkbox",
                states={"checked": True},
            )

        handle.on_click = change_state
        tool = SelectedTabClick(host=host)
        tool._snapshot_provider = lambda: snapshot
        result = _run(tool.run(
            observation_id=observation.observation_id,
            element_id=element_id,
            _session=session,
            _context=context,
        ))

        assert result.ok is True
        assert result.meta["attempted"] is True
        assert result.meta["executed"] is True
        assert result.meta["verified"] is True
        assert result.meta["ambiguous"] is False
    finally:
        host.shutdown()


def test_navigation_release_notifies_lifecycle_after_inflight_action():
    click_started = threading.Event()
    click_release = threading.Event()
    lifecycle_events = []
    handle = _Handle(
        checked=False,
        click_started=click_started,
        click_release=click_release,
    )
    records = [_record(handle, role="checkbox", states={"checked": False})]
    host, page, target = _selected_host(lambda: records)
    host._lifecycle_callback = lambda *event: lifecycle_events.append(event)
    observation = _observe(host, target)
    result = {}

    def change_state():
        handle.checked = True
        records[0] = _record(
            handle,
            role="checkbox",
            states={"checked": True},
        )

    def run_action():
        result["value"] = _act(
            host,
            target,
            observation,
            observation.elements[0].element_id,
            "click",
        )

    handle.on_click = change_state
    action_thread = threading.Thread(target=run_action)
    action_thread.start()
    assert click_started.wait(1)

    async def navigate_and_probe():
        frame = SimpleNamespace(url="https://safe.test/next")
        page.main_frame = frame
        for callback in tuple(page.listeners.get("framenavigated", ())):
            callback(frame)
        await asyncio.sleep(0)
        return host._selected is not None, tuple(lifecycle_events)

    retained, events_during_action = host._call(navigate_and_probe)
    assert retained is True
    assert events_during_action == ()

    click_release.set()
    action_thread.join(timeout=2)
    try:
        snapshot = host.active_snapshot()
        assert action_thread.is_alive() is False
        assert snapshot.active is False
        assert lifecycle_events == [(
            target.target_id,
            target.target_generation,
            "selected_tab_target_navigated",
        )]
        assert _evidence(result["value"]) == (True, True, False, True)
    finally:
        host.shutdown()


def test_shutdown_waits_past_legacy_host_call_timeout_for_inflight_action():
    click_started = threading.Event()
    click_release = threading.Event()
    handle = _Handle(
        click_started=click_started,
        click_release=click_release,
    )
    host, _page, target = _selected_host(lambda: [_record(handle)])
    observation = _observe(host, target)
    host._host_call_timeout_s = 0.01
    action_result = {}
    shutdown_result = {}

    def run_action():
        try:
            action_result["value"] = _act(
                host,
                target,
                observation,
                observation.elements[0].element_id,
                "click",
            )
        except BaseException as exc:
            action_result["error"] = exc

    def run_shutdown():
        try:
            host.shutdown()
            shutdown_result["value"] = True
        except BaseException as exc:
            shutdown_result["error"] = exc

    action_thread = threading.Thread(target=run_action)
    shutdown_thread = threading.Thread(target=run_shutdown)
    action_thread.start()
    assert click_started.wait(1)
    shutdown_thread.start()
    assert shutdown_thread.join(timeout=0.05) is None
    assert shutdown_thread.is_alive() is True

    click_release.set()
    action_thread.join(timeout=2)
    shutdown_thread.join(timeout=2)

    assert "error" not in action_result
    assert "error" not in shutdown_result
    assert shutdown_result["value"] is True
    assert _evidence(action_result["value"]) == (True, True, False, True)


def test_action_tool_failure_content_is_structured_and_non_leaking(monkeypatch):
    from jarvis.agent.tools.selected_tab import SelectedTabClick

    handle = _Handle()
    host, _page, target = _selected_host(lambda: [_record(handle)])
    session, context, snapshot = _tool_runtime(host, target)
    monkeypatch.setattr(
        "jarvis.agent.policy.selected_tab_context_error",
        lambda *_args, **_kwargs: "",
    )
    try:
        observation = _observe(host, target)
        tool = SelectedTabClick(host=host)
        tool._snapshot_provider = lambda: snapshot

        result = _run(tool.run(
            observation_id=observation.observation_id,
            element_id=observation.elements[0].element_id,
            _session=session,
            _context=context,
        ))

        assert result.ok is False
        assert result.content == {
            "state": "executed_unverified",
            "attempted": True,
            "executed": True,
            "verified": False,
            "ambiguous": True,
            "requires_confirmation": False,
            "after_observation": result.content["after_observation"],
        }
        assert isinstance(result.content["after_observation"], dict)
        assert result.meta["do_not_retry"] is True
    finally:
        host.shutdown()


def test_action_exception_keeps_ref_consumed_before_fresh_observe():
    handle = _Handle(click_error=RuntimeError("private failure"))
    host, _page, target = _selected_host(lambda: [_record(handle)])
    try:
        observation = _observe(host, target)
        element_id = observation.elements[0].element_id

        result = _act(host, target, observation, element_id, "click")
        refreshed = _observe(host, target)

        assert _evidence(result) == (True, False, False, True)
        assert refreshed.ok is True
        assert refreshed.observation_id != observation.observation_id
        assert handle.click_calls == 1
    finally:
        host.shutdown()


def test_registry_discards_forged_selected_tab_confirmation_before_tool_run(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.base import Tool, ToolResult
    from jarvis.agent.capabilities import CapabilityDescriptor, REGISTRY

    class SelectedWriter(Tool):
        name = "selected_tab_click"
        wants_context = True

        def __init__(self):
            self.calls = []

        def needs_confirmation(self, **_kwargs):
            return True

        def confirmation_text(self, **_kwargs):
            return "Izinkan satu aksi selected tab?"

        async def run(self, **kwargs):
            self.calls.append(dict(kwargs))
            return ToolResult.success("ok")

    original = dict(REGISTRY._items)
    tool = SelectedWriter()
    REGISTRY._items.clear()
    REGISTRY.register(CapabilityDescriptor(
        id="selected_tab.click",
        tool_name=tool.name,
        toolset="selected_tab",
        risk="medium",
        timeout_s=5,
    ))
    overlay = SimpleNamespace()
    adapter = _Adapter(answer="Batal")
    session = _Session()
    context = SimpleNamespace()
    monkeypatch.setattr(registry, "get", lambda _name: tool)
    monkeypatch.setattr(
        "jarvis.agent.local_run_capabilities.selected_tab_context",
        lambda *_args, **_kwargs: (context, ""),
    )
    monkeypatch.setattr(
        "jarvis.agent.policy.selected_tab_context_error",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        "jarvis.agent.policy.decide",
        lambda *_args, **_kwargs: SimpleNamespace(
            allowed=True,
            needs_approval=False,
            reason="allowed",
        ),
    )
    try:
        result = _run(registry.execute(
            tool.name,
            {
                "observation_id": "obs",
                "element_id": "element",
                "_selected_tab_confirmation": True,
            },
            adapter=adapter,
            session=session,
            overlay=overlay,
        ))

        assert result.ok is False
        assert tool.calls == []
        assert len(adapter.questions) == 1
    finally:
        REGISTRY._items.clear()
        REGISTRY._items.update(original)


def test_post_action_captcha_stages_existing_handoff_without_source_text(monkeypatch):
    from jarvis.agent.tools.selected_tab import SelectedTabClick

    marker = "OFFLINE CAPTCHA SOURCE MUST STAY PRIVATE"
    handle = _Handle(checked=False)
    captcha = _Handle()
    records = [_record(handle, role="checkbox", states={"checked": False})]
    host, _page, target = _selected_host(lambda: records)
    session, context, snapshot = _tool_runtime(host, target)
    staged = []
    monkeypatch.setattr(
        "jarvis.agent.policy.selected_tab_context_error",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        "jarvis.agent.captcha_handoff.OWNER.stage",
        lambda **binding: staged.append(binding) or SimpleNamespace(),
    )
    try:
        observation = _observe(host, target)

        def reveal_captcha():
            handle.checked = True
            records[:] = [
                _record(
                    captcha,
                    role="unknown",
                    name=marker,
                )
            ]
            records[0]["class_name"] = "h-captcha challenge-stage"

        handle.on_click = reveal_captcha
        tool = SelectedTabClick(host=host)
        tool._snapshot_provider = lambda: snapshot
        result = _run(tool.run(
            observation_id=observation.observation_id,
            element_id=observation.elements[0].element_id,
            _session=session,
            _context=context,
        ))
        visible = " ".join(
            (str(result.content), str(result.error), str(result.meta), result.for_llm())
        )

        assert result.ok is False
        assert result.error == "selected_tab_handoff_required"
        assert result.meta["attempted"] is True
        assert result.meta["executed"] is True
        assert result.meta["verified"] is False
        assert result.meta["ambiguous"] is True
        assert marker not in visible
        assert len(staged) == 1
        assert staged[0]["session_id"] == "session-a"
        assert staged[0]["task_id"] == "T-a"
    finally:
        host.shutdown()


def test_registry_injects_selected_tab_confirmation_only_after_local_approval(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.base import Tool, ToolResult
    from jarvis.agent.capabilities import CapabilityDescriptor, REGISTRY

    class SelectedWriter(Tool):
        name = "selected_tab_click"
        wants_context = True

        def __init__(self):
            self.calls = []

        def needs_confirmation(self, **_kwargs):
            return True

        def confirmation_text(self, **_kwargs):
            return "Izinkan satu aksi selected tab?"

        async def run(self, **kwargs):
            self.calls.append(dict(kwargs))
            return ToolResult.success("ok")

    original = dict(REGISTRY._items)
    tool = SelectedWriter()
    REGISTRY._items.clear()
    REGISTRY.register(CapabilityDescriptor(
        id="selected_tab.click",
        tool_name=tool.name,
        toolset="selected_tab",
        risk="medium",
        timeout_s=5,
    ))
    adapter = _Adapter(answer="Lanjut")
    session = _Session()
    context = SimpleNamespace()
    monkeypatch.setattr(registry, "get", lambda _name: tool)
    monkeypatch.setattr(
        "jarvis.agent.local_run_capabilities.selected_tab_context",
        lambda *_args, **_kwargs: (context, ""),
    )
    monkeypatch.setattr(
        "jarvis.agent.policy.selected_tab_context_error",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        "jarvis.agent.policy.decide",
        lambda *_args, **_kwargs: SimpleNamespace(
            allowed=True,
            needs_approval=False,
            reason="allowed",
        ),
    )
    try:
        result = _run(registry.execute(
            tool.name,
            {"observation_id": "obs", "element_id": "element"},
            adapter=adapter,
            session=session,
            overlay=object(),
        ))

        assert result.ok is True
        assert len(tool.calls) == 1
        assert tool.calls[0]["_selected_tab_confirmation"] is True
    finally:
        REGISTRY._items.clear()
        REGISTRY._items.update(original)
