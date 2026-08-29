"""Task 4 — local-only Chrome tab share picker UI.

Qt runs offscreen and all browser/coordinator dependencies are fakes. No live tab,
screenshot, pointer, browser input, or DesktopService authority is used.
"""
from __future__ import annotations

import os
import threading
import time
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QAbstractItemView, QWidget

from jarvis.integrations.selected_tab_browser import (
    LocalTabCandidate,
    PickerResult,
    SelectedTarget,
    SelectionResult,
)
from jarvis.ui import screen_control

_APP = QApplication.instance() or QApplication([])


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        _APP.processEvents()
        if predicate():
            return True
        threading.Event().wait(0.01)
    _APP.processEvents()
    return bool(predicate())


class _Host:
    def __init__(self, *, block=False) -> None:
        self.gate = threading.Event()
        if not block:
            self.gate.set()
        self.begin_threads = []
        self.cancelled = []
        self.selected = []
        self.stopped = []
        self.selected_matches_result = True
        self.selection_checks = 0
        self.picker = PickerResult(
            True,
            "tabs_available",
            picker_id="picker-local",
            candidates=(
                LocalTabCandidate("candidate-a", "Docs", "https://docs.test"),
                LocalTabCandidate("candidate-b", "Music", "https://music.test"),
            ),
        )

    def begin_picker(self):
        self.begin_threads.append(threading.get_ident())
        assert self.gate.wait(2)
        return self.picker

    def cancel_picker(self, picker_id):
        self.cancelled.append((picker_id, threading.get_ident()))
        return picker_id == "picker-local"

    def select_candidate(self, picker_id, candidate_id):
        self.selected.append((picker_id, candidate_id, threading.get_ident()))
        if picker_id != "picker-local" or candidate_id not in {"candidate-a", "candidate-b"}:
            return SelectionResult(False, "stopped", "selection mismatch")
        title = "Docs" if candidate_id == "candidate-a" else "Music"
        origin = "https://docs.test" if candidate_id == "candidate-a" else "https://music.test"
        return SelectionResult(
            True,
            "sharing",
            target=SelectedTarget("target-opaque", 7, title, origin),
        )

    def selection_is_active(self, target_id, target_generation):
        self.selection_checks += 1
        matches = self.selected_matches_result
        if isinstance(matches, list):
            matches = matches.pop(0)
        return bool(
            matches
            and target_id == "target-opaque"
            and target_generation == 7
        )

    def stop_selected(self, target_id, target_generation):
        self.stopped.append((target_id, target_generation, threading.get_ident()))
        return target_id == "target-opaque" and target_generation == 7


class _Coordinator:
    def __init__(self) -> None:
        self.activations = []
        self.revocations = []
        self.current = screen_control.ScreenControlSnapshot()

    def snapshot(self):
        return self.current

    def activate_browser_tab(
        self,
        session_id,
        task_id,
        *,
        target_id,
        target_generation,
        ttl_s,
    ):
        self.activations.append(
            (
                session_id,
                task_id,
                target_id,
                target_generation,
                ttl_s,
                threading.get_ident(),
            )
        )
        self.current = screen_control.ScreenControlSnapshot(
            screen_control.ACTIVE,
            session_id,
            task_id,
            150.0,
            screen_control.BROWSER_TAB_SURFACE,
            target_id,
            target_generation,
        )
        return True

    def revoke(self, reason):
        self.revocations.append((reason, threading.get_ident()))
        self.current = screen_control.ScreenControlSnapshot()
        return True

    def revoke_browser_tab(
        self,
        *,
        target_id,
        target_generation,
        reason,
    ):
        current = self.current
        if (
            current.surface_kind != screen_control.BROWSER_TAB_SURFACE
            or current.surface_id != target_id
            or current.surface_generation != target_generation
        ):
            return False
        return self.revoke(reason)


def _sheet(*, host=None, coordinator=None):
    from jarvis.ui.tab_share_sheet import TabShareSheet

    parent = QWidget()
    parent.resize(900, 700)
    parent.show()
    sheet = TabShareSheet(
        host=host or _Host(),
        coordinator=coordinator or _Coordinator(),
        ttl_provider=lambda: 30.0,
        parent=parent,
    )
    return parent, sheet


def test_present_returns_while_fake_attach_is_blocked_and_updates_asynchronously():
    host = _Host(block=True)
    parent, sheet = _sheet(host=host)
    caller_thread = threading.get_ident()
    try:
        started = time.monotonic()
        assert sheet.present(SimpleNamespace(session_id="session-a", task_id="T-a"), 900, 700)
        elapsed = time.monotonic() - started

        assert elapsed < 0.2
        assert sheet.state == "checking"
        assert sheet.isVisible()
        assert _wait_until(lambda: bool(host.begin_threads))
        assert host.begin_threads[0] != caller_thread

        host.gate.set()
        assert _wait_until(lambda: sheet.state == "tabs_available")
        assert sheet.candidate_titles() == ["Docs", "Music"]
    finally:
        host.gate.set()
        sheet.cancel_local()
        parent.close()
        _APP.processEvents()


