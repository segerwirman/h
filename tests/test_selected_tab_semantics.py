"""Task 5 — exact selected-tab semantic observation and privacy boundary.

All Page, ElementHandle, clock, coordinator, and CAPTCHA dependencies are fakes.
The suite never launches Chrome, opens CDP, captures a screenshot, or performs input.
"""
from __future__ import annotations

import asyncio
import json
import threading
from dataclasses import asdict
from types import SimpleNamespace


class _Handle:
    def __init__(self, name: str, *, box=None) -> None:
        self.name = name
        self.box = box or {"x": 10, "y": 20, "width": 100, "height": 40}
        self.visible = True
        self.attached = True
        self.bounding_box_calls = 0

    async def bounding_box(self):
        self.bounding_box_calls += 1
        return self.box if self.attached else None

    async def is_visible(self):
        return self.visible and self.attached


class _Page:
    def __init__(self, url: str = "https://safe.test/path?secret=query#fragment") -> None:
        self.url = url
        self._title = "Private local title"
        self.closed = False
        self.listeners: dict[str, list] = {}
        self.main_frame = object()

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    async def title(self):
        return self._title

    def is_closed(self):
        return self.closed


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


class _Clock:
    def __init__(self, now=100.0) -> None:
        self.now = now

    def __call__(self):
        return self.now


def _record(handle, *, tag="button", role="button", name="Continue", label="", text="",
            elem_type="", states=None, rect=None, **private):
    return {
        "handle": handle,
        "tag": tag,
        "role": role,
        "name": name,
        "label": label,
        "text": text,
        "type": elem_type,
        "container": "main",
        "visible": True,
        "rect": rect or {"x": 10, "y": 20, "w": 100, "h": 40},
        "states": dict(states or {}),
        **private,
    }


def _selected_host(records, *, clock=None):
    from jarvis.integrations.selected_tab_browser import SelectedTabBrowserHost

    page = _Page()
    browser = _Browser(page)
    ids = iter(("picker-opaque", "candidate-opaque", "target-opaque"))
    host = SelectedTabBrowserHost(
        connector=lambda _port: browser,
        enabled_check=lambda: True,
        port_provider=lambda: 9222,
        id_factory=lambda: next(ids),
    )
    host._semantic_harvester = lambda selected_page: records
    host._semantic_binding_check = lambda *_args: ""
    host._semantic_clock = clock or _Clock()
    host._semantic_id_factory = iter(
        ("observation-opaque-a", "element-opaque-a", "observation-opaque-b", "element-opaque-b")
    ).__next__
    picker = host.begin_picker()
    selected = host.select_candidate(
        picker.picker_id,
        picker.candidates[0].candidate_id,
    )
    assert selected.ok is True
    return host, browser, page, selected.target


def _observe(host, target, *, session_id="session-a", task_id="T-a"):
    observe = getattr(host, "observe_selected", None)
    if not callable(observe):
        return SimpleNamespace(ok=False, state="missing", reason="observe_selected_missing")
    return observe(
        session_id=session_id,
        task_id=task_id,
        target_id=target.target_id,
        target_generation=target.target_generation,
    )


