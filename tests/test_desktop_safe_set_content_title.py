"""Phase 19 GREEN — desktop_safe_set_content_title intent-specific Judul Project only."""
from __future__ import annotations
import asyncio, pathlib

TOOL = "desktop_safe_set_content_title"
EXPECTED_PROPS = {"observation_id", "element_id", "project_title"}

def _tool_path():
    return pathlib.Path("E:/jarvis agent/h/jarvis/agent/tools/desktop_safe_set_content_title.py")

def test_schema_is_intent_specific_bounded():
    from jarvis.agent.tools.desktop_safe_set_content_title import DesktopSafeSetContentTitle
    props = DesktopSafeSetContentTitle().json_schema()["properties"]
    assert set(props.keys()) == EXPECTED_PROPS, f"got {set(props.keys())}"
    for banned in ("x", "y", "text", "keys", "path", "url", "value", "button", "double", "drag", "coordinate"):
        assert banned not in props, f"banned prop {banned}"
    assert DesktopSafeSetContentTitle.requires_confirmation is True
    desc = DesktopSafeSetContentTitle.description.lower()
    assert "judul" in desc and "project" in desc

def test_has_no_type_key_drag_coordinate_api():
    from jarvis.agent.tools.desktop_safe_set_content_title import DesktopSafeSetContentTitle
    assert not hasattr(DesktopSafeSetContentTitle, "type")
    assert not hasattr(DesktopSafeSetContentTitle, "key")
    assert not hasattr(DesktopSafeSetContentTitle, "drag")
    assert not hasattr(DesktopSafeSetContentTitle, "click_at")
    assert not hasattr(DesktopSafeSetContentTitle, "vision_analyze")

def test_registry_rejects_remote_before_confirmation(monkeypatch):
    from jarvis.agent import registry
    tool = registry.get("desktop_safe_set_content_title")
    monkeypatch.setattr(tool, "run", lambda **_: (_ for _ in ()).throw(AssertionError("must not run")))
    from jarvis.agent.execution_context import ExecutionContext
    ctx = ExecutionContext.create(source="telegram", actor_id="remote", session_id="remote-a", surface="remote", toolsets=["desktop_safe"])
    result = asyncio.run(registry.execute(TOOL, {"observation_id":"obs","element_id":"uia-1","project_title":"Judul"}, context=ctx))
    assert result.ok is False
    assert "policy menolak" in (result.error or "")

def test_tool_source_has_no_generic_dispatch():
    p = _tool_path()
    src = p.read_text(encoding="utf-8").lower()
    assert "webbrowser" not in src
    assert "subprocess" not in src
    assert "pyautogui" not in src
    assert "requests" not in src
    assert "open_url" not in src
    assert "click_at" not in src

def test_tool_uses_content_title_policy():
    p = _tool_path()
    src = p.read_text(encoding="utf-8").lower()
    assert "content_title_policy" in src or "admit_title" in src

def test_policy_integration_rejects_url_password():
    import asyncio
    from jarvis.agent.tools.desktop_safe_set_content_title import DesktopSafeSetContentTitle
    from jarvis.agent.execution_context import ExecutionContext
    class Sess:
        id = "desktop-test"
    ctx = ExecutionContext.create(source="agent", actor_id="local", session_id="desktop-test", surface="desktop", toolsets=["desktop_safe"])
    async def run_bad(title):
        tool = DesktopSafeSetContentTitle()
        res = await tool.run(observation_id="obs", element_id="uia-1", project_title=title, _session=Sess(), _context=ctx, _desktop_safe_confirmation=True)
        return res
    for bad in ["https://evil.com", "password 123", "x"*200]:
        r = asyncio.run(run_bad(bad))
        assert r.ok is False, f"should reject {bad}"
