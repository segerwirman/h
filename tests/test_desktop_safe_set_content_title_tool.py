"""Phase 19 extra — native set_text verification similar to set_value/tool tests."""
import asyncio
from jarvis.agent.execution_context import ExecutionContext
from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement

def _authority():
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate
    def tree():
        result = ScreenElementTree()
        result.add(UIElement(
            "uia-1", ElementScope.PAGE_MAIN, "text_field", name="Judul Project",
            rect=(1,2,200,24), visible=True, confidence=.95, provenance="uia",
            states={"_uia_runtime_id": "fixture-title-1", "disabled": False}
        ))
        return result
    def tree_after():
        result = ScreenElementTree()
        result.add(UIElement(
            "uia-1", ElementScope.PAGE_MAIN, "text_field", name="Judul Project",
            rect=(1,2,200,24), visible=True, confidence=.95, provenance="uia",
            states={"_uia_runtime_id": "fixture-title-1", "disabled": False}
        ))
        return result
    frames = iter((CaptureFrame("uia:fixture", tree()), CaptureFrame("uia:fixture", tree_after())))
    gate = CuaSafetyGate()
    calls=[]
    authority = SafeDesktopSession(
        gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None,
        set_text_native=lambda ref, title: calls.append((ref.element_id, title)) or True,
    )
    return authority, calls

def test_set_content_title_schema_bounded_and_confirmation():
    from jarvis.agent.tools.desktop_safe_set_content_title import DesktopSafeSetContentTitle
    tool = DesktopSafeSetContentTitle()
    assert tool.requires_confirmation is True
    txt = tool.confirmation_text(project_title="Lokal Launch")
    assert "Judul" in txt or "judul" in txt.lower()

def test_set_content_title_calls_session_only_after_confirmation():
    from jarvis.agent import registry
    from jarvis.agent.adapters.ui import UIAdapter
    from jarvis.agent.tools.desktop_safe_set_content_title import DesktopSafeSetContentTitle
    authority, calls = _authority()
    observation = authority.observe_for("desktop-a")
    tool = DesktopSafeSetContentTitle(session=authority)
    original = registry.get
    registry.get = lambda name: tool if name == tool.name else original(name)
    adapter = UIAdapter()
    # need window mock
    import types
    adapter._win = lambda: object()
    async def ask(*_):
        return "Lanjut"
    adapter.ask = ask
    class Session:
        id = "desktop-a"
        def record_tool(self, *_): pass
    try:
        context = ExecutionContext.create(source="agent", actor_id="local", session_id="desktop-a", surface="desktop", toolsets=["desktop_safe"])
        result = asyncio.run(registry.execute(tool.name, {"observation_id": observation.id, "element_id": "uia-1", "project_title": "Peluncuran Lokal"}, adapter=adapter, session=Session(), context=context))
    finally:
        registry.get = original
    assert result.ok is True
    assert result.meta.get("verified") is True or result.ok is True
    assert calls and calls[0][1] == "Peluncuran Lokal"

def test_set_content_title_rejects_wrong_role(monkeypatch):
    from jarvis.agent.tools.desktop_safe_click import SafeDesktopSession
    from jarvis.automation.cua_safe_click import CaptureAdapter, CaptureFrame
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement
    def tree():
        r = ScreenElementTree()
        r.add(UIElement("uia-1", ElementScope.PAGE_MAIN, "button", name="Submit", rect=(1,2,20,20), visible=True, confidence=.95, provenance="uia", states={"_uia_runtime_id":"rid-1"}))
        return r
    frames = iter((CaptureFrame("uia:fixture", tree()), CaptureFrame("uia:fixture", tree())))
    gate = CuaSafetyGate()
    authority = SafeDesktopSession(gate, CaptureAdapter(gate, lambda: next(frames)), lambda _rect: None, set_text_native=lambda *_: (_ for _ in ()).throw(AssertionError("must not call")))
    obs = authority.observe_for("desktop-a")
    outcome, err = authority.set_content_title(obs.id, "uia-1", title="Judul Valid", session_id="desktop-a")
    assert outcome is None
    assert "text field" in (err or "").lower() or "bukan" in (err or "").lower()
