"""Studio D local timeline model and bounded export contract."""
from __future__ import annotations

import csv
import io
import json


def _project():
    from jarvis.core.content_project import ContentProject, Scene
    return ContentProject("Peluncuran", "Kreator", "Cinematic", "Mulai sekarang", "Coba hari ini", (
        Scene("Pembuka", "Kota neon", "Halo dunia", "neon city skyline"),
        Scene("Isi", "Studio", "Kenalkan produk", "product on desk"),
    ))


def test_build_timeline_orders_scenes_with_local_only_fields():
    from jarvis.core.content_export import build_timeline

    rows = build_timeline(_project(), assets={1: {"state": "ready"}})
    assert rows == [
        {"order": 1, "title": "Pembuka", "narration": "Halo dunia", "visual_prompt": "neon city skyline", "duration_s": 0, "asset_state": "none"},
        {"order": 2, "title": "Isi", "narration": "Kenalkan produk", "visual_prompt": "product on desk", "duration_s": 0, "asset_state": "ready"},
    ]


def test_timeline_is_distinct_from_global_audit_timeline():
    from jarvis.core import content_export
    source = open(content_export.__file__, encoding="utf-8").read().lower()
    for forbidden in ("contexttimeline", "tools.jsonl", "audit", "session"):
        assert forbidden not in source


def test_export_markdown_storyboard_contains_only_project_content():
    from jarvis.core.content_export import export_project

    result = export_project(_project(), fmt="storyboard_md")
    assert result["ok"] is True
    text = result["content"]
    assert "# Peluncuran" in text
    assert "Pembuka" in text and "neon city skyline" in text
    assert "path" not in text.lower() and "http" not in text.lower()


def test_export_prompt_sheet_and_shot_list_and_voiceover_and_captions():
    from jarvis.core.content_export import export_project

    prompts = export_project(_project(), fmt="prompt_sheet")["content"]
    assert "neon city skyline" in prompts and "product on desk" in prompts

    shots = export_project(_project(), fmt="shot_list_csv")["content"]
    reader = list(csv.reader(io.StringIO(shots)))
    assert reader[0] == ["order", "title", "visual", "duration_s"]
    assert reader[1][1] == "Pembuka"

    voiceover = export_project(_project(), fmt="voiceover_md")["content"]
    assert "Halo dunia" in voiceover and "Kenalkan produk" in voiceover

    captions = export_project(_project(), fmt="captions_srt")["content"]
    assert "1\n" in captions and "Halo dunia" in captions and "-->" in captions


def test_export_asset_manifest_and_json_and_csv_are_project_owned():
    from jarvis.core.content_export import export_project

    manifest = export_project(_project(), fmt="asset_manifest_json", assets={0: {"state": "ready", "provider": "local", "model": "m"}})
    data = json.loads(manifest["content"])
    assert data[0] == {"scene_index": 0, "state": "ready", "provider": "local", "model": "m"}

    project_json = json.loads(export_project(_project(), fmt="project_json")["content"])
    assert project_json["title"] == "Peluncuran" and len(project_json["scenes"]) == 2

    project_csv = export_project(_project(), fmt="project_csv")["content"]
    assert "Peluncuran" not in project_csv.splitlines()[0]  # header row
    assert "Pembuka" in project_csv


def test_export_rejects_unknown_format_and_never_writes_file():
    from jarvis.core.content_export import export_project

    result = export_project(_project(), fmt="mp4_render")
    assert result == {"ok": False, "reason": "content_export_format_rejected"}


def test_export_module_has_no_render_publish_or_remote_surface():
    from jarvis.core import content_export
    source = open(content_export.__file__, encoding="utf-8").read().lower()
    for forbidden in ("ffmpeg", "moviepy", "requests", "webbrowser", "subprocess", "upload", "publish", "telegram", "s3", "boto"):
        assert forbidden not in source
