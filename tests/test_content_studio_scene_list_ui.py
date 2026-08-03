"""Phase 22 RED — Content Studio scene list production UX.

Scene order visible + deterministic Move Up/Down controls, reusing the
existing move_scene() policy path, with selected/asset mapping following the
moved scene and stable accessibility identity for the Phase 21 UIA lane.
"""
from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication


_APP_REF = None  # referensi global: QApplication yang di-GC = Qt abort


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication(sys.argv)
    return _APP_REF


def _sheet_with_scenes(n: int = 3):
    _app()  # QApplication wajib sebelum konstruksi QWidget
    from jarvis.ui.content_studio import ContentStudioSheet

    sheet = ContentStudioSheet()
    for i in range(n):
        sheet.add_scene(title=f"S{i}", visual=f"V{i}",
                        narration=f"N{i}", visual_prompt=f"P{i}")
    return sheet


def test_scene_list_renders_scenes_with_order_numbers():
    # RED: widget scene list belum ada
    sheet = _sheet_with_scenes(3)
    scene_list = sheet.scene_list_widget()
    assert scene_list is not None
    assert scene_list.count() == 3
    assert [scene_list.item(i).text() for i in range(3)] == ["1. S0", "2. S1", "3. S2"]


def test_scene_list_selection_updates_selected_scene():
    sheet = _sheet_with_scenes(3)
    scene_list = sheet.scene_list_widget()
    assert sheet.select_scene(2) is True
    # render ulang setelah selection mempertahankan selected index
    assert sheet.selected_scene() == 2
    assert scene_list.currentRow() == 2


def test_move_up_down_reorders_and_refreshes_list():
    sheet = _sheet_with_scenes(3)
    sheet.select_scene(2)
    assert sheet.move_selected_up() is True
    titles = [sheet.scene_list_widget().item(i).text() for i in range(3)]
    assert titles == ["1. S0", "2. S2", "3. S1"]
    assert sheet.selected_scene() == 1          # selected mengikuti scene yang dipindah
    rows = sheet.timeline_rows()
    assert [r["title"] for r in rows] == ["S0", "S2", "S1"]


def test_first_up_and_last_down_rejected():
    sheet = _sheet_with_scenes(3)
    sheet.select_scene(0)
    assert sheet.move_selected_up() is False    # first-up reject, no mutation
    assert [sheet.scene_list_widget().item(i).text() for i in range(3)] == \
        ["1. S0", "2. S1", "3. S2"]
    sheet.select_scene(2)
    assert sheet.move_selected_down() is False  # last-down reject
    assert [sheet.scene_list_widget().item(i).text() for i in range(3)] == \
        ["1. S0", "2. S1", "3. S2"]


def test_asset_metadata_follows_reordered_scene():
    # RED: move_scene belum meng-update _asset["scene_index"]
    sheet = _sheet_with_scenes(3)
    sheet._asset = {"scene_index": 2, "provider": "fake", "model": "fake"}
    sheet.select_scene(2)
    assert sheet.move_selected_up() is True
    asset = sheet.asset_metadata()
    assert asset is not None
    assert asset["scene_index"] == 1            # asset mengikuti scene asli yang pindah


def test_scene_controls_have_stable_accessibility_identity():
    sheet = _sheet_with_scenes(2)
    scene_list = sheet.scene_list_widget()
    up = sheet.move_up_button()
    down = sheet.move_down_button()
    assert scene_list.objectName() == "jarvis-scene-list"
    assert scene_list.accessibleName() == "Daftar Scene"
    assert up.objectName() == "jarvis-scene-move-up"
    assert down.objectName() == "jarvis-scene-move-down"
