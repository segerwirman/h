"""Desktop-safe capability stays desktop-local, session-bound, and ephemeral."""
from __future__ import annotations

import asyncio

from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


def _context(*, surface="desktop", source="ui", toolsets=("desktop_safe",)):
    return ExecutionContext.create(
        source=source, actor_id="local-user", session_id="desktop-a",
        surface=surface, toolsets=toolsets,
    )


def test_desktop_safe_has_explicit_capability_descriptors_not_generic_local():
    from jarvis.agent.capabilities import REGISTRY

    by_tool = {item.tool_name: item for item in REGISTRY.descriptors()}

    assert by_tool["desktop_observe"].toolset == "desktop_safe"
    assert by_tool["desktop_safe_click"].toolset == "desktop_safe"
    assert by_tool["desktop_safe_scroll"].toolset == "desktop_safe"
    assert by_tool["desktop_observe"].id == "desktop_safe.desktop_observe"


def test_desktop_safe_policy_allows_only_desktop_local_context():
    from jarvis.agent import policy

    for surface, source, toolsets, allowed in (
        ("desktop", "ui", ("desktop_safe",), True),
        ("desktop", "agent", ("desktop_safe",), True),
        ("voice", "gemini_live", ("desktop_safe",), False),
        ("remote", "telegram", ("desktop_safe",), False),
        ("desktop", "cron", ("desktop_safe",), False),
        ("desktop", "delegation", ("desktop_safe",), False),
        ("desktop", "ui", ("local",), False),
    ):
        decision = policy.decide(
            _context(surface=surface, source=source, toolsets=toolsets),
            capability="desktop_safe.desktop_observe", risk="medium",
        )
        assert decision.allowed is allowed


def test_registry_hides_desktop_safe_schema_without_execution_context():
    from jarvis.agent import registry

    names = {item["function"]["name"] for item in registry.schemas()}

    assert not {"desktop_observe", "desktop_safe_click", "desktop_safe_scroll",
                "desktop_safe_set_value"} & names


def test_registry_passes_context_session_identity_to_desktop_safe_tool(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.base import ToolResult

    tool = registry.get("desktop_observe")
    captured = {}

    async def run(**kwargs):
        captured["context"] = kwargs["_context"]
        captured["runtime_session"] = kwargs["_session"]
        return ToolResult.success("ok")

    monkeypatch.setattr(tool, "run", run)
    runtime_session = type("Session", (), {"id": "runtime-a"})()
    context = ExecutionContext.create(
        source="agent", actor_id="local-user", session_id="context-b", surface="desktop",
        toolsets=["desktop_safe"],
    )

    result = asyncio.run(registry.execute(
        "desktop_observe", {}, session=runtime_session, context=context,
    ))

    assert result.ok is True
    assert captured["context"] is context
    assert captured["runtime_session"] is runtime_session


def test_desktop_safe_tool_rejects_context_session_mismatch_before_authority_use():
    from jarvis.agent.tools.desktop_observe import DesktopObserve
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fixture", tree)), lambda _rect: None,
    )
    context = ExecutionContext.create(
        source="agent", actor_id="local-user", session_id="context-b", surface="desktop",
        toolsets=["desktop_safe"],
    )
    result = asyncio.run(DesktopObserve(session=authority).run(
        _session=type("Session", (), {"id": "runtime-a"})(), _context=context,
    ))

    assert result.ok is False
    assert "session" in (result.error or "").lower()


def test_registry_schema_matrix_exposes_every_desktop_safe_tool_only_local_desktop():
    from jarvis.agent import registry

    expected = {"desktop_observe", "desktop_safe_click", "desktop_safe_scroll",
                "desktop_safe_set_value"}
    cases = (
        (None, set()),
        (_context(surface="desktop", source="ui"), expected),
        (_context(surface="desktop", source="agent"), expected),
        (_context(surface="voice", source="gemini_live"), set()),
        (_context(surface="remote", source="telegram"), set()),
        (_context(surface="desktop", source="cron"), set()),
        (_context(surface="desktop", source="delegation"), set()),
        (_context(surface="desktop", source="ui", toolsets=("local",)), set()),
    )
    for context, expected_names in cases:
        names = {item["function"]["name"] for item in registry.schemas(context=context)}
        assert names & expected == expected_names


