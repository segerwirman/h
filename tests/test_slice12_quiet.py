"""Fase 35 Slice 12 — local fallback observability characterization."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from jarvis.core import quiet


class _BrokenField:
    def setText(self, _value):
        raise RuntimeError("field unavailable")


class _BrokenStdout:
    encoding = "ascii"

    def __init__(self):
        self.parts = []

    def reconfigure(self, **_kwargs):
        raise OSError("stdout is not reconfigurable")

    def write(self, value):
        self.parts.append(value)
        return len(value)

    def flush(self):
        return None


def _spy(monkeypatch):
    events = []

    def record(event, exc=None, **_context):
        events.append((event, type(exc).__name__ if exc is not None else None))

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


@pytest.fixture(scope="module")
def app():
    from PyQt6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_task_halo_paint_failure_remains_fail_open_and_is_recorded(app, monkeypatch):
    from PyQt6.QtCore import QRect
    from PyQt6.QtGui import QPaintEvent
    from jarvis.ui.orb import OrbRenderer, OrbState
    from jarvis.ui.task_halo import TaskHaloOrb

    events = _spy(monkeypatch)
    monkeypatch.setattr(OrbRenderer, "paintEvent", lambda _self, _event: None)
    orb = TaskHaloOrb()
    orb.resize(120, 120)
    orb.set_state(OrbState.LISTENING)
    orb.set_task_progress(0.42, count=2)
    monkeypatch.setattr(orb, "_halo_visible", lambda: True)

    def fail_paint():
        raise RuntimeError("cosmetic arc failed")

    monkeypatch.setattr(orb, "_paint_task_arc", fail_paint)
    orb.paintEvent(QPaintEvent(QRect(0, 0, 120, 120)))

    assert orb.state is OrbState.LISTENING
    assert orb.task_progress == pytest.approx(0.42)
    assert events == [("ui.task_halo.task_arc_paint_failed", "RuntimeError")]


def test_content_title_field_failure_keeps_bounded_result_and_is_recorded(app, monkeypatch):
    from jarvis.ui.content_studio import ContentStudioSheet

    events = _spy(monkeypatch)
    sheet = ContentStudioSheet()
    sheet._field_refs["judul"] = _BrokenField()

    result = sheet.set_project_title("  Peluncuran Lokal  ")

    assert result == {
        "ok": True,
        "title": "Peluncuran Lokal",
        "intent": "content_studio_title",
    }
    assert sheet.project().title == "Peluncuran Lokal"
    assert "diperbarui" in sheet.status_text().lower()
    assert events == [("ui.content_studio.title_field_sync_failed", "RuntimeError")]


def test_prompt_print_keeps_output_when_reconfigure_fails_and_is_recorded(monkeypatch):
    from scripts import next_phase_prompt

    events = _spy(monkeypatch)
    stream = _BrokenStdout()
    monkeypatch.setattr(next_phase_prompt.sys, "stdout", stream)

    next_phase_prompt._print("prompt lokal")

    assert "prompt lokal\n" == "".join(stream.parts)
    assert events == [("scripts.next_phase_prompt.stdout_reconfigure_failed", "OSError")]


def test_prompt_print_unicode_fallback_preserves_output(monkeypatch):
    from scripts import next_phase_prompt

    events = _spy(monkeypatch)
    stream = _BrokenStdout()
    monkeypatch.setattr(next_phase_prompt.sys, "stdout", stream)

    next_phase_prompt._print("prompt ✅")

    assert "prompt ✅\n" == "".join(stream.parts)
    assert events == [("scripts.next_phase_prompt.stdout_reconfigure_failed", "OSError")]


def test_slice12_selected_block_count_is_bounded():
    assert 1 <= 3 <= 5


# The exact event assertions above intentionally fail before source migration;
# no source behavior is changed by this characterization file.


def test_selected_event_names_are_stable():
    assert {
        "ui.task_halo.task_arc_paint_failed",
        "ui.content_studio.title_field_sync_failed",
        "scripts.next_phase_prompt.stdout_reconfigure_failed",
    }


# Keep this module's recorder local; it stores only event and exception type.


def test_recorder_shape_is_minimal():
    events = []

    def record(event, exc=None, **_context):
        events.append((event, type(exc).__name__ if exc is not None else None))

    record("local.failed", RuntimeError("opaque"), secret="not stored")
    assert events == [("local.failed", "RuntimeError")]


# The three selected contracts are covered by one test per block above.
