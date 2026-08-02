def test_tool_is_desktop_safe_capability_and_not_voice():
    from jarvis.agent.capabilities import REGISTRY
    from jarvis.agent.tools.desktop_safe_set_content_title import DesktopSafeSetContentTitle
    from jarvis.integrations import voice_native_tools
    descriptor = REGISTRY.descriptor_for_tool(DesktopSafeSetContentTitle.name)
    assert descriptor is not None
    assert descriptor.toolset == "desktop_safe"
    assert DesktopSafeSetContentTitle.name not in {item["name"] for item in voice_native_tools.declarations()}

def test_schema_exposure_is_desktop_local_only():
    from jarvis.agent import registry
    from jarvis.agent.execution_context import ExecutionContext
    target = "desktop_safe_set_content_title"
    for surface, source, allowed in (
        ("desktop", "agent", True),
        ("remote", "telegram", False),
        ("voice", "gemini_live", False),
        ("desktop", "cron", False),
        ("desktop", "delegation", False),
    ):
        ctx = ExecutionContext.create(source=source, actor_id="local", session_id="s", surface=surface, toolsets=["desktop_safe"])
        names = {item["function"]["name"] for item in registry.schemas(context=ctx)}
        assert (target in names) is allowed, f"exposure mismatch {surface}/{source} expect {allowed}"
