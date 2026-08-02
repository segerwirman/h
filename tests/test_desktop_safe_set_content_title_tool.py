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
        set_text_native=lambda ref, title: calls.append((ref.element_id, title)),
    )
    return authority, calls

def test_set_content_title_schema_bounded_and_confirmation():
    from jarvis.agent.tools.desktop_safe_set_content_title import DesktopSafeSetContentTitle
    tool = DesktopSafeSetContentTitle()
    assert tool.requires_confirmation is True
    txt = tool.confirmation_text(project_title="Lokal Launch")
    assert "Judul" in txt or "judul" in txt.lower()

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
