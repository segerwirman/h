"""Studio local unmounted project and scene planning sheet."""
from __future__ import annotations
import asyncio
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PyQt6.QtWidgets import QApplication
_APP = None

def _app():
    global _APP
    _APP = QApplication.instance() or QApplication([])
    return _APP

def test_content_studio_tool_reads_local_brief_without_returning_source_path(tmp_path):
    from jarvis.agent.tools.content_studio import ContentStudioPrompt

    prompt = tmp_path / "brief.txt"
    prompt.write_text("Rencanakan kampanye lokal.", encoding="utf-8")
    result = asyncio.run(ContentStudioPrompt().run(path=str(prompt)))
    assert result.ok is True
    assert result.content == {"kind": "text", "text": "Rencanakan kampanye lokal."}
    assert str(prompt) not in result.for_llm()
    assert ContentStudioPrompt.read_only is True
    assert ContentStudioPrompt.requires_confirmation is True

def test_content_studio_tool_fails_with_safe_reason_only(tmp_path):
    from jarvis.agent.tools.content_studio import ContentStudioPrompt

    result = asyncio.run(ContentStudioPrompt().run(path=str(tmp_path / "script.py")))
    assert result.ok is False
    assert result.error == "content_prompt_type_rejected"
    assert str(tmp_path) not in result.for_llm()

def test_content_studio_sheet_is_hidden_and_keeps_brief_brainstorm_timeline_local():
    _app()
    from jarvis.ui.content_studio import ContentStudioSheet

    sheet = ContentStudioSheet()
    assert sheet.isVisible() is False
    assert sheet.section_names() == ("Brief", "Brainstorm", "Timeline")
    sheet.set_project_fields(title="Peluncuran", audience="Kreator", tone="Cinematic", hook="Mulai", cta="Coba")
    sheet.add_scene(title="Pembuka", visual="Kota", narration="Halo", visual_prompt="neon city")
    project = sheet.project()
    assert project.title == "Peluncuran"
    assert project.scenes[0].title == "Pembuka"
    source = open(sheet.__class__.__module__.replace(".", "/") + ".py", encoding="utf-8").read()
    for forbidden in ("webbrowser", "subprocess", "upload", "image_generate", "telegram", "requests"):
        assert forbidden not in source.lower()

def test_content_studio_sheet_generates_only_explicitly_selected_scene(monkeypatch):
    import asyncio
    _app()
    from jarvis.core import content_assets
    from jarvis.ui.content_studio import ContentStudioSheet

    sheet = ContentStudioSheet()
    sheet.add_scene(title="Satu", visual="V1", narration="N1", visual_prompt="prompt satu")
    sheet.add_scene(title="Dua", visual="V2", narration="N2", visual_prompt="prompt dua")
    monkeypatch.setattr(content_assets, "generate_selected_scene_with_active_provider", lambda project, index: _async_result(index))
    assert asyncio.run(sheet.generate_selected_scene()) == {"ok": False, "reason": "content_scene_selection_required"}
    assert sheet.select_scene(1) is True
    assert asyncio.run(sheet.generate_selected_scene()) == {"ok": True, "asset": {"scene_index": 1, "provider": "fake", "model": "test", "state": "ready"}}
    assert sheet.asset_metadata() == {"scene_index": 1, "provider": "fake", "model": "test", "state": "ready"}

async def _async_result(index):
    return {"ok": True, "asset": {"scene_index": index, "provider": "fake", "model": "test", "state": "ready"}}

def test_content_studio_sheet_rejects_invalid_scene_without_external_action():
    _app()
    from jarvis.ui.content_studio import ContentStudioSheet

    sheet = ContentStudioSheet()
    assert sheet.add_scene(title="", visual="", narration="", visual_prompt="") is False
    assert sheet.project().scenes == ()
    assert sheet.status_text() == "Scene belum lengkap."

def test_content_studio_sheet_exposes_local_timeline_and_bounded_export():
    _app()
    from jarvis.ui.content_studio import ContentStudioSheet

    sheet = ContentStudioSheet()
    sheet.set_project_fields(title="Peluncuran", audience="Kreator", tone="Cinematic", hook="Mulai", cta="Coba")
    sheet.add_scene(title="Pembuka", visual="Kota", narration="Halo", visual_prompt="neon city")
    sheet.add_scene(title="Isi", visual="Studio", narration="Kenalkan", visual_prompt="product desk")

    rows = sheet.timeline_rows()
    assert [r["title"] for r in rows] == ["Pembuka", "Isi"]
    assert rows[0]["order"] == 1 and rows[0]["asset_state"] == "none"

    export = sheet.export_project("storyboard_md")
    assert export["ok"] is True and "Peluncuran" in export["content"] and "neon city" in export["content"]
    assert sheet.export_project("mp4_render") == {"ok": False, "reason": "content_export_format_rejected"}
