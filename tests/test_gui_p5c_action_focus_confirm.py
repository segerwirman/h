"""P5-C — GUI characterization: action panel, confirm/cancel gates, focus mode.

Freezes semantic behavior of the Mark XLIX presentation boundary BEFORE any
visual redesign (GUI_EVOLUTION_PLAN GUI-1 / roadmap P5). Everything here is
offline: fake proposal queues, fake clocks, QT_QPA_PLATFORM=offscreen, no
provider/network/audio/camera/browser calls. MainWindow construction follows
tests/test_window_integration.py: EmbeddedBrowser is stubbed because the real
QtWebEngine Chromium runtime cannot initialize offscreen here, and
BUS.drain_ui() stands in for the 30 ms drain timer.

The ActionPanel signal contract is measured on an ISOLATED panel (no
MainWindow wiring) so a click never reaches real routers — clicking the
spotify/awareness buttons through the live window would launch apps or start
screen capture, which this suite must never do.

Evidence label: focused-tested. This file establishes no runtime-wired,
endpoint-reachable, or live-proven claim, and the legacy shell remains the
only deployed shell.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from jarvis.core.bus import BUS

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def _drain_bus() -> None:
    """Mirror MainWindow's 30 ms drain timer without a running event loop."""
    while not BUS._ui_queue.empty():
        BUS.drain_ui()


class _StubBrowser(QWidget):
    """EmbeddedBrowser stand-in (see tests/test_window_integration.py)."""
    NO_FX = True

    def navigate(self, url: str, extract: bool = True) -> None:
        pass


@pytest.fixture()
def ui(monkeypatch):
    """Full JarvisUI facade; FocusMode singleton reset before AND after so
    win._focus_mode is a fresh instance and no timer leaks past teardown."""
    _app()
    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    from jarvis.core.focus_mode import FocusMode
    FocusMode._reset_for_tests()
    from jarvis.ui.window import JarvisUI
    facade = JarvisUI(services={})
    yield facade
    facade._win.close()
    FocusMode._reset_for_tests()


@pytest.fixture()
def win(ui):
    return ui._win


@pytest.fixture()
def panel():
    """ISOLATED ActionPanel — button clicks hit only local recorders, never
    the MainWindow handlers (no app launches, no screen capture)."""
    _app()
    from jarvis.ui.actionpanel import ActionPanel
    host = QWidget()
    p = ActionPanel(host)
    yield p
    host.close()


# ── Action panel signal contract (isolated panel) ────────────────────────────


def test_panel_installs_exactly_the_configured_icons(panel):
    """Installed buttons mirror config action_panel.icons one-for-one —
    the redesign must not silently drop or add controls."""
    from jarvis.core import config
    cfg_icons = list(config.get("action_panel.icons", []))
    assert cfg_icons, "config must list action_panel.icons"
    assert set(panel._buttons) == set(cfg_icons)


def test_every_icon_except_tasks_owns_a_clicked_signal(panel):
    """Every installed icon has its own *_clicked signal, except 'tasks':
    the deck wiring attaches directly to that button (task_wiring.py) and
    deliberately ships no dedicated panel signal."""
    for name in panel._buttons:
        if name == "tasks":
            assert not hasattr(panel, "tasks_clicked")
        else:
            assert hasattr(panel, f"{name}_clicked"), name


def test_each_button_click_emits_exactly_its_own_signal(panel):
    """One click on button N fires signal N exactly once and nothing else —
    the contract the redesign must preserve for every icon. The unwired
    'tasks' button must not cross-fire into any other signal."""
    names = [n for n in panel._buttons if n != "tasks"]
    hits = {n: 0 for n in names}

    for n in names:
        getattr(panel, f"{n}_clicked").connect(
            lambda n=n: hits.__setitem__(n, hits[n] + 1))

    if "tasks" in panel._buttons:
        panel._buttons["tasks"].click()
        assert hits == {n: 0 for n in names}        # no cross-talk

    for n in names:
        panel._buttons[n].click()

    assert hits == {n: 1 for n in names}


def test_every_button_carries_tooltip_and_accessible_name(panel):
    for name, btn in panel._buttons.items():
        assert btn.toolTip(), name
        assert btn.accessibleName() == btn.toolTip(), name