def test_observe_returns_bounded_semantics_without_private_browser_data():
    safe = _Handle("safe-handle")
    password = _Handle("password-handle")
    upload = _Handle("upload-handle")
    download = _Handle("download-handle")
    permission = _Handle("permission-handle")
    records = [
        _record(
            safe,
            name="Continue to article " + "x" * 400,
            label="Primary action",
            text="Untrusted page text " + "y" * 500,
            states={"expanded": False, "focused": True, "private": "cookie-secret"},
            cookie="SID=private",
            selector="#raw-selector",
        ),
        _record(password, tag="input", role="", name="Password", elem_type="password"),
        _record(_Handle("pin-handle"), tag="input", role="", name="PIN", elem_type="text"),
        _record(_Handle("signin-handle"), role="button", name="Sign-in"),
        _record(upload, tag="input", role="", name="Upload passport", elem_type="file"),
        _record(download, tag="a", role="link", name="Download report", download="report.pdf"),
        _record(
            _Handle("hidden-download-handle"),
            tag="a",
            role="link",
            name="Safe-looking report",
            download="private-report.pdf",
        ),
        _record(
            _Handle("hidden-autocomplete-handle"),
            tag="input",
            role="",
            name="Account detail",
            elem_type="text",
            autocomplete="one-time-code",
        ),
        _record(permission, role="button", name="Allow camera permission"),
    ]
    host, _browser, _page, target = _selected_host(records)
    try:
        result = _observe(host, target)

        assert result.ok is True
        assert result.state == "observed"
        assert result.origin == "https://safe.test"
        assert result.target_generation == target.target_generation
        assert result.document_generation == 1
        assert result.observation_generation == 1
        assert result.observation_id == "observation-opaque-a"
        assert len(result.elements) == 1
        descriptor = result.elements[0]
        assert descriptor.element_id == "element-opaque-a"
        assert descriptor.role == "button"
        assert len(descriptor.name) <= 160
        assert len(descriptor.label) <= 160
        assert len(descriptor.text) <= 200
        assert descriptor.states == {"expanded": False, "focused": True}

        visible = json.dumps(asdict(result), ensure_ascii=False, default=str)
        for forbidden in (
            "target-opaque", "safe-handle", "password", "pin", "sign-in",
            "upload passport", "download report", "allow camera", "cookie-secret", "SID=private",
            "#raw-selector", "secret=query", "fragment", '"rect"', '"x"', '"y"',
        ):
            assert forbidden.casefold() not in visible.casefold()
    finally:
        host.shutdown()


def test_observe_rejects_wrong_exact_target_before_harvesting():
    calls = []
    host, _browser, _page, target = _selected_host([])
    host._semantic_harvester = lambda _page: calls.append("harvested") or []
    try:
        observe = getattr(host, "observe_selected", None)
        result = (
            observe(
                session_id="session-a",
                task_id="T-a",
                target_id="wrong-target",
                target_generation=target.target_generation,
            )
            if callable(observe)
            else SimpleNamespace(ok=False, reason="observe_selected_missing")
        )

        assert result.ok is False
        assert result.reason == "selected_tab_target_mismatch"
        assert calls == []
    finally:
        host.shutdown()


def test_observe_rejects_wrong_exact_session_or_task_before_harvesting():
    calls = []
    host, _browser, _page, target = _selected_host([])
    host._semantic_harvester = lambda _page: calls.append("harvested") or []
    host._semantic_binding_check = lambda session_id, task_id, *_: (
        "selected_tab_lease_session_mismatch"
        if session_id != "session-a"
        else "selected_tab_lease_task_mismatch" if task_id != "T-a" else ""
    )
    try:
        wrong_session = _observe(host, target, session_id="session-b")
        wrong_task = _observe(host, target, task_id="T-b")

        assert wrong_session.ok is False
        assert wrong_session.reason == "selected_tab_lease_session_mismatch"
        assert wrong_task.ok is False
        assert wrong_task.reason == "selected_tab_lease_task_mismatch"
        assert calls == []
    finally:
        host.shutdown()


def test_new_observation_and_ttl_retire_old_opaque_refs():
    clock = _Clock()
    handle = _Handle("same-handle")
    host, _browser, _page, target = _selected_host([_record(handle)], clock=clock)
    try:
        first = _observe(host, target)
        check = getattr(host, "element_ref_is_actionable", None)
        assert callable(check)
        assert check(
            session_id="session-a",
            task_id="T-a",
            observation_id=first.observation_id,
            element_id=first.elements[0].element_id,
            target_id=target.target_id,
            target_generation=target.target_generation,
            document_generation=first.document_generation,
            observation_generation=first.observation_generation,
        ) is True

        second = _observe(host, target)
        assert second.ok is True
        assert second.observation_generation == first.observation_generation + 1
        assert check(
            session_id="session-a",
            task_id="T-a",
            observation_id=first.observation_id,
            element_id=first.elements[0].element_id,
            target_id=target.target_id,
            target_generation=target.target_generation,
            document_generation=first.document_generation,
            observation_generation=first.observation_generation,
        ) is False

        clock.now = second.expires_at + 0.001
        assert check(
            session_id="session-a",
            task_id="T-a",
            observation_id=second.observation_id,
            element_id=second.elements[0].element_id,
            target_id=target.target_id,
            target_generation=target.target_generation,
            document_generation=second.document_generation,
            observation_generation=second.observation_generation,
        ) is False
    finally:
        host.shutdown()


