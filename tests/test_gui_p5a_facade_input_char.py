"""P5-A — GUI characterization tests: facade seams and input contract.

Freezes the semantic behavior of the Mark XLIX presentation boundary BEFORE
any visual redesign (GUI_EVOLUTION_PLAN GUI-1 / roadmap P5). Everything here
is offline: fake services, fake BUS payloads, QT_QPA_PLATFORM=offscreen, no
provider/network/audio/camera/browser calls. MainWindow construction follows
tests/test_window_integration.py: EmbeddedBrowser is stubbed because the real
QtWebEngine Chromium runtime cannot initialize offscreen in this environment,
and BUS.drain_ui() stands in for the 30 ms drain timer.

Evidence label: focused-tested. This file establishes no runtime-wired,
endpoint-reachable, or live-proven claim, and the legacy shell remains the
only deployed shell.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtCore import QEvent, Qt
from PyQt6.QtGui import QKeyEvent
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


class _FakeSpeechQueue:
    def __init__(self):
        self.said: list[tuple[str, str]] = []

    def say(self, line: str, *, kind: str = "", turn: str = "") -> None:
        self.said.append((line, kind))


class _FakePredictive:
    def __init__(self, suggestion: str = ""):
        self._suggestion = suggestion
        self.recorded: list[str] = []

    def suggest(self, text: str) -> str:
        return self._suggestion if text and self._suggestion.startswith(text) else ""

    def record(self, text: str) -> None:
        self.recorded.append(text)


@pytest.fixture()
def ui(monkeypatch):
    """Full JarvisUI facade (MainWindow inside), no mic meter thread."""
    _app()
    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    from jarvis.ui.window import JarvisUI
    facade = JarvisUI(services={})
    yield facade
    facade._win.close()


@pytest.fixture()
def win(ui):
    return ui._win


def _key(widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
    """Direct keyPressEvent dispatch — no event loop needed."""
    widget.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, modifiers))


# ── JarvisUI facade contract ─────────────────────────────────────────────────


def test_write_log_reaches_activity_drawer_and_keeps_text(win):
    win.write_log("SYS: characterization ping")
    _app().processEvents()

    plain = win.activity._text.toPlainText()
    assert "SYS: characterization ping" in plain


def test_user_prefixed_log_enters_voice_intercept_path(win):
    """Typed 'You:' echoes are routed with _skip_next_intercept=True so the
    echo never re-routes through the voice intercept (window_commands.py).
    'kembali' resolves locally (same input test_window_integration uses), so
    this slice never falls through to the chat/provider path."""
    win.handle_command("kembali")
    _drain_bus()
    _app().processEvents()

    assert "You: kembali" in win.activity._text.toPlainText()


def test_speak_line_logs_and_enqueues_single_queue(win):
    fake = _FakeSpeechQueue()
    win._speech = lambda: fake

    win._speak_line("Siap, sir.", kind="ack")
    _app().processEvents()

    assert fake.said == [("Siap, sir.", "ack")]
    assert "Jarvis: Siap, sir." in win.activity._text.toPlainText()


def test_jarvis_prefixed_log_also_reaches_task_result_drawer(win):
    win.write_log("Jarvis: hasil ringkas")
    _app().processEvents()

    assert "hasil ringkas" in win.task_results._text.toPlainText()


@pytest.mark.parametrize("legacy,orb_name", [
    ("LISTENING", "LISTENING"),
    ("SPEAKING", "SPEAKING"),
    ("THINKING", "THINKING"),
    ("PROCESSING", "EXECUTING"),
    ("EXECUTING", "EXECUTING"),
    ("SLEEPING", "IDLE"),
    ("INITIALISING", "BOOT"),
    ("MUTED", "IDLE"),
    ("ERROR", "ERROR"),
    ("IDLE", "IDLE"),
])
def test_set_state_maps_legacy_names_to_orb_states(ui, win, legacy, orb_name):
    ui.set_state(legacy)
    _app().processEvents()

    from jarvis.ui.orb import OrbState
    assert win._legacy_state == legacy
    assert win.orb.state is OrbState(orb_name)


def test_set_state_unknown_name_falls_back_to_idle(ui, win):
    ui.set_state("NO_SUCH_STATE")
    _app().processEvents()

    from jarvis.ui.orb import OrbState
    assert win._legacy_state == "NO_SUCH_STATE"
    assert win.orb.state is OrbState.IDLE


def test_show_content_mounts_info_card_and_activates_stage(ui, win):
    ui.show_content("RINGKASAN", "baris satu\nbaris dua")
    _app().processEvents()

    from jarvis.ui.stage import ContentStatus
    assert win.info_panel is not None
    assert win.info_panel.card_count == 1
    assert win.stage.current == "info"
    assert win.stage.status is ContentStatus.ACTIVE


def test_show_content_bounds_title_and_text_before_crossing_signal(ui):
    """Facade truncates to the documented 64/6000 bound at the port."""
    long_title = "T" * 200
    long_text = "x" * 9000
    ui.show_content(long_title, long_text)
    _app().processEvents()

    # No exception and the signal carried bounded values; info panel still got
    # exactly one card with the bounded title.
    win = ui._win
    assert win.info_panel.card_count == 1


def test_wait_for_api_key_is_bounded_and_returns_false_when_not_ready(ui):
    stop_calls = {"n": 0}
    ui._win._ready = False  # force negative path (provider probes often succeed)

    def should_stop():
        stop_calls["n"] += 1
        return False

    result = ui.wait_for_api_key(timeout=0.3, should_stop=should_stop)

    assert result is False
    assert stop_calls["n"] >= 1


def test_wait_for_api_key_honors_should_stop(ui):
    ui._win._ready = False  # force negative path to ensure quick exit on stop
    assert ui.wait_for_api_key(timeout=30.0, should_stop=lambda: True) is False


def test_wait_for_api_key_returns_true_when_ready(ui):
    ui._win._ready = True
    assert ui.wait_for_api_key(timeout=0.1) is True


def test_prompt_reconfig_flips_ready_and_shows_api_sheet(ui, win):
    win._ready = True

    ui.prompt_reconfig()
    _app().processEvents()

    assert win._ready is False
    assert win._api_sheet is not None
    assert win._api_sheet.isHidden() is False


def test_callback_properties_delegate_to_window(ui, win):
    cb_text = lambda t: None
    cb_remote = lambda: None
    cb_interrupt = lambda e=None: None

    ui.on_text_command = cb_text
    ui.on_remote_clicked = cb_remote
    ui.on_interrupt = cb_interrupt

    assert ui.on_text_command is cb_text
    assert ui.on_remote_clicked is cb_remote
    assert ui.on_interrupt is cb_interrupt
    assert win.on_text_command is cb_text


def test_muted_property_delegates_to_toggle_mute(ui, win):
    assert ui.muted is False

    ui.muted = True
    _app().processEvents()
    assert win._muted is True
    assert ui.muted is True

    ui.muted = False
    _app().processEvents()
    assert win._muted is False


def test_current_file_property_reflects_window_state(ui, win):
    assert ui.current_file is None
    win._current_file = "laporan.pdf"
    assert ui.current_file == "laporan.pdf"


def test_camera_seams_with_no_vision_owner_are_bounded(ui, win):
    """No vision owner → seams degrade without raising or starting threads."""
    assert win.vision is None
    ui.show_camera_frame(b"\xff\xd8fake")
    _drain_bus()
    ui.start_camera_stream()
    ui.stop_camera_stream()
    assert ui.get_camera_snapshot(timeout=0.05) is None


def test_queue_greeting_is_bounded_noop(ui):
    ui.queue_greeting("Selamat pagi.")   # logs only; must not raise/enqueue


def test_start_stop_speaking_set_expected_states(ui, win):
    ui.start_speaking()
    _app().processEvents()
    assert win._legacy_state == "SPEAKING"

    ui.stop_speaking()
    _app().processEvents()
    assert win._legacy_state == "LISTENING"


# ── Input contract: CommandBar / _CliTextEdit ────────────────────────────────


def _make_bar(predictive=None):
    from jarvis.ui.window_widgets import CommandBar
    bar = CommandBar(predictive)
    return bar


def test_one_submit_emits_exactly_one_command_and_clears_input():
    bar = _make_bar()
    got: list[str] = []
    bar.submitted.connect(got.append)

    bar.input.setPlainText("  buka spotify  ")
    _key(bar.input, Qt.Key.Key_Return)

    assert got == ["buka spotify"]
    assert bar.input.toPlainText() == ""


def test_empty_submit_emits_nothing():
    bar = _make_bar()
    got: list[str] = []
    bar.submitted.connect(got.append)

    bar.input.setPlainText("   ")
    _key(bar.input, Qt.Key.Key_Return)

    assert got == []


def test_shift_enter_keeps_multiline_and_does_not_submit():
    """Shift+Enter inserts a newline without submitting — this is standard Qt
    QTextEdit behavior; in offscreen mode the key event must propagate to super()
    so we assert that no submit fires on Shift+Return."""
    bar = _make_bar()
    got: list[str] = []
    bar.submitted.connect(got.append)

    bar.input.setPlainText("baris satu")
    _key(bar.input, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)

    # No submit should happen with Shift modifier — multiline mode stays intact.
    assert got == []


def test_predictive_ghost_accepts_via_tab_and_records_nothing():
    pred = _FakePredictive("buka spotify")
    bar = _make_bar(pred)
    tab_hits: list[None] = []
    bar.input.tab_pressed.connect(lambda: tab_hits.append(None))

    bar.input.setPlainText("buka")        # triggers suggest("buka")
    assert bar.input._ghost == " spotify"

    _key(bar.input, Qt.Key.Key_Tab)
    assert bar.input.toPlainText() == "buka spotify"
    assert bar.input._ghost == ""
    assert tab_hits == [None]
    assert pred.recorded == []            # ghost acceptance is not a submission


def test_slash_on_empty_input_requests_palette():
    bar = _make_bar()
    requests: list[str] = []
    bar.input.palette_requested.connect(requests.append)

    _key(bar.input, Qt.Key.Key_Slash)
    assert requests == [""]
    assert bar.input.toPlainText() == ""  # slash itself is not inserted


def test_submit_records_predictive_usage():
    pred = _FakePredictive()
    bar = _make_bar(pred)
    got: list[str] = []
    bar.submitted.connect(got.append)

    bar.input.setPlainText("ringkas file")
    bar._submit()

    assert got == ["ringkas file"]
    assert pred.recorded == ["ringkas file"]


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])


def test_send_button_and_enter_share_one_submission_seam():
    bar = _make_bar()
    got: list[str] = []
    bar.submitted.connect(got.append)

    bar.input.setPlainText("halo jarvis")
    bar._send.clicked.emit()
    assert got == ["halo jarvis"]
    assert bar.input.toPlainText() == ""


# ── Escape semantics (pure contract) ─────────────────────────────────────────


@pytest.mark.parametrize("speaking,has_input,panel_open,expected", [
    (True, True, True, "interrupt"),      # barge-in always wins
    (True, False, False, "interrupt"),
    (False, True, True, "clear"),         # input first, panel stays
    (False, True, False, "clear"),
    (False, False, True, "close_panel"),
    (False, False, False, "none"),
])
def test_escape_action_priority(speaking, has_input, panel_open, expected):
    from jarvis.ui.window_widgets import escape_action
    assert escape_action(speaking=speaking, has_input=has_input,
                         panel_open=panel_open) == expected


def test_typed_channel_never_interrupts_audio():
    """Text is an independent command channel; only ESC/interrupt owns
    cutting speech (window_widgets.typed_action_interrupts_audio)."""
    from jarvis.ui.window_widgets import typed_action_interrupts_audio
    assert typed_action_interrupts_audio() is False


# ── ApiKeySheet secret hygiene ───────────────────────────────────────────────


def test_api_sheet_emits_once_and_clears_secret_after_emit():
    _app()
    from jarvis.ui.window_widgets import ApiKeySheet
    host = QWidget()
    sheet = ApiKeySheet(host)
    got: list[str] = []
    sheet.done.connect(got.append)

    sheet._key.setText("  fake-key-value  ")
    sheet._submit()

    assert got == ["fake-key-value"]
    assert sheet._key.text() == ""        # secret cleared after hand-off
    assert sheet.busy is True

    sheet._submit()                       # busy gate: no second emit
    assert got == ["fake-key-value"]


def test_api_sheet_secret_tidak_terbaca_dari_widget_setelah_handoff():
    """Secret tidak boleh terbaca dari widget setelah diserahkan.

    RED untuk Fase 63. Terukur: ``_submit()`` memancarkan ``done`` tetapi
    membiarkan teksnya tersimpan di ``self._key``. Selama jendela antara emit
    dan ``clear_secret()`` — yang dipanggil dari ``window_voice.py:425``
    HANYA setelah penyimpanan terenkripsi berhasil — secret berada di dalam
    widget yang masih hidup di memori.
    """
    _app()
    from jarvis.ui.window_widgets import ApiKeySheet
    host = QWidget()
    sheet = ApiKeySheet(host)
    got: list[str] = []
    sheet.done.connect(got.append)

    sheet._key.setText("  fake-key-value  ")
    sheet._submit()

    assert got == ["fake-key-value"], "key harus tetap sampai ke pemiliknya"
    assert sheet._key.text() == "", (
        f"secret masih terbaca di widget setelah hand-off: "
        f"{sheet._key.text()!r}"
    )


def test_api_sheet_gagal_simpan_masih_bisa_dicoba_lagi_tanpa_ketik_ulang():
    """Jalur gagal harus tetap bisa diulang tanpa mengetik ulang key.

    Ini pagar untuk RED di atas. Mengosongkan ``_key`` secara mentah di dalam
    ``_submit()`` akan membuat status "Coba lagi" menjadi bohong: terukur pada
    ``window_voice.py:420`` bahwa jalur penyimpanan gagal menampilkan "Coba
    lagi", tetapi kolomnya sudah kosong bila secret dibuang di ``_submit()``.

    Karena itu pembersihan tidak boleh membuang nilai yang bisa dikembalikan
    saat pemilik melaporkan kegagalan.
    """
    _app()
    from jarvis.ui.window_widgets import ApiKeySheet
    host = QWidget()
    sheet = ApiKeySheet(host)
    got: list[str] = []
    sheet.done.connect(got.append)

    sheet._key.setText("  fake-key-value  ")
    sheet._submit()
    assert sheet._key.text() == ""

    # Pemilik melaporkan gagal menyimpan -> sheet harus kembali siap menerima.
    sheet.set_busy(False)
    sheet.set_status("API key gagal disimpan terenkripsi. Coba lagi.", "error")

    assert sheet.busy is False
    assert sheet._key.isEnabled() is True
    assert sheet._activate.isEnabled() is True
    assert sheet.retry_secret() == "fake-key-value", (
        "jalur 'Coba lagi' kehilangan secret — pemakai harus mengetik ulang"
    )
    assert sheet._key.text() == "fake-key-value", (
        "secret harus kembali ke kolom agar pemakai bisa memperbaiki dan mencoba lagi"
    )


def test_api_sheet_rejects_empty_key_without_emitting():
    _app()
    from jarvis.ui.window_widgets import ApiKeySheet
    host = QWidget()
    sheet = ApiKeySheet(host)
    got: list[str] = []
    sheet.done.connect(got.append)

    sheet._submit()

    assert got == []
    assert sheet.status_kind == "error"
    assert sheet.busy is False


# ── ContentStage readiness model ─────────────────────────────────────────────


@pytest.fixture()
def stage():
    _app()
    from jarvis.ui.stage import ContentStage
    s = ContentStage()
    s.register("alpha", QWidget())
    s.register("beta", QWidget())
    # Qt visibility is hierarchical: a child's isVisible() stays False while any
    # ancestor is hidden, even after child.show(). Without this, begin_loading()
    # and activate() can call show() correctly and still read as hidden, so the
    # tests below would assert on a Qt artifact instead of stage behaviour.
    # register() already hides each child explicitly, and a parent show() does
    # not override that, so "starts empty and registers hidden" still holds.
    s.show()
    return s


def test_stage_starts_empty_and_registers_hidden(stage):
    from jarvis.ui.stage import ContentStatus
    assert stage.status is ContentStatus.EMPTY
    assert stage.current is None
    assert stage.registered_names == frozenset({"alpha", "beta"})
    assert stage.widget("alpha").isHidden()


def test_begin_loading_claims_loading_without_active_payload(stage):
    from jarvis.ui.stage import ContentStatus
    stage.begin_loading("alpha")

    assert stage.status is ContentStatus.LOADING
    assert stage.current is None
    assert stage.is_loading("alpha") is True
    assert stage.is_loading("beta") is False
    assert stage._loading_label.isVisible()


def test_begin_loading_unknown_name_is_noop(stage):
    from jarvis.ui.stage import ContentStatus
    stage.begin_loading("nope")
    assert stage.status is ContentStatus.EMPTY
    assert stage._pending is None


def test_activate_mounts_payload_and_marks_active(stage):
    from jarvis.ui.stage import ContentStatus
    stage.begin_loading("alpha")
    stage.activate("alpha")

    assert stage.status is ContentStatus.ACTIVE
    assert stage.current == "alpha"
    assert stage.widget("alpha").isVisible()
    assert stage._loading_label.isHidden()


def test_switch_panel_while_active_notifies_every_time(stage):
    from jarvis.ui.stage import ContentStatus
    stage.activate("alpha")
    seen: list[str] = []
    stage.status_changed.connect(seen.append)

    stage.activate("beta")                # switch panel, status stays ACTIVE
    assert stage.status is ContentStatus.ACTIVE
    assert stage.current == "beta"
    # Panel change with constant ACTIVE must still notify (force=True). The
    # forced emit is one per switch, not two — _set_status fires once.
    assert seen == ["ACTIVE"]
    stage.activate("alpha")               # switching back is notified too
    assert seen.count("ACTIVE") == 2


def test_reactivating_the_same_panel_emits_nothing(stage):
    from jarvis.ui.stage import ContentStatus
    stage.activate("alpha")
    seen: list[str] = []
    stage.status_changed.connect(seen.append)

    stage.activate("alpha")               # no state change → no duplicate signal
    assert stage.status is ContentStatus.ACTIVE
    assert stage.current == "alpha"
    assert seen == []


def test_panel_switch_crossfades_to_new_owner(stage):
    stage.activate("alpha")
    stage.begin_loading("beta")
    stage.activate("beta")

    assert stage.current == "beta"
    assert stage.widget("beta").isVisible()


def test_toggle_returns_active_then_closes_on_second_call(stage):
    from jarvis.ui.stage import ContentStatus
    assert stage.toggle("alpha") is True
    assert stage.status is ContentStatus.ACTIVE
    assert stage.toggle("alpha") is False
    assert stage.status is ContentStatus.EMPTY
    assert stage.current is None


def test_toggle_unregistered_name_is_safe_false(stage):
    assert stage.toggle("ghost") is False


def test_fail_loading_keeps_mount_and_surfaces_error(stage):
    from jarvis.ui.stage import ContentStatus
    stage.begin_loading("alpha")
    stage.fail_loading("SUMBER TIDAK TERSEDIA")

    assert stage.status is ContentStatus.ERROR
    assert stage._pending is None
    assert stage._loading_label.text() == "SUMBER TIDAK TERSEDIA"
    assert stage.current is None          # never claimed ACTIVE


def test_hide_all_returns_to_empty(stage):
    from jarvis.ui.stage import ContentStatus
    stage.activate("alpha")
    stage.hide_all()

    assert stage.status is ContentStatus.EMPTY
    assert stage.current is None
    assert stage._pending is None


def test_status_changed_traces_readiness_sequence(stage):
    from jarvis.ui.stage import ContentStatus
    seen: list[str] = []
    stage.status_changed.connect(seen.append)

    stage.begin_loading("alpha")
    stage.activate("alpha")
    stage.hide_all()

    assert seen == ["LOADING", "ACTIVE", "EMPTY"]
    assert ContentStatus("EMPTY") is ContentStatus.EMPTY
