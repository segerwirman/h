"""Fase 11: TogglePattern hanya untuk checkbox UIA visible yang bounded."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _context(session_id: str = "desktop-a") -> ExecutionContext:
    return ExecutionContext.create(
        source="agent", actor_id="local", session_id=session_id, surface="desktop",
        toolsets=["desktop_safe"],
    )


def _tree(*, checked: bool = False, name: str = "Enable safe mode") -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-checkbox", ElementScope.PAGE_MAIN, "checkbox", name=name,
        rect=(10, 40, 180, 24), visible=True, confidence=.95, provenance="uia",
        states={"checked": checked, "_uia_runtime_id": "fixture-checkbox"},
    ))
    return tree


def _authority(*, name: str = "Enable safe mode"):
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(checked=False, name=name)),
        CaptureFrame("uia:fixture", _tree(checked=True, name=name)),
    ))
    gate = CuaSafetyGate()
    calls = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        toggle_native=lambda ref: calls.append(ref),
    )
    return authority, calls


def test_toggle_schema_accepts_only_opaque_observation_and_checkbox_ids():
    from jarvis.agent.tools.desktop_safe_toggle import DesktopSafeToggle

    props = DesktopSafeToggle().json_schema()["properties"]

    assert set(props) == {"observation_id", "element_id"}
    assert not {"x", "y", "label", "text", "checked", "value", "keys", "button", "drag"} & set(props)


def test_toggle_runs_once_on_safe_checkbox_and_recaptures_changed_state():
    authority, calls = _authority()
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.toggle(observation.id, "uia-checkbox", session_id="desktop-a")

    assert error == ""
    assert outcome.ok is True
    assert outcome.executed is True
    assert outcome.verified is True
    assert len(calls) == 1
    assert calls[0].element_id == "uia-checkbox"


def test_toggle_rejects_destructive_checkbox_before_lease_or_executor():
    authority, calls = _authority(name="Delete all local data")
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.toggle(observation.id, "uia-checkbox", session_id="desktop-a")

    assert outcome is None
    assert "konfirmasi" in error
    assert calls == []


def test_toggle_rejects_disabled_or_missing_binary_state_before_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    for states in (
        {"checked": False, "disabled": True, "_uia_runtime_id": "disabled"},
        {"disabled": False, "_uia_runtime_id": "missing-state"},
    ):
        tree = ScreenElementTree()
        tree.add(UIElement(
            "uia-checkbox", ElementScope.PAGE_MAIN, "checkbox", name="Safe mode",
            rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia", states=states,
        ))
        gate, calls = CuaSafetyGate(), []
        authority = SafeDesktopSession(
            gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
            lambda _rect: None, toggle_native=lambda ref: calls.append(ref),
        )
        observation = authority.observe_for("desktop-a")
        outcome, error = authority.toggle(observation.id, "uia-checkbox", session_id="desktop-a")

        assert outcome is None
        assert calls == []
        assert "checkbox" in error


def test_toggle_rejects_non_checkbox_and_unknown_ids_before_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    tree.add(UIElement(
        "uia-radio", ElementScope.PAGE_MAIN, "radio", name="Option A",
        rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
        states={"_uia_runtime_id": "radio"},
    ))
    gate, calls = CuaSafetyGate(), []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        lambda _rect: None, toggle_native=lambda ref: calls.append(ref),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.toggle(observation.id, "uia-radio", session_id="desktop-a")

    assert outcome is None
    assert "checkbox" in error
    assert calls == []


def test_toggle_tool_stays_desktop_local_and_not_voice_or_delegation_schema():
    from jarvis.agent import registry
    from jarvis.agent.tools.desktop_safe_toggle import DesktopSafeToggle
    from jarvis.integrations import voice_native_tools

    assert DesktopSafeToggle.name not in {item["name"] for item in voice_native_tools.declarations()}
    for surface, source, allowed in (
        ("desktop", "agent", True), ("remote", "telegram", False),
        ("voice", "gemini_live", False), ("desktop", "cron", False),
        ("desktop", "delegation", False),
    ):
        context = ExecutionContext.create(
            source=source, actor_id="local", session_id="desktop-a", surface=surface,
            toolsets=["desktop_safe"],
        )
        names = {item["function"]["name"] for item in registry.schemas(context=context)}
        assert (DesktopSafeToggle.name in names) is allowed


def test_desktop_observe_exposes_checkbox_as_opaque_toggle_ref():
    from jarvis.agent.tools.desktop_observe import DesktopObserve

    authority, _ = _authority()
    result = asyncio.run(DesktopObserve(session=authority).run(
        _session=type("Session", (), {"id": "desktop-a"})(), _context=_context()))

    assert result.ok is True
    assert result.content["elements"] == [{
        "element_id": "uia-checkbox", "role": "checkbox", "scope": "page_main",
        "actions": ["toggle"],
    }]
    assert "Enable safe mode" not in str(result.content)


def test_toggle_always_requires_native_local_confirmation():
    from jarvis.agent.tools.desktop_safe_toggle import DesktopSafeToggle

    tool = DesktopSafeToggle()
    assert tool.requires_confirmation is True
    assert "checkbox" in tool.confirmation_text().lower()


def test_toggle_has_no_click_type_key_drag_or_vision_api():
    from jarvis.agent.tools.desktop_safe_toggle import DesktopSafeToggle

    assert not {"click", "type", "key", "drag", "click_at", "vision_analyze"} & set(dir(DesktopSafeToggle))


def test_toggle_direct_run_rejects_missing_registry_confirmation_permit():
    from jarvis.agent.tools.desktop_safe_toggle import DesktopSafeToggle

    authority, calls = _authority()
    observation = authority.observe_for("desktop-a")
    result = asyncio.run(DesktopSafeToggle(session=authority).run(
        observation.id,
        "uia-checkbox",
        _session=type("Session", (), {"id": "desktop-a"})(),
        _context=_context(),
    ))

    assert result.ok is False
    assert "permit konfirmasi registry" in (result.error or "")
    assert calls == []
