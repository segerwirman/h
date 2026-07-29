"""Deterministic Mark XLIX P0 UI contracts (no renderer snapshots required)."""
from __future__ import annotations

import inspect
import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from jarvis.ui.actionpanel import CameraButton
from jarvis.ui.orb import OrbRenderer, OrbState, PresentationMode
from jarvis.ui.stage import ContentStage, ContentStatus
from jarvis.ui.window import JarvisUI, MainWindow


_APP_REF: QApplication | None = None


def _app() -> QApplication:
    # Keep a persistent reference: PyQt6 will crash (native stack corruption)
    # if the QApplication wrapper is garbage-collected while Qt still treats
    # it as the live singleton.
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def _orb() -> OrbRenderer:
    _app()
    orb = OrbRenderer()
    orb.resize(1000, 700)
    return orb


def test_speaking_empty_is_full_size_radial_and_orbiting():
    orb = _orb()
    try:
        orb.set_state(OrbState.SPEAKING)
        shot = orb.presentation_snapshot()
        assert shot == {
            "mode": PresentationMode.FULL_EMPTY_STAGE.value,
            "diameter": 300.0,
            "docked": False,
            "waveform_bars": 24,
            "particles": "orbit",
            "halo": True,
        }
    finally:
        orb._timer.stop()


def test_speaking_active_content_is_docked_140_with_24_bars():
    orb = _orb()
    try:
        orb.set_state(OrbState.SPEAKING)
        orb.set_presentation(PresentationMode.DOCKED_CONTENT_STAGE)
        shot = orb.presentation_snapshot()
        assert shot["diameter"] == 140.0
        assert shot["docked"] is True
        assert shot["waveform_bars"] == 24
        assert shot["halo"] is False
    finally:
        orb._timer.stop()


def test_loading_does_not_activate_or_dock_and_clear_restores_empty():
    _app()
    stage = ContentStage()
    stage.register("payload", QWidget())
    stage.begin_loading("payload")
    assert stage.status is ContentStatus.LOADING
    stage.activate("payload")
    assert stage.status is ContentStatus.ACTIVE
    stage.hide_all()
    assert stage.status is ContentStatus.EMPTY


def test_old_brackets_are_removed_and_halo_is_full_only():
    source = Path("jarvis/ui/orb.py").read_text(encoding="utf-8")
    assert "_paint_brackets" not in source
    orb = _orb()
    try:
        orb.set_state(OrbState.SPEAKING)
        assert orb.presentation_snapshot()["halo"] is True
        orb.set_presentation(PresentationMode.DOCKED_CONTENT_STAGE)
        assert orb.presentation_snapshot()["halo"] is False
    finally:
        orb._timer.stop()


def test_camera_control_is_a_recognizable_vector_path():
    _app()
    path = CameraButton.camera_path(24)
    assert not path.isEmpty()
    assert path.boundingRect().width() > path.boundingRect().height() / 2
    assert "Camera and vision panel" == CameraButton(22).accessibleName()


def test_camera_button_paint_event_renders_without_raising():
    """Regression guard: paintEvent once crashed with a TypeError because
    QPainter.drawEllipse has no 4-float overload — render() drives the real
    paint path for both the inactive and active (shutter-lamp) branches."""
    from PyQt6.QtGui import QPixmap
    _app()
    btn = CameraButton(22)
    btn.resize(44, 40)
    for active in (False, True):
        btn.set_active(active)
        pm = QPixmap(btn.size())
        pm.fill()
        btn.render(pm)   # raises through if paintEvent throws


def test_boot_has_no_briefing_or_boot_time_notification_poll():
    main_source = Path("jarvis/main.py").read_text(encoding="utf-8")
    boot_source = Path("jarvis/core/boot.py").read_text(encoding="utf-8")
    assert "NotificationHub().poll" not in main_source
    assert "build_greeting(" not in boot_source
    assert "news" not in main_source.lower()
    assert "weather" not in main_source.lower()


def test_facade_states_and_hotkeys_are_preserved():
    required = ("set_state", "write_log", "show_content", "start_camera_stream",
                "stop_camera_stream", "queue_greeting")
    for name in required:
        assert hasattr(JarvisUI, name)
    assert list(inspect.signature(JarvisUI.set_state).parameters) == ["self", "state"]
    assert {state.value for state in OrbState} == {
        "BOOT", "IDLE", "LISTENING", "THINKING", "SPEAKING", "EXECUTING", "ERROR"}
    source = inspect.getsource(MainWindow._bind_hotkeys)
    for key in ("mute", "fullscreen", "interrupt"):
        assert f'"hotkeys.{key}"' in source


def test_emergency_stop_gesture_has_no_panel_visibility_gate():
    """PALM_HOLD_3S must stay unconditionally active whenever the vision
    subsystem is available — it must not depend on whether the camera
    panel is currently visible (redesign §3). The worker runs in a
    separate process (jarvis.vision.process) with no reference to the Qt
    UI at all, so this is architecturally guaranteed; this guard proves
    the handling block itself carries no such condition and never will
    without failing this test."""
    source = Path("jarvis/vision/process.py").read_text(encoding="utf-8")
    start = source.index("PALM_HOLD_3S")
    end = source.index("event_q.put({\"type\": \"gesture\"", start)
    block = source[start:end]
    assert "emergency_stop()" in block
    for forbidden in ("stage.current", "vision_panel", "panel_visible",
                      "is_visible", "isVisible"):
        assert forbidden not in block


def test_no_hardcoded_hex_colors_outside_theme_module():
    """Every visual token must be configurable (redesign §3, §19) —
    theme.py is the one designated place for fallback default colors;
    everything else in jarvis/ui must read from theme.PAL / config."""
    import re
    hex_re = re.compile(r'["\']#[0-9a-fA-F]{3,8}["\']')
    ui_dir = Path("jarvis/ui")
    offenders = {}
    for path in ui_dir.glob("*.py"):
        if path.name == "theme.py":
            continue
        matches = hex_re.findall(path.read_text(encoding="utf-8"))
        if matches:
            offenders[path.name] = matches
    assert offenders == {}
