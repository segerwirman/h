"""Phase 20 RED — desktop_safe reorder semantic tool must exist, schema bounded."""

def test_reorder_tool_must_exist_schema_bounded():
    try:
        from jarvis.agent.tools.desktop_safe_reorder_scene import DesktopSafeReorderScene as Tool
    except ModuleNotFoundError:
        assert False, "jarvis.agent.tools.desktop_safe_reorder_scene must exist"
    from pydantic import BaseModel
    assert issubclass(Tool.params_schema, BaseModel)
    props = Tool.params_schema.model_json_schema().get("properties", {})
    # exact 3 props only, no coordinate/path/generic drag
    assert set(props.keys()) == {"observation_id", "source_element_id", "destination_element_id"}
    for banned in ("x", "y", "text", "keys", "path", "url", "value", "button", "double", "drag", "coordinate", "from_index", "to_index"):
        assert banned not in props, f"banned prop {banned} present"
    assert getattr(Tool, "requires_confirmation") is True
    assert "reorder" in Tool.description.lower() or "scene" in Tool.description.lower()


def test_reorder_tool_no_generic_api():
    from jarvis.agent.tools.desktop_safe_reorder_scene import DesktopSafeReorderScene
    for banned in ("drag", "click_at", "type", "key", "coordinate"):
        assert not hasattr(DesktopSafeReorderScene, banned)


def test_reorder_tool_rejects_remote_voice_cron():
    src = open(r"E:\jarvis agent\h\jarvis\agent\tools\desktop_safe_reorder_scene.py", encoding="utf-8").read()
    assert "desktop_safe_context_error" in src
    assert "content_studio_scene_reorder" in src


def test_reorder_tool_has_explicit_descriptor_and_desktop_only_schema():
    from jarvis.agent import registry
    from jarvis.agent.capabilities import REGISTRY
    from jarvis.agent.execution_context import ExecutionContext
    from jarvis.agent.tools.desktop_safe_reorder_scene import DesktopSafeReorderScene

    descriptor = REGISTRY.descriptor_for_tool(DesktopSafeReorderScene.name)
    assert descriptor is not None
    assert descriptor.toolset == "desktop_safe"

    for surface, source, allowed in (
        ("desktop", "agent", True),
        ("remote", "telegram", False),
        ("voice", "gemini_live", False),
        ("desktop", "cron", False),
        ("desktop", "delegation", False),
    ):
        ctx = ExecutionContext.create(
            source=source, actor_id="local", session_id="s",
            surface=surface, toolsets=["desktop_safe"],
        )
        names = {item["function"]["name"] for item in registry.schemas(context=ctx)}
        assert (DesktopSafeReorderScene.name in names) is allowed
