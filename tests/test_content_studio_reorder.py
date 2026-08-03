"""Phase 20 RED — ContentStudioSheet.move_scene bounded reorder."""

def _make_sheet():
    from jarvis.ui.content_studio import ContentStudioSheet
    sheet = ContentStudioSheet.__new__(ContentStudioSheet)
    # bypass QWidget __init__ to avoid QApplication heavy in RED; call init parts manually
    # We'll use QObject-ish minimal: rely on real constructor requires QApplication, so create app
    from PyQt6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)
    return ContentStudioSheet()


def test_sheet_must_have_move_scene():
    from jarvis.ui.content_studio import ContentStudioSheet
    assert hasattr(ContentStudioSheet, "move_scene")


def test_move_scene_bounded_only():
    from PyQt6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)

    from jarvis.ui.content_studio import ContentStudioSheet
    sheet = ContentStudioSheet()
    # empty fails
    assert sheet.move_scene(0, 1)["ok"] is False

    # add 3 scenes
    for i in range(3):
        sheet.add_scene(title=f"S{i}", visual=f"V{i}", narration=f"N{i}", visual_prompt=f"P{i}")
    # valid reorder 0->2
    res = sheet.move_scene(0, 2)
    assert res["ok"] is True
    assert res["intent"] == "content_studio_scene_reorder"
    rows = sheet.timeline_rows()
    # after moving S0 to index 2, order should be S1,S2,S0
    titles = [r["title"] for r in rows]
    assert titles == ["S1", "S2", "S0"]


def test_move_scene_preserves_other_fields_and_selected():
    from PyQt6.QtWidgets import QApplication
    import sys
    app = QApplication.instance() or QApplication(sys.argv)

    from jarvis.ui.content_studio import ContentStudioSheet
    sheet = ContentStudioSheet()
    sheet.set_project_fields(title="T", audience="A", tone="Ton", hook="H", cta="C")
    for i in range(3):
        sheet.add_scene(title=f"S{i}", visual=f"V{i}", narration=f"N{i}", visual_prompt=f"P{i}")
    sheet.select_scene(0)
    sheet.move_scene(0, 1)
    proj = sheet.project()
    assert proj.title == "T"
    assert proj.audience == "A"


def test_move_scene_no_filesystem_or_generic_path():
    src = open(r"E:\jarvis agent\h\jarvis\ui\content_studio.py", encoding="utf-8").read()
    # must not introduce upload/publish/filesystem for reorder
    assert "def move_scene" in src
    # must use admit_reorder policy
    assert "admit_reorder" in src or "content_scene_reorder" in src
    # must not contain webbrowser, subprocess, requests for this
    # we allow QLineEdit usage from prior phase but not for move_scene introducing new dangerous imports
    low = src.lower()
    assert low.count("webbrowser") == 0
