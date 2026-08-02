"""Studio D: desktop-local creative timeline and bounded project export.

Produces only project-owned text artifacts. Callers receive strings; this module
never renders media, writes files, or sends data anywhere.
"""
from __future__ import annotations

import csv
import io
import json

from jarvis.core.content_project import ContentProject

_FORMATS = {
    "storyboard_md",
    "prompt_sheet",
    "shot_list_csv",
    "voiceover_md",
    "captions_srt",
    "asset_manifest_json",
    "project_json",
    "project_csv",
}


def build_timeline(project: ContentProject, *, assets: dict | None = None) -> list[dict]:
    """Ordered scene rows with local-only creative fields; independent of any global timeline."""
    assets = assets or {}
    rows = []
    for index, scene in enumerate(project.scenes):
        entry = assets.get(index) or {}
        rows.append({
            "order": index + 1,
            "title": scene.title,
            "narration": scene.narration,
            "visual_prompt": scene.visual_prompt,
            "duration_s": int(entry.get("duration_s", 0)),
            "asset_state": str(entry.get("state", "none")),
        })
    return rows


def _storyboard_md(project: ContentProject) -> str:
    lines = [f"# {project.title}", "", f"- Audiens: {project.audience}", f"- Tone: {project.tone}",
             f"- Hook: {project.hook}", f"- CTA: {project.cta}", ""]
    for index, scene in enumerate(project.scenes, start=1):
        lines += [f"## Scene {index}: {scene.title}", "",
                  f"- Visual: {scene.visual}", f"- Narasi: {scene.narration}",
                  f"- Visual prompt: {scene.visual_prompt}", ""]
    return "\n".join(lines).rstrip() + "\n"


def _prompt_sheet(project: ContentProject) -> str:
    return "\n".join(f"{i}. {s.visual_prompt}" for i, s in enumerate(project.scenes, start=1)) + "\n"


def _shot_list_csv(project: ContentProject) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["order", "title", "visual", "duration_s"])
    for index, scene in enumerate(project.scenes, start=1):
        writer.writerow([index, scene.title, scene.visual, 0])
    return buffer.getvalue()


def _voiceover_md(project: ContentProject) -> str:
    lines = [f"# Voiceover — {project.title}", ""]
    for index, scene in enumerate(project.scenes, start=1):
        lines += [f"## Scene {index}: {scene.title}", "", scene.narration, ""]
    return "\n".join(lines).rstrip() + "\n"


def _srt_stamp(seconds: int) -> str:
    return f"00:00:{seconds:02d},000"


def _captions_srt(project: ContentProject) -> str:
    blocks = []
    for index, scene in enumerate(project.scenes, start=1):
        start = _srt_stamp((index - 1) * 5)
        end = _srt_stamp(index * 5)
        blocks.append(f"{index}\n{start} --> {end}\n{scene.narration}\n")
    return "\n".join(blocks)


def _asset_manifest_json(project: ContentProject, assets: dict) -> str:
    manifest = []
    for index in range(len(project.scenes)):
        entry = assets.get(index) or {}
        manifest.append({
            "scene_index": index,
            "state": str(entry.get("state", "none")),
            "provider": str(entry.get("provider", "")),
            "model": str(entry.get("model", "")),
        })
    return json.dumps(manifest, ensure_ascii=False, indent=2)


def _project_json(project: ContentProject) -> str:
    return json.dumps(project.public_dict(), ensure_ascii=False, indent=2)


def _project_csv(project: ContentProject) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["order", "title", "visual", "narration", "visual_prompt"])
    for index, scene in enumerate(project.scenes, start=1):
        writer.writerow([index, scene.title, scene.visual, scene.narration, scene.visual_prompt])
    return buffer.getvalue()


def export_project(project: ContentProject, *, fmt: str, assets: dict | None = None) -> dict:
    """Return only a project-owned string artifact; reject unknown/unsafe formats."""
    if fmt not in _FORMATS:
        return {"ok": False, "reason": "content_export_format_rejected"}
    assets = assets or {}
    if fmt == "storyboard_md":
        content = _storyboard_md(project)
    elif fmt == "prompt_sheet":
        content = _prompt_sheet(project)
    elif fmt == "shot_list_csv":
        content = _shot_list_csv(project)
    elif fmt == "voiceover_md":
        content = _voiceover_md(project)
    elif fmt == "captions_srt":
        content = _captions_srt(project)
    elif fmt == "asset_manifest_json":
        content = _asset_manifest_json(project, assets)
    elif fmt == "project_json":
        content = _project_json(project)
    else:
        content = _project_csv(project)
    return {"ok": True, "fmt": fmt, "content": content}


__all__ = ["build_timeline", "export_project"]
