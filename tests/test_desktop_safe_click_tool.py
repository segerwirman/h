"""Native desktop_safe_click only consumes semantic observation and element IDs."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _tree(name: str = "Next", *, runtime_id: str = "fixture-button") -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        element_id="uia-next", scope=ElementScope.PAGE_MAIN, role="button",
        name=name, rect=(10, 20, 100, 40), visible=True,
        confidence=0.95, provenance="uia",
        states={"_uia_runtime_id": runtime_id},
    ))
    return tree


def test_safe_click_rejects_replaced_target_before_executor_even_when_id_rect_surface_match():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(runtime_id="original")),
        CaptureFrame("uia:fixture", _tree(runtime_id="replacement")),
    ))
    clicks = []
    gate = CuaSafetyGate()

    def native_click(ref):
        if ref.native_identity != "replacement":
            raise RuntimeError("identitas UIA button berubah sebelum click")
        clicks.append(ref)

    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda rect: clicks.append(rect), click_native=native_click,
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.click(
        observation.id, "uia-next", session_id="desktop-a")

    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert "executor gagal" in outcome.reason
    assert clicks == []


def test_safe_click_recapture_rejects_replaced_target_identity_after_attempt():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((
        CaptureFrame("uia:fixture", _tree(name="Before", runtime_id="original")),
        CaptureFrame("uia:fixture", _tree(name="After", runtime_id="replacement")),
    ))
    clicks = []
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda rect: clicks.append(rect),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.click(
        observation.id, "uia-next", session_id="desktop-a")

    assert error == ""
    assert outcome.executed is True
    assert outcome.verified is False
    assert len(clicks) == 1


def test_safe_click_rejects_guessed_confirm_target_before_native_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    gate = CuaSafetyGate()
    clicks = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", _tree("Delete all"))),
        click_rect=lambda _rect: clicks.append("legacy"),
        click_native=lambda ref: clicks.append(ref),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.click(
        observation.id, "uia-next", session_id="desktop-a")

    assert outcome is None
    assert "konfirmasi" in error
    assert clicks == []


def test_safe_click_rejects_target_without_runtime_identity_before_executor():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = _tree()
    tree._by_id["uia-next"].states.clear()
    gate = CuaSafetyGate()
    clicks = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)),
        click_rect=lambda rect: clicks.append(rect),
    )
    observation = authority.observe_for("desktop-a")

    outcome, error = authority.click(observation.id, "uia-next", session_id="desktop-a")

    assert outcome is None
    assert "identitas" in error
    assert clicks == []


def _context() -> ExecutionContext:
    return ExecutionContext.create(
        source="agent", actor_id="local", session_id="desktop-safe-click",
        surface="desktop", toolsets=["desktop_safe"],
    )


def test_desktop_safe_click_schema_accepts_ids_and_no_coordinate_or_button_controls():
    from jarvis.agent.tools.desktop_safe_click import DesktopSafeClick

    props = DesktopSafeClick().json_schema()["properties"]

    assert set(props) == {"observation_id", "element_id"}
    assert not {"x", "y", "button", "double", "text", "keys", "drag"} & set(props)


def test_desktop_safe_click_requires_live_observation_and_executes_service_ref():
    from jarvis.agent.tools.desktop_safe_click import DesktopSafeClick, SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter((CaptureFrame("uia:fixture", _tree()), CaptureFrame("uia:fixture", _tree("Done"))))
    gate = CuaSafetyGate()
    session = SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(gate, lambda: next(frames)),
        click_rect=lambda _rect: None,
    )
    observation = session.observe()
    tool = DesktopSafeClick(session=session)

    result = asyncio.run(tool.run(
        observation_id=observation.id, element_id="uia-next", _context=_context()))

    assert result.ok is True
    assert result.meta["executed"] is True
    assert result.meta["verified"] is True
    assert result.meta["after_observation_id"]


def test_desktop_safe_click_rejects_unknown_or_stale_id_without_click():
    from jarvis.agent.tools.desktop_safe_click import DesktopSafeClick, SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    clicks = []
    gate = CuaSafetyGate()
    session = SafeDesktopSession(
        gate=gate,
        capture=CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", _tree())),
        click_rect=lambda rect: clicks.append(rect),
    )
    tool = DesktopSafeClick(session=session)

    result = asyncio.run(tool.run(
        observation_id="unknown", element_id="uia-next", _context=_context()))

    assert result.ok is False
    assert clicks == []
    assert "observasi" in (result.error or "")


def test_desktop_safe_click_is_not_voice_schema_or_legacy_coordinate_tool():
    from jarvis.agent.tools.desktop_safe_click import DesktopSafeClick
    from jarvis.integrations import voice_native_tools

    assert DesktopSafeClick.name not in voice_native_tools.native_tool_names()
    assert DesktopSafeClick.name not in {item["name"] for item in voice_native_tools.declarations()}


def test_desktop_safe_click_has_no_type_key_drag_or_vision_api():
    from jarvis.agent.tools.desktop_safe_click import DesktopSafeClick

    assert not hasattr(DesktopSafeClick, "type")
    assert not hasattr(DesktopSafeClick, "key")
    assert not hasattr(DesktopSafeClick, "drag")
    assert not hasattr(DesktopSafeClick, "vision_analyze")
    assert DesktopSafeClick.requires_confirmation is False
    assert DesktopSafeClick.read_only is False