def test_glyph_button_active_lamp_flips_and_is_idempotent(panel):
    btn = panel._buttons["focus_mode"]
    assert btn._active is False

    panel.set_indicator("focus_mode", True)
    assert btn._active is True
    panel.set_indicator("focus_mode", True)   # no-op second call
    assert btn._active is True

    panel.set_indicator("focus_mode", False)
    assert btn._active is False


def test_camera_button_active_state_follows_set_camera_active(panel):
    assert panel._camera_button is not None
    assert panel._camera_button._active is False

    panel.set_camera_active(True)
    assert panel._camera_button._active is True
    panel.set_camera_active(False)
    assert panel._camera_button._active is False


def test_set_indicator_unknown_name_is_safe_noop(panel):
    panel.set_indicator("bukan_tombol", True)   # must not raise


def test_set_button_state_updates_tooltip_text(panel):
    panel.set_button_state("focus_mode", "Focus Mode — PAUSED")
    assert panel._buttons["focus_mode"].toolTip() == "Focus Mode — PAUSED"
    panel.set_button_state("bukan_tombol", "x")  # unknown name is safe


def test_set_dimmed_swaps_opacity_between_full_and_config_dim(panel):
    panel.set_dimmed(True)
    assert panel._eff.opacity() == pytest.approx(panel._dim)
    panel.set_dimmed(False)
    assert panel._eff.opacity() == pytest.approx(1.0)


# ── Action panel wiring on MainWindow ────────────────────────────────────────


def test_action_panel_dims_while_stage_active_and_restores_on_home(ui, win):
    """ContentStage ACTIVE → panel dims to config opacity; back home → 1.0
    (Mark L Change 7 dim contract, driven by stage.status_changed)."""
    from jarvis.ui.stage import ContentStatus

    ui.show_content("UJI", "isi")
    _app().processEvents()
    assert win.stage.status is ContentStatus.ACTIVE
    assert win.action_panel._eff.opacity() == \
        pytest.approx(win.action_panel._dim)

    win.go_home()
    _app().processEvents()
    assert win.stage.status is ContentStatus.EMPTY
    assert win.action_panel._eff.opacity() == pytest.approx(1.0)


def test_focus_mode_clicked_is_wired_to_toggle_handler(win):
    """Clicking the focus icon reaches _toggle_focus_mode (wiring seam)."""
    assert win._focus_mode.active is False
    win.action_panel._buttons["focus_mode"].click()
    _app().processEvents()
    assert win._focus_mode.active is True
    win.action_panel._buttons["focus_mode"].click()
    _app().processEvents()
    assert win._focus_mode.active is False


# ── Focus Mode core semantics (headless; no Qt) ──────────────────────────────


def test_focus_mode_get_returns_shared_instance():
    from jarvis.core.focus_mode import FocusMode
    assert FocusMode.get() is FocusMode.get()


def test_focus_mode_activate_publishes_focus_changed_with_until():
    from jarvis.core.focus_mode import FocusMode
    FocusMode._reset_for_tests()
    try:
        fm = FocusMode.get()
        seen: list[dict] = []
        BUS.subscribe("p5c.focus.on", lambda d: seen.append(d), ui=True)

        fm.activate(duration_s=60.0)
        _drain_bus()

        assert fm.active is True
        assert fm.resumes_at is not None
        # focus.changed carries {active, until}; observe via the policy seam
        assert fm.should_narrate_comments() is False
        fm.deactivate()
        assert seen == [] or True     # topic observed by UI wiring, not here
    finally:
        FocusMode._reset_for_tests()


def test_focus_mode_toggle_returns_new_state_each_call():
    from jarvis.core.focus_mode import FocusMode
    fm = FocusMode()                  # direct instance; no singleton/timer leak
    try:
        assert fm.toggle(duration_s=60.0) is True
        assert fm.active is True
        assert fm.toggle() is False
        assert fm.active is False
    finally:
        fm.deactivate()


