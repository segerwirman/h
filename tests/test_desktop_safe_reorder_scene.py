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
