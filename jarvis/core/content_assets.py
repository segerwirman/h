"""Studio B selected-scene local asset metadata boundary."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from jarvis.core.content_project import ContentProject


def generate_selected_scene(
    project: ContentProject,
    scene_index: int,
    *,
    configured: bool,
    provider: str = "",
    model: str = "",
    generate: Callable[[str], Path] | None = None,
) -> dict:
    """Generate exactly one selected scene; public result intentionally has no file location."""
    if not configured or generate is None:
        return {"ok": False, "reason": "content_image_provider_unavailable"}
    if not isinstance(scene_index, int) or isinstance(scene_index, bool) or not 0 <= scene_index < len(project.scenes):
        return {"ok": False, "reason": "content_scene_selection_required"}
    scene = project.scenes[scene_index]
    try:
        artifact = generate(scene.visual_prompt)
    except Exception:
        return {"ok": False, "reason": "content_image_generation_failed"}
    if not isinstance(artifact, Path):
        return {"ok": False, "reason": "content_image_generation_failed"}
    return {
        "ok": True,
        "asset": {
            "scene_index": scene_index,
            "provider": str(provider)[:80],
            "model": str(model)[:120],
            "state": "ready",
        },
    }


def _active_image_tool():
    """Return only configured provider/model labels plus the existing image tool."""
    from jarvis.agent.tools import image_gen
    from jarvis.core import config

    if not image_gen.available():
        return None
    provider = str(config.get("image_generation.provider", "") or "configured").strip()
    model = str(config.get("image_generation.model", "") or "active").strip()
    return provider[:80], model[:120], image_gen.ImageGenerate()


async def generate_selected_scene_with_active_provider(project: ContentProject, scene_index: int) -> dict:
    """Invoke the configured existing image lane for one scene and return metadata only."""
    if not isinstance(scene_index, int) or isinstance(scene_index, bool) or not 0 <= scene_index < len(project.scenes):
        return {"ok": False, "reason": "content_scene_selection_required"}
    active = _active_image_tool()
    if active is None:
        return {"ok": False, "reason": "content_image_provider_unavailable"}
    provider, model, tool = active
    try:
        result = await tool.run(prompt=project.scenes[scene_index].visual_prompt, n=1)
    except Exception:
        return {"ok": False, "reason": "content_image_generation_failed"}
    paths = getattr(result, "meta", {}).get("paths", []) if getattr(result, "ok", False) else []
    if not isinstance(paths, list) or len(paths) != 1:
        return {"ok": False, "reason": "content_image_generation_failed"}
    return {"ok": True, "asset": {"scene_index": scene_index, "provider": provider, "model": model, "state": "ready"}}


__all__ = ["generate_selected_scene", "generate_selected_scene_with_active_provider"]