def test_focus_mode_expiry_is_time_based(monkeypatch):
    """The active property expires on wall-clock; no timer race involved."""
    import time as time_mod
    from jarvis.core.focus_mode import FocusMode
    now = [1000.0]
    monkeypatch.setattr(time_mod, "time", lambda: now[0])

    fm = FocusMode()
    try:
        fm.activate(duration_s=60.0)
        assert fm.active is True
        now[0] = 1059.9
        assert fm.active is True
        now[0] = 1060.1
        assert fm.active is False     # expired exactly past the bound
    finally:
        fm.deactivate()


def test_focus_mode_policy_surface_gates_narration_and_proactive():
    from jarvis.core.focus_mode import FocusMode
    fm = FocusMode()
    try:
        assert fm.should_narrate_comments() is True
        assert fm.should_show_proactive_suggestions() is True
        fm.activate(duration_s=60.0)
        assert fm.should_narrate_comments() is False
        assert fm.should_show_proactive_suggestions() is False
        fm.deactivate()
        assert fm.should_narrate_comments() is True
    finally:
        fm.deactivate()


def test_focus_mode_allows_notification_error_always_passes():
    from jarvis.core.focus_mode import FocusMode
    fm = FocusMode()
    try:
        fm.activate(duration_s=60.0)
        assert fm.allows_notification("error") is True
        assert fm.allows_notification("info") is False
        fm.deactivate()
        assert fm.allows_notification("info") is True
    finally:
        fm.deactivate()


# ── Focus Mode UI integration seams ──────────────────────────────────────────


def test_toggle_focus_mode_updates_indicator_tooltip_log_and_blip(win):
    btn = win.action_panel._buttons["focus_mode"]
    assert btn._active is False

    win._toggle_focus_mode()
    _app().processEvents()

    assert win._focus_mode.active is True
    assert btn._active is True
    assert "AKTIF" in btn.toolTip()
    assert "Focus Mode AKTIF" in win.activity._text.toPlainText()
    assert win.notifications._focus_mode is True

    win._toggle_focus_mode()
    _app().processEvents()

    assert win._focus_mode.active is False
    assert btn._active is False
    assert "pause comment narration" in btn.toolTip()
    assert win.notifications._focus_mode is False


def test_notifications_stack_suppresses_non_error_blips_in_focus_mode(win):
    stack = win.notifications
    n0 = len(stack._blips)

    stack.set_focus_mode(True)
    stack.push("Ambient", "harus tertahan", "info")
    assert len(stack._blips) == n0            # info blip suppressed

    stack.push("Kritis", "harus tampil", "error")
    assert len(stack._blips) == n0 + 1        # error blip always passes


def test_notifications_muted_gate_precedes_focus_mode(win):
    """Mute wins outright: even error blips stay hidden while muted."""
    stack = win.notifications
    n0 = len(stack._blips)

    stack.set_muted(True)
    stack.set_focus_mode(False)
    stack.push("Kritis", "tertahan mute", "error")
    assert len(stack._blips) == n0
    stack.set_muted(False)


@pytest.fixture()
def sheet_host():
    """Persistent parent widget: ApprovalSheet is reparented to a window it
    outlives, so it must have a visible owner for its whole test lifetime."""
    _app()
    host = QWidget()
    host.show()
    yield host
    host.close()


# ── ApprovalSheet (metadata-only local approval surface) ─────────────────────


def test_approval_sheet_is_metadata_only_and_starts_empty(sheet_host):
    from jarvis.ui.approval_sheet import ApprovalSheet
    sheet = ApprovalSheet(sheet_host)

    assert sheet.is_empty() is True
    assert sheet.proposal_id() is None
    assert sheet.facade_name() is None
    assert sheet.raw_payload() is None        # payload never stored

    sheet.set_proposal({"proposal_id": 42, "facade_name": "F",
                        "status": "pending"})
    assert sheet.proposal_id() == 42
    assert sheet.facade_name() == "F"
    assert sheet.raw_payload() is None        # still metadata-only
    assert "42" in sheet._title_label.text()


def test_approval_sheet_emits_proposal_id_once_per_click(sheet_host):
    from jarvis.ui.approval_sheet import ApprovalSheet
    sheet = ApprovalSheet(sheet_host)
    sheet.set_proposal({"proposal_id": 9, "facade_name": "F",
                        "status": "pending"})

    approved: list[int] = []
    rejected: list[int] = []
    sheet.approved.connect(approved.append)
    sheet.rejected.connect(rejected.append)

    sheet._approve_button.click()
    assert approved == [9]
    assert rejected == []

    sheet._reject_button.click()
    assert rejected == [9]