def test_action_eligibility_rereads_geometry_from_same_handle_without_requery():
    handle = _Handle("stable-handle")
    harvest_calls = []
    records = [_record(handle)]
    host, _browser, _page, target = _selected_host(records)
    host._semantic_harvester = lambda _page: harvest_calls.append("capture") or records
    try:
        observation = _observe(host, target)
        assert observation.ok is True
        assert harvest_calls == ["capture"]
        captured_box_calls = handle.bounding_box_calls

        check = getattr(host, "element_ref_is_actionable", None)
        assert callable(check)
        assert check(
            session_id="session-a",
            task_id="T-a",
            observation_id=observation.observation_id,
            element_id=observation.elements[0].element_id,
            target_id=target.target_id,
            target_generation=target.target_generation,
            document_generation=observation.document_generation,
            observation_generation=observation.observation_generation,
        ) is True
        assert handle.bounding_box_calls == captured_box_calls + 1
        assert harvest_calls == ["capture"]

        handle.attached = False
        assert check(
            session_id="session-a",
            task_id="T-a",
            observation_id=observation.observation_id,
            element_id=observation.elements[0].element_id,
            target_id=target.target_id,
            target_generation=target.target_generation,
            document_generation=observation.document_generation,
            observation_generation=observation.observation_generation,
        ) is False
    finally:
        host.shutdown()


def test_navigation_and_stop_clear_semantic_refs_for_exact_target():
    handle = _Handle("stable-handle")
    host, _browser, page, target = _selected_host([_record(handle)])
    try:
        observation = _observe(host, target)
        assert observation.ok is True
        check = getattr(host, "element_ref_is_actionable", None)
        clear = getattr(host, "clear_semantic_session", None)
        assert callable(check) and callable(clear)
        assert clear("wrong-session") == 0
        assert clear("session-a") == 1
        assert check(
            session_id="session-a",
            task_id="T-a",
            observation_id=observation.observation_id,
            element_id=observation.elements[0].element_id,
            target_id=target.target_id,
            target_generation=target.target_generation,
            document_generation=observation.document_generation,
            observation_generation=observation.observation_generation,
        ) is False

        refreshed = _observe(host, target)
        assert refreshed.ok is True
        frame = SimpleNamespace(url="https://safe.test/next")
        page.main_frame = frame
        for callback in tuple(page.listeners.get("framenavigated", ())):
            callback(frame)
        assert host.active_snapshot().active is False
        assert check(
            session_id="session-a",
            task_id="T-a",
            observation_id=refreshed.observation_id,
            element_id=refreshed.elements[0].element_id,
            target_id=target.target_id,
            target_generation=target.target_generation,
            document_generation=refreshed.document_generation,
            observation_generation=refreshed.observation_generation,
        ) is False
    finally:
        host.shutdown()


def test_host_captcha_result_contains_no_source_text_or_opaque_refs():
    source_label = "OFFLINE CAPTCHA SOURCE MUST STAY PRIVATE"
    records = [
        _record(_Handle("safe"), name="Continue"),
        _record(
            _Handle("captcha"),
            role="unknown",
            name=source_label,
            class_name="h-captcha challenge-stage",
        ),
    ]
    host, _browser, _page, target = _selected_host(records)
    try:
        result = _observe(host, target)
        visible = json.dumps(asdict(result), ensure_ascii=False, default=str)

        assert result.ok is False
        assert result.state == "captcha_handoff"
        assert result.observation_id == ""
        assert result.elements == ()
        assert source_label not in visible
        assert "Continue" not in visible
        assert "observation-opaque" not in visible
        assert "element-opaque" not in visible
    finally:
        host.shutdown()


