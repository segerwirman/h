"""Native desktop_safe_set_value requires confirmation and stays local-only."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _authority():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    def tree(value):
        result = ScreenElementTree()
        result.add(UIElement(
            "uia-slider", ElementScope.PAGE_MAIN, "slider", name="JARVIS fixture slider",
            rect=(1, 2, 100, 20), visible=True, confidence=.95, provenance="uia",
            states={"value": value, "minimum": 0.0, "maximum": 100.0,
                    "_uia_runtime_id": "fixture-slider"},
        ))
        return result
    frames = iter((CaptureFrame("uia:fixture", tree(25.0)), CaptureFrame("uia:fixture", tree(30.0))))
    gate = CuaSafetyGate()
    calls = []
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        set_value_native=lambda ref, value: calls.append((ref, value)),
    )
    return authority, calls


def test_set_value_schema_has_only_semantic_ids_and_numeric_value():
    from jarvis.agent.tools.desktop_safe_set_value import DesktopSafeSetValue

    props = DesktopSafeSetValue().json_schema()["properties"]

    assert set(props) == {"observation_id", "element_id", "value"}
    assert props["value"]["type"] == "number"
    assert not {"x", "y", "text", "keys", "button", "double", "drag"} & set(props)


def test_set_value_always_requires_explicit_confirmation():
    from jarvis.agent.tools.desktop_safe_set_value import DesktopSafeSetValue

    tool = DesktopSafeSetValue()
    assert tool.requires_confirmation is True
    assert tool.needs_confirmation(observation_id="a", element_id="b", value=30) is True
    assert "slider" in tool.confirmation_text(observation_id="a", element_id="b", value=30).lower()


def test_set_value_tool_calls_internal_session_only_after_registry_confirmation(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.adapters.ui import UIAdapter
    from jarvis.agent.tools.desktop_safe_set_value import DesktopSafeSetValue

    authority, calls = _authority()
    observation = authority.observe_for("desktop-a")
    tool = DesktopSafeSetValue(session=authority)
    original = registry.get
    registry.get = lambda name: tool if name == tool.name else original(name)

    adapter = UIAdapter()
    monkeypatch.setattr(adapter, "_win", lambda: object())

    async def ask(*_):
        return "Lanjut"

    monkeypatch.setattr(adapter, "ask", ask)

    class Session:
        id = "desktop-a"
        def record_tool(self, *_): pass
    try:
        context = ExecutionContext.create(
            source="agent", actor_id="local", session_id="desktop-a", surface="desktop",
            toolsets=["desktop_safe"],
        )
        result = asyncio.run(registry.execute(tool.name, {
            "observation_id": observation.id, "element_id": "uia-slider", "value": 30,
        }, adapter=adapter, session=Session(), context=context))
    finally:
        registry.get = original

    assert result.ok is True
    assert result.meta["verified"] is True
    assert [(ref.rect, value) for ref, value in calls] == [((1, 2, 100, 20), 30.0)]


def test_set_value_tool_is_desktop_safe_capability_and_not_voice_schema():
    from jarvis.agent.capabilities import REGISTRY
    from jarvis.agent.tools.desktop_safe_set_value import DesktopSafeSetValue
    from jarvis.integrations import voice_native_tools

    descriptor = REGISTRY.descriptor_for_tool(DesktopSafeSetValue.name)
    assert descriptor.toolset == "desktop_safe"
    assert DesktopSafeSetValue.name not in {item["name"] for item in voice_native_tools.declarations()}


def test_set_value_schema_is_exposed_only_desktop_local():
    from jarvis.agent import registry

    target = "desktop_safe_set_value"
    for surface, source, allowed in (
        ("desktop", "agent", True), ("remote", "telegram", False),
        ("voice", "gemini_live", False), ("desktop", "cron", False),
        ("desktop", "delegation", False),
    ):
        context = ExecutionContext.create(
            source=source, actor_id="local", session_id="s", surface=surface,
            toolsets=["desktop_safe"],
        )
        names = {item["function"]["name"] for item in registry.schemas(context=context)}
        assert (target in names) is allowed


def test_set_value_registry_rejects_remote_before_confirmation_or_executor(monkeypatch):
    from jarvis.agent import registry

    tool = registry.get("desktop_safe_set_value")
    monkeypatch.setattr(
        tool, "run", lambda **_: (_ for _ in ()).throw(AssertionError("must not run")),
    )
    context = ExecutionContext.create(
        source="telegram", actor_id="remote", session_id="remote-a", surface="remote",
        toolsets=["desktop_safe"],
    )

    result = asyncio.run(registry.execute(
        "desktop_safe_set_value",
        {"observation_id": "obs", "element_id": "uia-slider", "value": 30},
        context=context,
    ))

    assert result.ok is False
    assert "policy menolak" in (result.error or "")


def test_set_value_registry_rejects_missing_context_before_confirmation_or_executor(monkeypatch):
    from jarvis.agent import registry

    tool = registry.get("desktop_safe_set_value")
    monkeypatch.setattr(
        tool, "run", lambda **_: (_ for _ in ()).throw(AssertionError("must not run")),
    )

    class Adapter:
        async def ask(self, *_):
            raise AssertionError("must not ask")

    result = asyncio.run(registry.execute(
        "desktop_safe_set_value",
        {"observation_id": "obs", "element_id": "uia-slider", "value": 30},
        adapter=Adapter(),
    ))

    assert result.ok is False
    assert "execution context" in (result.error or "")


def test_set_value_direct_run_rejects_missing_context_and_confirmation_permit():
    from jarvis.agent.tools.desktop_safe_set_value import DesktopSafeSetValue

    authority, calls = _authority()
    observation = authority.observe_for("desktop-a")
    result = asyncio.run(DesktopSafeSetValue(session=authority).run(
        observation.id, "uia-slider", 30.0,
        _session=type("Session", (), {"id": "desktop-a"})(),
    ))

    assert result.ok is False
    assert "execution_context" in (result.error or "")
    assert calls == []


def test_set_value_rejects_non_finite_value_before_native_executor():
    from jarvis.agent.tools.desktop_safe_set_value import DesktopSafeSetValue

    authority, calls = _authority()
    observation = authority.observe_for("desktop-a")
    context = ExecutionContext.create(
        source="agent", actor_id="local", session_id="desktop-a", surface="desktop",
        toolsets=["desktop_safe"],
    )
    result = asyncio.run(DesktopSafeSetValue(session=authority).run(
        observation.id, "uia-slider", float("inf"),
        _session=type("Session", (), {"id": "desktop-a"})(), _context=context,
        _desktop_safe_confirmation=True,
    ))

    assert result.ok is False
    assert "finite" in (result.error or "")
    assert calls == []


def test_set_value_has_no_type_key_drag_or_coordinate_api():
    from jarvis.agent.tools.desktop_safe_set_value import DesktopSafeSetValue

    assert not hasattr(DesktopSafeSetValue, "type")
    assert not hasattr(DesktopSafeSetValue, "key")
    assert not hasattr(DesktopSafeSetValue, "drag")
    assert not hasattr(DesktopSafeSetValue, "click_at")
    assert not hasattr(DesktopSafeSetValue, "vision_analyze")