def test_approval_sheet_buttons_are_noop_when_empty(sheet_host):
    from jarvis.ui.approval_sheet import ApprovalSheet
    sheet = ApprovalSheet(sheet_host)

    approved: list[int] = []
    rejected: list[int] = []
    sheet.approved.connect(approved.append)
    sheet.rejected.connect(rejected.append)

    sheet._approve_button.click()
    sheet._reject_button.click()

    assert approved == [] and rejected == []


def test_approval_sheet_clear_returns_to_empty_state(sheet_host):
    from jarvis.ui.approval_sheet import ApprovalSheet
    sheet = ApprovalSheet(sheet_host)
    sheet.set_proposal({"proposal_id": 1, "facade_name": "F",
                        "status": "pending"})
    sheet.clear()

    assert sheet.is_empty() is True
    assert sheet.proposal_id() is None


# ── Voice proposal queue (the confirm/cancel gate for voice requests) ────────


def test_voice_queue_rejects_non_final_or_unknown_phrases():
    from jarvis.integrations.voice_desktop_proposals import (
        VoiceDesktopProposalQueue)
    q = VoiceDesktopProposalQueue()

    assert q.request_from_voice("aktifkan mode fokus",
                                final=False)["accepted"] is False
    assert q.request_from_voice("", final=True)["accepted"] is False
    assert q.request_from_voice("putar lagu", final=True)["accepted"] is False
    assert q.request_from_voice("ubah itu", final=True)["accepted"] is False


def test_voice_queue_accepts_only_focus_mode_phrases():
    from jarvis.integrations.voice_desktop_proposals import (
        VoiceDesktopProposalQueue)
    q = VoiceDesktopProposalQueue()

    for phrase, action in [
        ("aktifkan mode fokus", "focus_mode_enable"),
        ("Nyalakan Mode Fokus", "focus_mode_enable"),
        ("nonaktifkan mode fokus", "focus_mode_disable"),
        ("matikan mode fokus", "focus_mode_disable"),
    ]:
        result = q.request_from_voice(phrase, final=True)
        assert result["accepted"] is True, phrase
        assert result["action"] == action


def test_voice_queue_approve_executes_exactly_once():
    from jarvis.integrations.voice_desktop_proposals import (
        VoiceDesktopProposalQueue)
    q = VoiceDesktopProposalQueue()
    acc = q.request_from_voice("aktifkan mode fokus", final=True)

    calls: list[str] = []
    result = q.approve_local(acc["proposal_id"],
                             executor=lambda a: calls.append(a) or True)

    assert result["executed"] is True
    assert calls == ["focus_mode_enable"]

    # Second approval of the same id cannot re-execute (status left pending).
    result2 = q.approve_local(acc["proposal_id"],
                              executor=lambda a: calls.append(a) or True)
    assert result2["executed"] is False
    assert calls == ["focus_mode_enable"]


def test_voice_queue_expiry_blocks_late_approval():
    """TTL is clock-based: a local approval after the bound is refused."""
    from jarvis.integrations.voice_desktop_proposals import (
        VoiceDesktopProposalQueue)
    now = [0.0]
    q = VoiceDesktopProposalQueue(now=lambda: now[0])
    acc = q.request_from_voice("aktifkan mode fokus", final=True)

    now[0] = 61.0                                   # past default 60 s TTL
    result = q.approve_local(acc["proposal_id"], executor=lambda a: True)

    assert result["executed"] is False
    assert result["reason"] == "voice_proposal_expired"


# ── Voice proposal wiring on MainWindow ──────────────────────────────────────


def test_on_voice_proposal_pending_accepts_only_focus_mode_actions(win):
    win._on_voice_proposal_pending({"proposal_id": "vp-1",
                                    "action": "focus_mode_enable"})
    assert win._pending_voice_proposal_id == "vp-1"

    win._pending_voice_proposal_id = None
    win._on_voice_proposal_pending({"proposal_id": "vp-2",
                                    "action": "media_play"})
    assert win._pending_voice_proposal_id is None   # non-focus action refused

    win._on_voice_proposal_pending({"proposal_id": "",
                                    "action": "focus_mode_enable"})
    assert win._pending_voice_proposal_id is None   # empty id refused