def test_captcha_is_classified_before_text_or_refs_escape_and_stages_human_handoff(monkeypatch):
    from jarvis.agent.execution_context import ExecutionContext

    source_label = "OFFLINE CAPTCHA SOURCE MUST STAY PRIVATE"
    records = [
        _record(_Handle("safe"), name="Continue"),
        _record(
            _Handle("captcha"),
            role="unknown",
            name=source_label,
            class_name="h-captcha challenge-stage",
        ),
    ]
    host, _browser, _page, target = _selected_host(records)
    staged = []
    monkeypatch.setattr(
        "jarvis.agent.policy.selected_tab_context_error",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        "jarvis.agent.captcha_handoff.OWNER.stage",
        lambda **binding: staged.append(binding) or SimpleNamespace(),
    )
    monkeypatch.setattr(
        "jarvis.agent.tools.selected_tab.selected_tab_context_error",
        lambda *_args, **_kwargs: "",
        raising=False,
    )
    runtime = SimpleNamespace(id="session-a", registry_task_id="T-a")
    context = ExecutionContext.create(
        source="ui",
        actor_id="local",
        session_id="session-a",
        surface="browser_tab",
        toolsets={"selected_tab"},
    )
    try:
        from jarvis.agent.tools.selected_tab import SelectedTabObserve

        tool = SelectedTabObserve(host=host)
        tool._snapshot_provider = lambda: SimpleNamespace(
            surface_id=target.target_id,
            surface_generation=target.target_generation,
        )
        result = asyncio.run(tool.run(_session=runtime, _context=context))
        visible = " ".join(
            (str(result.content), str(result.error), str(result.display), str(result.meta), result.for_llm())
        )

        assert result.ok is False
        assert result.error == "selected_tab_handoff_required"
        assert source_label not in visible
        assert "Continue" not in visible
        assert "target-opaque" not in visible
        assert "observation-opaque" not in visible
        assert len(staged) == 1
        assert staged[0]["session_id"] == "session-a"
        assert staged[0]["task_id"] == "T-a"
        assert staged[0]["authority"].surface_kind == "browser_tab"
    finally:
        host.shutdown()


def test_captcha_resume_for_browser_tab_fresh_observes_without_desktop_reacquisition(monkeypatch):
    from jarvis.agent import captcha_handoff

    events = []

    class Registry:
        def resume_wait(self, _task_id, _token=None):
            events.append("resume_wait")
            return True

        def try_acquire(self, _task, _resources):
            raise AssertionError("browser-tab CAPTCHA must never acquire desktop")

        def clear_wait_continuation(self, _task_id, _token=None):
            events.append("clear")
            return True

        def cancel(self, _task_id):
            events.append("cancel")
            return True

    class Coordinator:
        def resume_handoff(self, _task_id):
            events.append("screen_resumed")
            return True

        def release_task(self, _task_id, reason=""):
            events.append(f"released:{reason}")
            return True

    authority = SimpleNamespace(
        surface_kind="browser_tab",
        clear_session=lambda session_id: events.append(f"clear_refs:{session_id}"),
        observe_for=lambda session_id: events.append(f"fresh_observe:{session_id}")
        or SimpleNamespace(ok=True, state="observed"),
        observation_allowed=lambda observation: bool(observation.ok),
    )
    monkeypatch.setattr(captcha_handoff, "REGISTRY", Registry())
    monkeypatch.setattr(captcha_handoff, "COORDINATOR", Coordinator())
    owner = captcha_handoff.CaptchaHandoffOwner(clock=lambda: 100.0)
    request = owner.stage(
        session_id="session-a",
        task_id="T-a",
        authority=authority,
    )

    outcome = asyncio.run(
        owner.resume_for_test(
            request,
            bg_task=SimpleNamespace(id="T-a", cancel=threading.Event()),
        )
    )

    assert outcome == "resumed"
    assert "desktop_acquired" not in events
    assert events == [
        "clear_refs:session-a",
        "resume_wait",
        "screen_resumed",
        "fresh_observe:session-a",
        "clear_refs:session-a",
        "clear",
    ]


def test_selected_tab_audit_keeps_output_and_browser_binding_private():
    from jarvis.agent import registry

    args = {
        "target_id": "private-target",
        "observation_id": "private-observation",
        "element_id": "private-element",
        "selector": "#private-selector",
    }

    assert registry._audit_args("selected_tab_observe", args) == {
        "action": "selected_tab_observe"
    }
    assert registry._audit_error(
        "selected_tab_observe", "private page failure"
    ) == "selected_tab_failed"


def test_selected_tab_observe_schema_has_no_selector_coordinate_or_browser_inventory():
    from jarvis.agent import registry

    tools = registry.all_tools(refresh=True)
    tool = tools.get("selected_tab_observe")
    assert tool is not None
    assert tool.read_only is True
    schema = json.dumps(tool.json_schema(), sort_keys=True).casefold()
    assert tool.json_schema().get("properties") == {}
    for forbidden in (
        "selector", "xpath", '"x"', '"y"', "coordinate", "tab_index",
        "target_id", "javascript", "cookie", "storage", "screenshot",
    ):
        assert forbidden not in schema
