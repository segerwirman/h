"""Task 12 — Screen Control semantic actions stay ID-only and fail closed.

The suite uses semantic trees, fake native callbacks, and fake coordinator
snapshots only. It never reads a live desktop or moves the real pointer.
"""
from __future__ import annotations

import asyncio

import pytest
from pydantic import ValidationError

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _context(session_id: str = "desktop-a") -> ExecutionContext:
    return ExecutionContext.create(
        source="agent",
        actor_id="local",
        session_id=session_id,
        surface="desktop",
        toolsets=["desktop_safe"],
    )


def _tree(*, role="button", label="Open", marker="before") -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        element_id="uia-target",
        scope=ElementScope.PAGE_MAIN,
        role=role,
        name=label,
        rect=(10, 20, 100, 40),
        visible=True,
        confidence=.95,
        provenance="uia",
        states={"_uia_runtime_id": "fixture-target", "marker": marker},
    ))
    return tree


def _authority(*, role="button", native_error=False):
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(role=role, marker="before")),
        CaptureFrame("uia:fixture", _tree(role=role, marker="after")),
    ))
    calls = []

    def action(ref):
        calls.append(ref.element_id)
        if native_error:
            raise RuntimeError("fixture native error")

    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda _rect: None,
        right_click_native=action,
        double_click_native=action,
    )
    return authority, calls


@pytest.mark.parametrize(
    ("module_name", "class_name", "expected"),
    [
        (
            "jarvis.agent.tools.desktop_safe_right_click",
            "DesktopSafeRightClick",
            {"observation_id", "element_id"},
        ),
        (
            "jarvis.agent.tools.desktop_safe_double_click",
            "DesktopSafeDoubleClick",
            {"observation_id", "element_id"},
        ),
        (
            "jarvis.agent.tools.desktop_safe_text_entry",
            "DesktopSafeTextEntry",
            {"observation_id", "element_id", "text"},
        ),
    ],
)
def test_new_action_schemas_are_semantic_only(module_name, class_name, expected):
    module = __import__(module_name, fromlist=[class_name])
    tool_class = getattr(module, class_name)
    schema = tool_class.params_schema
    props = tool_class().json_schema()["properties"]

    assert set(props) == expected
    assert not {"x", "y", "button", "double", "delta", "keys"} & set(props)
    validator = getattr(schema, "model_validate", schema.parse_obj)
    payload = {"observation_id": "obs", "element_id": "uia-target"}
    if "text" in expected:
        payload["text"] = "Catatan aman"
    payload["x"] = 10
    with pytest.raises(ValidationError):
        validator(payload)


def test_scroll_schema_adds_only_bounded_count_and_rejects_raw_delta():
    from jarvis.agent.tools.desktop_safe_scroll import DesktopSafeScroll

    props = DesktopSafeScroll().json_schema()["properties"]
    validator = getattr(
        DesktopSafeScroll.params_schema,
        "model_validate",
        DesktopSafeScroll.params_schema.parse_obj,
    )

    assert set(props) == {"observation_id", "element_id", "direction", "count"}
    assert props["count"]["minimum"] == 1
    assert props["count"]["maximum"] == 5
    with pytest.raises(ValidationError):
        validator({
            "observation_id": "obs",
            "element_id": "uia-target",
            "direction": "down",
            "count": 6,
        })
    with pytest.raises(ValidationError):
        validator({
            "observation_id": "obs",
            "element_id": "uia-target",
            "direction": "down",
            "delta": 1000,
        })


@pytest.mark.parametrize(
    ("method_name", "callback_name"),
    [
        ("right_click", "right_click_native"),
        ("double_click", "double_click_native"),
    ],
)
def test_pointer_actions_invalidate_then_recapture_after_one_attempt(
    method_name, callback_name,
):
    authority, calls = _authority()
    before = authority.observe_for("desktop-a")

    outcome, error = getattr(authority, method_name)(
        before.id,
        "uia-target",
        session_id="desktop-a",
    )

    assert error == ""
    assert calls == ["uia-target"]
    assert outcome.executed is True
    assert outcome.verified is True
    assert outcome.after is not None
    assert outcome.after.id != before.id
    with pytest.raises(Exception, match="observasi"):
        authority.gate.reference(before.id, "uia-target")


def test_native_pointer_failure_still_invalidates_and_recaptures():
    authority, calls = _authority(native_error=True)
    before = authority.observe_for("desktop-a")

    outcome, error = authority.right_click(
        before.id,
        "uia-target",
        session_id="desktop-a",
    )

    assert error == ""
    assert calls == ["uia-target"]
    assert outcome.ok is False
    assert outcome.executed is True
    assert outcome.verified is False
    assert outcome.after is not None
    assert outcome.after.id != before.id
    with pytest.raises(Exception, match="observasi"):
        authority.gate.reference(before.id, "uia-target")


def test_native_scroll_failure_still_invalidates_and_recaptures():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(role="scrollbar", marker="before")),
        CaptureFrame("uia:fixture", _tree(role="scrollbar", marker="after")),
    ))
    calls = []

    def scroll(ref, delta):
        calls.append((ref.element_id, delta))
        raise RuntimeError("fixture native error")

    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda _rect: None,
        scroll_rect=lambda *_: None,
        scroll_native=scroll,
    )
    before = authority.observe_for("desktop-a")

    outcome, error = authority.scroll(
        before.id,
        "uia-target",
        direction="down",
        count=2,
        session_id="desktop-a",
    )

    assert error == ""
    assert calls == [("uia-target", -6)]
    assert outcome.ok is False
    assert outcome.executed is True
    assert outcome.verified is False
    assert outcome.after is not None
    assert outcome.after.id != before.id
    with pytest.raises(Exception, match="observasi"):
        authority.gate.reference(before.id, "uia-target")