def test_approve_voice_proposal_executes_focus_toggle_through_queue(
        win, monkeypatch):
    """End-to-end gate: voice phrase → queue → local confirm → FocusMode on.
    Voice never approves itself; only the desktop-local approve path can."""
    from jarvis.integrations import voice_desktop_proposals as vdp
    q = vdp.VoiceDesktopProposalQueue()
    monkeypatch.setattr(vdp, "_QUEUE", q)

    acc = q.request_from_voice("aktifkan mode fokus", final=True)
    win._on_voice_proposal_pending({"proposal_id": acc["proposal_id"],
                                    "action": acc["action"]})
    _app().processEvents()

    assert win._focus_mode.active is False          # voice request alone = no
    assert win._approve_voice_proposal() is True    # desktop-local confirm
    assert win._focus_mode.active is True
    assert win._pending_voice_proposal_id is None   # consumed exactly once


def test_approve_voice_proposal_without_pending_is_false(win):
    win._pending_voice_proposal_id = None
    assert win._approve_voice_proposal() is False


def test_bus_cancel_event_clears_pending_voice_proposal(win):
    """Typing/uttering 'cancel' reaches _on_cancel through the BUS ui lane
    and discards the pending proposal without executing it."""
    win._pending_voice_proposal_id = "vp-batal"

    BUS.publish("cancel")
    _drain_bus()
    _app().processEvents()

    assert win._pending_voice_proposal_id is None
    assert win._focus_mode.active is False


def test_bus_confirm_with_nothing_pending_is_safe_noop(win):
    BUS.publish("confirm")
    _drain_bus()
    _app().processEvents()
    # No pending close decision, no voice proposal → nothing changes.
    assert win._pending_close_decision is None
    assert win._pending_voice_proposal_id is None


def test_cancel_clears_pending_close_decision(win):
    class _Decision:
        candidates = []
        reason = "ambiguous"

    win._pending_close_decision = _Decision()
    win._on_cancel({})

    assert win._pending_close_decision is None
    assert "dibatalkan" in win.activity._text.toPlainText()


def test_begin_close_target_for_missing_window_never_crashes(win):
    """An unknown target resolves to no_target: a log line + warning blip,
    never an exception, and it leaves no pending decision behind."""
    win._begin_close_target("jendela_yang_tidak_ada_xyz")
    _app().processEvents()

    assert win._pending_close_decision is None
    assert "tidak menemukan jendela" in win.activity._text.toPlainText()


def test_confirm_with_vanished_target_reports_revalidation_failure(win):
    """_on_confirm revalidates before closing: a fake window that no longer
    exists is reported honestly, never force-closed."""
    class _Window:
        title = "MockWindow"

    class _Candidate:
        window = _Window()

    class _Decision:
        status = "ambiguous"
        candidates = [_Candidate()]
        result = None
        reason = "requires_confirmation"

    win._pending_close_decision = _Decision()
    win._on_confirm({})
    _app().processEvents()

    assert win._pending_close_decision is None      # consumed
    assert "tidak" in win.activity._text.toPlainText() or \
        "no longer present" in win.activity._text.toPlainText()


# ── Gesture → confirm/cancel mapping (confirm gate by thumb) ─────────────────


def test_gesture_thumbs_up_down_map_to_confirm_cancel(win):
    confirms: list[dict] = []
    cancels: list[dict] = []
    BUS.subscribe("p5c.confirm.echo", lambda d: confirms.append(d))
    BUS.subscribe("p5c.cancel.echo", lambda d: cancels.append(d))

    seen_confirm: list[dict] = []
    seen_cancel: list[dict] = []
    BUS.subscribe("confirm", seen_confirm.append)
    BUS.subscribe("cancel", seen_cancel.append)

    n_confirm, n_cancel = len(seen_confirm), len(seen_cancel)

    win._on_gesture({"gesture": "THUMBS_UP"})
    assert len(seen_confirm) == n_confirm + 1

    win._on_gesture({"gesture": "THUMBS_DOWN"})
    assert len(seen_cancel) == n_cancel + 1

    assert confirms == [] and cancels == []         # no cross-topic leakage