def test_picker_exposes_only_tabs_not_window_or_entire_screen_choices():
    parent, sheet = _sheet()
    try:
        sheet.present(SimpleNamespace(session_id="session-a", task_id="T-a"), 900, 700)
        assert _wait_until(lambda: sheet.state == "tabs_available")

        labels = sheet.candidate_titles()
        assert labels == ["Docs", "Music"]
        assert "Window" not in labels
        assert "Entire Screen" not in labels
        assert sheet._candidates.selectionMode() == QAbstractItemView.SelectionMode.SingleSelection
    finally:
        sheet.cancel_local()
        parent.close()
        _APP.processEvents()


def test_target_that_closes_before_activation_never_becomes_screen_control_active():
    host = _Host()
    host.selected_matches_result = False
    coordinator = _Coordinator()
    parent, sheet = _sheet(host=host, coordinator=coordinator)
    try:
        sheet.present(SimpleNamespace(session_id="session-a", task_id="T-a"), 900, 700)
        assert _wait_until(lambda: sheet.state == "tabs_available")
        sheet._candidates.setCurrentRow(0)
        sheet._candidates.itemClicked.emit(sheet._candidates.currentItem())
        sheet.share_selected()

        assert _wait_until(lambda: sheet.state == "closed")
        assert coordinator.activations == []
        assert coordinator.snapshot().state == screen_control.OFF
        assert sheet.active_target_id == ""
    finally:
        parent.close()
        _APP.processEvents()


def test_target_close_during_activation_gap_revokes_new_orphan_authority():
    host = _Host()
    host.selected_matches_result = [True, False]
    coordinator = _Coordinator()
    parent, sheet = _sheet(host=host, coordinator=coordinator)
    try:
        sheet.present(SimpleNamespace(session_id="session-a", task_id="T-a"), 900, 700)
        assert _wait_until(lambda: sheet.state == "tabs_available")
        sheet._candidates.setCurrentRow(0)
        sheet._candidates.itemClicked.emit(sheet._candidates.currentItem())
        sheet.share_selected()

        assert _wait_until(lambda: sheet.state == "closed")
        assert host.selection_checks == 2
        assert coordinator.activations[0][:5] == (
            "session-a",
            "T-a",
            "target-opaque",
            7,
            30.0,
        )
        assert coordinator.revocations[-1][0] == "selected_tab_target_closed"
        assert coordinator.snapshot().state == screen_control.OFF
        assert sheet.active_target_id == ""
    finally:
        parent.close()
        _APP.processEvents()


def test_one_local_candidate_activates_exact_browser_surface_off_ui_thread():
    host = _Host()
    coordinator = _Coordinator()
    parent, sheet = _sheet(host=host, coordinator=coordinator)
    caller_thread = threading.get_ident()
    try:
        sheet.present(SimpleNamespace(session_id="session-a", task_id="T-a"), 900, 700)
        assert _wait_until(lambda: sheet.state == "tabs_available")
        sheet._candidates.setCurrentRow(1)
        sheet._candidates.itemClicked.emit(sheet._candidates.currentItem())
        sheet.share_selected()

        assert _wait_until(lambda: sheet.state == "sharing")
        assert host.selected[0][:2] == ("picker-local", "candidate-b")
        assert host.selected[0][-1] != caller_thread
        assert coordinator.activations[0][:5] == (
            "session-a",
            "T-a",
            "target-opaque",
            7,
            30.0,
        )
        assert coordinator.activations[0][-1] != caller_thread
        assert sheet.active_target_id == "target-opaque"
    finally:
        if sheet.state == "sharing":
            sheet.stop_sharing()
            _wait_until(lambda: sheet.state == "stopped")
        parent.close()
        _APP.processEvents()


def test_cancel_while_checking_retires_inventory_when_worker_finishes():
    host = _Host(block=True)
    parent, sheet = _sheet(host=host)
    try:
        sheet.present(SimpleNamespace(session_id="session-a", task_id="T-a"), 900, 700)
        assert _wait_until(lambda: bool(host.begin_threads))
        sheet.cancel_local()
        assert not sheet.isVisible()

        host.gate.set()
        assert _wait_until(lambda: bool(host.cancelled))
        assert host.cancelled[0][0] == "picker-local"
        assert host.cancelled[0][1] != threading.get_ident()
        assert sheet.state == "stopped"
    finally:
        host.gate.set()
        parent.close()
        _APP.processEvents()


