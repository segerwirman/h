"""Studio D: desktop-local creative timeline and bounded project export.

Produces only project-owned text artifacts. Callers receive strings; this module
never renders media, writes files, or sends data anywhere.
"""
from __future__ import annotations

import csv
import io
import json

from jarvis.core.content_project import ContentProject
from jarvis.core.content_timing_policy import (
    admit_durations,
    build_srt,
    default_durations,
)

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


def _storyboard_md(project: ContentProject,
                   durations: list[int] | None = None) -> str:
    lines = [f"# {project.title}", "", f"- Audiens: {project.audience}", f"- Tone: {project.tone}",
             f"- Hook: {project.hook}", f"- CTA: {project.cta}", ""]
    durations = durations or default_durations(len(project.scenes))
    for index, (scene, _duration) in enumerate(
            zip(project.scenes, durations), start=1):
        lines += [f"## Scene {index}: {scene.title}", "",
                  f"- Visual: {scene.visual}", f"- Narasi: {scene.narration}",
                  f"- Visual prompt: {scene.visual_prompt}", ""]
    return "\n".join(lines).rstrip() + "\n"


def _prompt_sheet(project: ContentProject) -> str:
    return "\n".join(f"{i}. {s.visual_prompt}" for i, s in enumerate(project.scenes, start=1)) + "\n"


def _shot_list_csv(project: ContentProject,
                   durations: list[int] | None = None) -> str:
    buffer = io.StringIO()
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerow(["order", "title", "visual", "duration_s"])
    durations = durations or default_durations(len(project.scenes))
    for index, (scene, duration) in enumerate(
            zip(project.scenes, durations), start=1):
        writer.writerow([index, scene.title, scene.visual, duration])
    return buffer.getvalue()


def _voiceover_md(project: ContentProject) -> str:
    lines = [f"# Voiceover — {project.title}", ""]
    for index, scene in enumerate(project.scenes, start=1):
        lines += [f"## Scene {index}: {scene.title}", "", scene.narration, ""]
    return "\n".join(lines).rstrip() + "\n"


def _captions_srt(project: ContentProject,
                  durations: list[int] | None = None) -> str:
    durations = durations or default_durations(len(project.scenes))
    result = build_srt(
        durations, [scene.narration for scene in project.scenes])
    return result.get("content", "")


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


def export_project(project: ContentProject, *, fmt: str,
                   assets: dict | None = None,
                   durations: object = None) -> dict:
    """Return only a project-owned string artifact; reject unknown/unsafe formats."""
    if fmt not in _FORMATS:
        return {"ok": False, "reason": "content_export_format_rejected"}
    assets = assets or {}
    if durations is None:
        durations = default_durations(len(project.scenes))
    else:
        admitted = admit_durations(durations)
        if not admitted.get("ok"):
            return {"ok": False,
                    "reason": admitted.get("reason", "content_durations_rejected")}
        durations = admitted["durations"]
    if fmt == "storyboard_md":
        content = _storyboard_md(project, durations)
    elif fmt == "prompt_sheet":
        content = _prompt_sheet(project)
    elif fmt == "shot_list_csv":
        content = _shot_list_csv(project, durations)
    elif fmt == "voiceover_md":
        content = _voiceover_md(project)
    elif fmt == "captions_srt":
        content = _captions_srt(project, durations)
    elif fmt == "asset_manifest_json":
        content = _asset_manifest_json(project, assets)
    elif fmt == "project_json":
        content = _project_json(project)
    else:
        content = _project_csv(project)
    return {"ok": True, "fmt": fmt, "content": content}


def preview_export(project: ContentProject, *, fmt: str,
                   durations: object = None) -> dict:
    """Local in-memory preview with timing; never writes any file.

    Supported preview formats: storyboard_md (with timing lines),
    captions_srt (cumulative timing), shot_list_csv (validated durations).
    """
    if fmt not in {"storyboard_md", "captions_srt", "shot_list_csv"}:
        return {"ok": False, "reason": "content_preview_format_rejected"}
    if durations is None:
        durations = default_durations(len(project.scenes))
    else:
        admitted = admit_durations(durations)
        if not admitted.get("ok"):
            return {"ok": False,
                    "reason": admitted.get("reason", "content_durations_rejected")}
        durations = admitted["durations"]
    if fmt == "captions_srt":
        result = build_srt(
            durations, [scene.narration for scene in project.scenes])
        if not result.get("ok"):
            return result
        content = result["content"]
    elif fmt == "shot_list_csv":
        content = _shot_list_csv(project, durations)
    else:
        from jarvis.core.content_timing_policy import cumulative_timings, srt_timestamp
        lines = [f"# {project.title}", "",
                 f"- Audiens: {project.audience}", f"- Tone: {project.tone}",
                 f"- Hook: {project.hook}", f"- CTA: {project.cta}", ""]
        for index, (scene, (start, end)) in enumerate(
                zip(project.scenes, cumulative_timings(durations)), start=1):
            lines += [f"## Scene {index}: {scene.title}",
                      f"- Timing: {srt_timestamp(start)} → {srt_timestamp(end)}"
                      f" ({durations[index - 1]}s)",
                      f"- Visual: {scene.visual}",
                      f"- Narasi: {scene.narration}", ""]
        content = "\n".join(lines).rstrip() + "\n"
    return {"ok": True, "fmt": fmt, "content": content}


__all__ = ["build_timeline", "export_project", "preview_export"]
