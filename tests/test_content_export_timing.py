"""Phase 23 RED — export timing integration + in-memory preview."""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

_APP_REF = None  # referensi global: QApplication yang di-GC = Qt abort


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication(sys.argv)
    return _APP_REF


def _project():
    from jarvis.core.content_project import ContentProject, Scene

    return ContentProject(
        title="T", audience="A", tone="Ton", hook="H", cta="C",
        scenes=(Scene("S0", "V0", "N0", "P0"),
                Scene("S1", "V1", "N1", "P1"),
                Scene("S2", "V2", "N2", "P2")),
    )


def test_export_captions_srt_uses_validated_cumulative_durations():
    from jarvis.core.content_export import export_project

    result = export_project(_project(), fmt="captions_srt", durations=[5, 10, 15])
    assert result["ok"] is True
    content = result["content"]
    assert "00:00:00,000 --> 00:00:05,000" in content
    assert "00:00:05,000 --> 00:00:15,000" in content
    assert "00:00:15,000 --> 00:00:30,000" in content
    assert "N0" in content and "N2" in content


def test_export_rejects_invalid_durations_without_content():
    from jarvis.core.content_export import export_project

    result = export_project(_project(), fmt="captions_srt", durations=[5, -1, 15])
    assert result["ok"] is False
    assert "content" not in result


def test_export_default_durations_stay_backward_compatible():
    from jarvis.core.content_export import export_project

    result = export_project(_project(), fmt="captions_srt")
    assert result["ok"] is True
    assert "00:00:00,000 --> 00:00:05,000" in result["content"]
    assert "00:00:05,000 --> 00:00:10,000" in result["content"]


def test_shot_list_csv_carries_validated_durations():
    from jarvis.core.content_export import export_project

    result = export_project(_project(), fmt="shot_list_csv", durations=[5, 10, 15])
    assert result["ok"] is True
    lines = result["content"].strip().splitlines()
    assert lines[0] == "order,title,visual,duration_s"
    assert lines[1] == "1,S0,V0,5"
    assert lines[3] == "3,S2,V2,15"


def test_preview_export_returns_in_memory_strings_with_timing():
    from jarvis.core.content_export import preview_export

    story = preview_export(_project(), fmt="storyboard_md", durations=[5, 10, 15])
    assert story["ok"] is True
    assert "00:00:05,000" in story["content"]        # timing visible
    assert "Scene 1: S0" in story["content"]

    captions = preview_export(_project(), fmt="captions_srt", durations=[5, 10, 15])
    assert captions["ok"] is True
    assert "00:00:15,000 --> 00:00:30,000" in captions["content"]

    assert preview_export(_project(), fmt="captions_srt", durations=[5, -1])["ok"] is False


def test_preview_export_never_writes_files(tmp_path):
    import os

    from jarvis.core.content_export import preview_export

    before = set(os.listdir(tmp_path))
    preview_export(_project(), fmt="storyboard_md", durations=[5, 5, 5])
    preview_export(_project(), fmt="captions_srt", durations=[5, 5, 5])
    assert set(os.listdir(tmp_path)) == before


def test_sheet_preview_export_returns_safe_metadata():
    _app()
    from jarvis.ui.content_studio import ContentStudioSheet

    sheet = ContentStudioSheet()
    for i in range(3):
        sheet.add_scene(title=f"S{i}", visual=f"V{i}",
                        narration=f"N{i}", visual_prompt=f"P{i}")
    result = sheet.preview_export("captions_srt", durations=[5, 10, 15])
    assert result["ok"] is True
    assert "00:00:05,000 --> 00:00:15,000" in result["content"]
    assert sheet.preview_export("captions_srt", durations=[5, -1])["ok"] is False