def test_active_icon_manage_view_does_not_stop_or_rebind_until_explicit_button():
    host = _Host()
    coordinator = _Coordinator()
    parent, sheet = _sheet(host=host, coordinator=coordinator)
    active = screen_control.ScreenControlSnapshot(
        screen_control.ACTIVE,
        "session-a",
        "T-a",
        150.0,
        screen_control.BROWSER_TAB_SURFACE,
        "target-opaque",
        7,
    )
    try:
        assert sheet.present_manage(active, 900, 700) is True
        assert sheet.state == "sharing"
        assert host.begin_threads == []
        assert coordinator.revocations == []
        assert host.selected == []

        sheet.stop_sharing()
        assert _wait_until(lambda: sheet.state == "stopped")
        assert coordinator.revocations[0][0] == "user_stop_sharing"
        assert host.stopped[0][:2] == ("target-opaque", 7)
    finally:
        parent.close()
        _APP.processEvents()


@pytest.mark.parametrize(
    ("reason", "expected_state"),
    [
        ("selected_tab_target_closed", "closed"),
        ("selected_tab_browser_disconnected", "disconnected"),
    ],
)
def test_active_manage_view_reflects_fail_closed_browser_lifecycle(
    reason,
    expected_state,
):
    host = _Host()
    coordinator = _Coordinator()
    parent, sheet = _sheet(host=host, coordinator=coordinator)
    active = screen_control.ScreenControlSnapshot(
        screen_control.ACTIVE,
        "session-a",
        "T-a",
        150.0,
        screen_control.BROWSER_TAB_SURFACE,
        "target-opaque",
        7,
    )
    try:
        assert sheet.present_manage(active, 900, 700) is True

        sheet.apply_screen_control_state(
            {
                "active": False,
                "reason": reason,
                "surface_kind": "",
            }
        )

        assert sheet.state == expected_state
        assert sheet.active_target_id == ""
        assert sheet.isVisible() is True
        assert sheet._stop_button.isEnabled() is False
    finally:
        parent.close()
        _APP.processEvents()


def test_sheet_has_truthful_text_for_all_declared_local_states():
    parent, sheet = _sheet()
    try:
        for state in (
            "checking",
            "unavailable",
            "zero_tabs",
            "tabs_available",
            "selected",
            "preview_unavailable",
            "ready",
            "sharing",
            "navigated",
            "closed",
            "disconnected",
            "captcha_handoff",
            "stopped",
        ):
            assert sheet.set_runtime_state(state) is True
            assert sheet.status_text().strip()
        assert "tidak dapat" in sheet._state_text("unavailable", "").casefold()
        assert "berhasil" not in sheet._state_text("preview_unavailable", "").casefold()
    finally:
        parent.close()
        _APP.processEvents()


def test_window_panel_icon_opens_picker_or_manage_without_native_activation(monkeypatch):
    from jarvis.agent.dispatch import ScreenControlScope
    from jarvis.ui.window_panels import WindowPanelsMixin

    calls = []
    snapshots = [screen_control.ScreenControlSnapshot()]
    host = SimpleNamespace(
        centralWidget=lambda: SimpleNamespace(width=lambda: 900, height=lambda: 700),
        tab_share_sheet=SimpleNamespace(
            present=lambda *args: calls.append(("picker", args)) or True,
            present_manage=lambda *args: calls.append(("manage", args)) or True,
        ),
        write_log=lambda _message: None,
        notifications=SimpleNamespace(push=lambda *_args: None),
    )
    monkeypatch.setattr(screen_control.COORDINATOR, "snapshot", lambda: snapshots[0])
    monkeypatch.setattr(
        screen_control.COORDINATOR,
        "activate",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("icon must not activate native desktop")
        ),
    )
    monkeypatch.setattr(
        screen_control.COORDINATOR,
        "revoke",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("active icon must open manage view, not stop")
        ),
    )
    monkeypatch.setattr(
        "jarvis.core.config.get",
        lambda key, default=None: True if key == "screen_control.enabled" else default,
    )
    monkeypatch.setattr(
        "jarvis.agent.dispatch.screen_control_scope",
        lambda: ScreenControlScope("session-a", "T-a"),
    )

    WindowPanelsMixin._toggle_screen_control(host)
    snapshots[0] = screen_control.ScreenControlSnapshot(
        screen_control.ACTIVE,
        "session-a",
        "T-a",
        150.0,
        screen_control.BROWSER_TAB_SURFACE,
        "target-a",
        1,
    )
    WindowPanelsMixin._toggle_screen_control(host)

    assert [call[0] for call in calls] == ["picker", "manage"]