def test_text_entry_invalidates_then_recaptures_after_committed_value_change():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(role="text_field", label="Notes", marker="before")),
        CaptureFrame("uia:fixture", _tree(role="text_field", label="Notes", marker="after")),
    ))
    calls = []

    def enter_text(ref, text):
        calls.append((ref.element_id, text))
        return True

    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda _rect: None,
        text_entry_native=enter_text,
    )
    before = authority.observe_for("desktop-a")

    outcome, error = authority.text_entry(
        before.id,
        "uia-target",
        text="Catatan aman",
        session_id="desktop-a",
    )

    assert error == ""
    assert calls == [("uia-target", "Catatan aman")]
    assert outcome.ok is True
    assert outcome.executed is True
    assert outcome.verified is True
    assert outcome.after is not None
    assert outcome.after.id != before.id
    with pytest.raises(Exception, match="observasi"):
        authority.gate.reference(before.id, "uia-target")


@pytest.mark.parametrize(
    ("label", "scope", "text", "reason"),
    [
        ("Password", ElementScope.PAGE_MAIN, "hello", "sensitif"),
        ("PIN", ElementScope.PAGE_MAIN, "hello", "sensitif"),
        ("Card number", ElementScope.PAGE_MAIN, "hello", "sensitif"),
        ("Search", ElementScope.BROWSER_ADDRESS, "hello", "address"),
        ("Notes", ElementScope.PAGE_MAIN, "x" * 501, "panjang"),
        ("Notes", ElementScope.PAGE_MAIN, "hello\x00world", "karakter"),
    ],
)
def test_text_entry_admission_blocks_sensitive_fields_and_unbounded_text(
    label, scope, text, reason,
):
    from jarvis.automation.cua_safety import admit_text_entry

    element = UIElement(
        element_id="uia-field",
        scope=scope,
        role="text_field",
        name=label,
        rect=(1, 2, 30, 20),
        visible=True,
        confidence=.95,
        provenance="uia",
        states={"_uia_runtime_id": "field-1"},
    )

    admission = admit_text_entry(element, text)

    assert admission.allowed is False
    assert reason in admission.reason
    assert admission.text == ""


def test_text_entry_admission_preserves_bounded_printable_unicode():
    from jarvis.automation.cua_safety import admit_text_entry

    element = UIElement(
        element_id="uia-field",
        scope=ElementScope.PAGE_MAIN,
        role="text_field",
        name="Catatan",
        rect=(1, 2, 30, 20),
        visible=True,
        confidence=.95,
        provenance="uia",
        states={"_uia_runtime_id": "field-1"},
    )

    admission = admit_text_entry(element, "Halo, dunia — baris dua\naman.")

    assert admission.allowed is True
    assert admission.text == "Halo, dunia — baris dua\naman."


def test_screen_control_gate_requires_exact_live_session_and_task(monkeypatch):
    from jarvis.agent import policy
    from jarvis.ui import screen_control

    runtime = type("Session", (), {
        "id": "desktop-a",
        "registry_task_id": "T-a",
    })()
    monkeypatch.setattr(
        screen_control.COORDINATOR,
        "snapshot",
        lambda: screen_control.ScreenControlSnapshot(
            screen_control.ACTIVE,
            "desktop-a",
            "T-a",
            999.0,
        ),
    )

    assert policy.screen_control_context_error(
        _context(),
        capability="desktop_safe.desktop_safe_right_click",
        runtime_session=runtime,
    ) == ""

    runtime.registry_task_id = "T-other"
    assert "task" in policy.screen_control_context_error(
        _context(),
        capability="desktop_safe.desktop_safe_right_click",
        runtime_session=runtime,
    )


@pytest.mark.parametrize(
    ("module_name", "class_name"),
    [
        ("jarvis.agent.tools.desktop_safe_right_click", "DesktopSafeRightClick"),
        ("jarvis.agent.tools.desktop_safe_double_click", "DesktopSafeDoubleClick"),
        ("jarvis.agent.tools.desktop_safe_text_entry", "DesktopSafeTextEntry"),
    ],
)
def test_new_actions_refuse_without_screen_control_before_native_executor(
    monkeypatch, module_name, class_name,
):
    from jarvis.ui import screen_control

    authority, calls = _authority(role="text_field" if "text_entry" in module_name else "button")
    observation = authority.observe_for("desktop-a")
    monkeypatch.setattr(
        screen_control.COORDINATOR,
        "snapshot",
        lambda: screen_control.ScreenControlSnapshot(),
    )
    module = __import__(module_name, fromlist=[class_name])
    tool = getattr(module, class_name)(session=authority)
    kwargs = {
        "observation_id": observation.id,
        "element_id": "uia-target",
        "_session": type("Session", (), {
            "id": "desktop-a",
            "registry_task_id": "T-a",
        })(),
        "_context": _context(),
        "_desktop_safe_confirmation": True,
    }
    if "text_entry" in module_name:
        kwargs["text"] = "Catatan aman"

    result = asyncio.run(tool.run(**kwargs))

    assert result.ok is False
    assert "screen_control" in (result.error or "")
    assert calls == []