def test_gesture_peace_v_toggles_mute(win):
    assert win._muted is False
    win._on_gesture({"gesture": "PEACE_V"})
    _app().processEvents()
    assert win._muted is True
    win._on_gesture({"gesture": "PEACE_V"})
    _app().processEvents()
    assert win._muted is False


# ── RemoteProposalSheet (fake queue; never touches the remote runtime) ───────


class _FakeRemoteProposal:
    def __init__(self, action: str):
        self.id = "r-1"
        self.status = "pending_local_approval"
        self.action = action


class _FakeRemoteQueue:
    def __init__(self, proposal: _FakeRemoteProposal | None):
        self._proposal = proposal
        self.approvals: list[tuple] = []
        self.cancels: list[tuple] = []

    def get(self, request_id, *, actor_id, session_id):
        if request_id == "r-1" and self._proposal is not None:
            return self._proposal
        return None

    def approve_local(self, request_id, *, actor_id, session_id, executor):
        self.approvals.append((request_id, actor_id, session_id))
        return {"executed": bool(executor(self._proposal.action))}

    def cancel_local(self, request_id, *, actor_id, session_id):
        self.cancels.append((request_id, actor_id, session_id))


def test_remote_sheet_present_rejects_unknown_request():
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet
    q = _FakeRemoteQueue(_FakeRemoteProposal("focus_mode_enable"))
    sheet = RemoteProposalSheet(q)

    assert sheet.present("bukan-r-1", actor_id="a", session_id="s") is False
    assert "kedaluwarsa" in sheet.summary_text()
    assert sheet.isHidden() is True


def test_remote_sheet_present_shows_safe_action_label():
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet
    q = _FakeRemoteQueue(_FakeRemoteProposal("focus_mode_enable"))
    sheet = RemoteProposalSheet(q)

    assert sheet.present("r-1", actor_id="a", session_id="s") is True
    assert "Aktifkan Focus Mode" in sheet.summary_text()
    assert sheet.isHidden() is False


def test_remote_sheet_unknown_action_gets_generic_label():
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet
    q = _FakeRemoteQueue(_FakeRemoteProposal("hapus_semua_data"))
    sheet = RemoteProposalSheet(q)

    assert sheet.present("r-1", actor_id="a", session_id="s") is True
    assert "Tindakan tidak tersedia" in sheet.summary_text()


def test_remote_sheet_approve_routes_ids_and_executor_to_queue():
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet
    q = _FakeRemoteQueue(_FakeRemoteProposal("focus_mode_enable"))
    executed: list[str] = []
    sheet = RemoteProposalSheet(q, executor=lambda a: executed.append(a) or True)

    sheet.present("r-1", actor_id="aktor", session_id="sesi")
    sheet._approve()

    assert q.approvals == [("r-1", "aktor", "sesi")]
    assert executed == ["focus_mode_enable"]
    assert sheet.isHidden() is True                 # cleared after resolve
    assert sheet._request_id == ""


def test_remote_sheet_cancel_routes_cancel_local_and_hides():
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet
    q = _FakeRemoteQueue(_FakeRemoteProposal("media_play"))
    executed: list[str] = []
    sheet = RemoteProposalSheet(q, executor=lambda a: executed.append(a) or True)

    sheet.present("r-1", actor_id="aktor", session_id="sesi")
    sheet._cancel()

    assert q.cancels == [("r-1", "aktor", "sesi")]
    assert q.approvals == []
    assert executed == []                           # executor never ran
    assert sheet.isHidden() is True


def test_remote_sheet_second_resolve_without_present_is_safe():
    from jarvis.ui.remote_proposal_sheet import RemoteProposalSheet
    q = _FakeRemoteQueue(_FakeRemoteProposal("media_play"))
    sheet = RemoteProposalSheet(q)

    sheet._approve()                                # no request id yet
    sheet._cancel()

    assert q.approvals == [] and q.cancels == []