def test_registry_denies_remote_desktop_safe_before_tool_runs(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.base import ToolResult

    tool = registry.get("desktop_observe")
    monkeypatch.setattr(tool, "run", lambda **_: (_ for _ in ()).throw(AssertionError("must not run")))

    result = asyncio.run(registry.execute(
        "desktop_observe", {}, context=_context(surface="remote", source="telegram")))

    assert result.ok is False
    assert "policy menolak" in (result.error or "")


def test_safe_session_cleanup_revokes_all_observations_owned_by_session():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    tree = ScreenElementTree()
    tree.add(UIElement("uia-next", ElementScope.PAGE_MAIN, "button", name="Next",
                       rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia"))
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(gate, CaptureAdapter(gate, lambda: CaptureFrame("uia:fix", tree)), lambda _r: None)
    observation = authority.observe_for("desktop-a")

    authority.clear_session("desktop-a")
    outcome, error = authority.click(observation.id, "uia-next", session_id="desktop-a")

    assert outcome is None
    assert "observasi" in error


def test_registry_desktop_local_observe_then_click_acceptance(monkeypatch):
    from jarvis.agent import registry
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.agent.tools import desktop_observe, desktop_safe_click
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate

    def tree(label):
        result = ScreenElementTree()
        result.add(UIElement("uia-next", ElementScope.PAGE_MAIN, "button", name=label,
                             rect=(1, 2, 30, 20), visible=True, confidence=.95, provenance="uia",
                             states={"_uia_runtime_id": "fixture-next"}))
        return result
    frames = iter((CaptureFrame("uia:fix", tree("Next")), CaptureFrame("uia:fix", tree("Done"))))
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(gate, CaptureAdapter(gate, lambda: next(frames)), lambda _r: None)
    monkeypatch.setattr(desktop_observe, "desktop_safe_session", lambda: authority)
    monkeypatch.setattr(desktop_safe_click, "desktop_safe_session", lambda: authority)

    class Session:
        id = "desktop-a"
        def record_tool(self, *_): pass

    context = _context()
    observed = asyncio.run(registry.execute("desktop_observe", {}, session=Session(), context=context))
    clicked = asyncio.run(registry.execute("desktop_safe_click", {
        "observation_id": observed.content["observation_id"],
        "element_id": observed.content["elements"][0]["element_id"],
    }, session=Session(), context=context))

    assert observed.ok is True
    assert clicked.ok is True
    assert clicked.meta["verified"] is True


def test_scope_mapping_keeps_unsupported_uia_as_page_main():
    from jarvis.automation.uia_capture import _scope_for

    control = type("C", (), {"element_info": type("I", (), {"is_dialog": False})()})()
    assert _scope_for(control, 30, 90) is ElementScope.PAGE_MAIN


def test_dispatch_cleanup_revokes_desktop_safe_observations(monkeypatch):
    from jarvis.agent import dispatch

    cleared = []

    class Authority:
        def clear_session(self, session_id):
            cleared.append(session_id)

    monkeypatch.setattr(
        "jarvis.agent.tools.desktop_safe_click.desktop_safe_session",
        lambda: Authority(),
    )

    dispatch._clear_desktop_safe_session("terminal-session")

    assert cleared == ["terminal-session"]


def test_lifecycle_bridge_is_editable_and_does_not_modify_frozen_legacy_ui():
    from pathlib import Path

    bridge = Path("jarvis/integrations/desktop_safe_lifecycle.py").read_text(encoding="utf-8")
    frozen = Path("ui.py").read_text(encoding="utf-8")

    assert "closeEvent" in bridge
    assert "clear_all" in bridge
    assert "DESKTOP_SAFE_TEARDOWN_HOOK" not in frozen


def test_lifecycle_bridge_clears_all_refs_when_ui_closes(monkeypatch):
    from jarvis.integrations import desktop_safe_lifecycle

    cleared = []
    authority = type("Authority", (), {"clear_all": lambda self: cleared.append(True)})()
    monkeypatch.setattr(desktop_safe_lifecycle, "desktop_safe_session", lambda: authority)

    class Window:
        def closeEvent(self, event):
            return "legacy-close"

    desktop_safe_lifecycle.install(Window)

    assert Window().closeEvent(object()) == "legacy-close"
    assert cleared == [True]
