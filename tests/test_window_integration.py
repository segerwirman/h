"""MainWindow integration tests for the redesign's P1 wiring.

The existing P0 suite (tests/test_xlix_p0.py) deliberately never
instantiates MainWindow — it tests OrbRenderer/ContentStage/CameraButton in
isolation via `presentation_snapshot()`, the documented "deterministic test
seam." Full MainWindow construction pulls in `EmbeddedBrowser`
(QWebEngineView), whose Chromium subprocess cannot even initialize a
`QWebEngineProfile` on this dev machine — confirmed unrelated to any code
in this repo (a bare custom-painted QWidget also crashes on real paint
dispatch here under QT_QPA_PLATFORM=offscreen). These tests follow the
same "no real event-loop/paint dispatch" discipline the existing suite
already uses, and additionally substitute a stub for EmbeddedBrowser so
the unrelated WebEngine crash never enters the picture. `BUS.drain_ui()` is
called explicitly to simulate the 30 ms drain timer MainWindow installs
in the real running app (there's no Qt event loop pumping it here).
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QApplication, QWidget

from jarvis.core.bus import BUS
from jarvis.core.focus_mode import FocusMode
from jarvis.core.target_resolver import CloseResult, TargetResolver, WindowAdapter, WindowInfo

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def _drain_bus() -> None:
    """In the real app a 30 ms QTimer drains the BUS continuously; here no
    event loop runs between tests, so the shared UI queue accumulates log
    events session-wide. One drain_ui() call caps at 64 events — drain until
    genuinely empty so this test's own event is always dispatched."""
    while not BUS._ui_queue.empty():
        BUS.drain_ui()


class _StubBrowser(QWidget):
    """EmbeddedBrowser stand-in — the real one needs a working QtWebEngine
    Chromium runtime, unavailable in this environment (see module docstring)."""
    content_ready = pyqtSignal(str, str)
    display_ready = pyqtSignal(bool)
    NO_FX = True

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._url = ""

    def navigate(self, url: str, extract: bool = True) -> None:
        self._url = url

    def play_embed(self, url: str) -> None:
        self._url = url

    def current_url(self) -> str:
        return self._url


class _StubAgent(QWidget):
    """Browser-agent stand-in with the surface take-over routing depends on."""
    display_ready = pyqtSignal(bool)
    status = pyqtSignal(str)
    NO_FX = True

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self._embedded = True
        self.navigated: list[str] = []
        self.opened = 0
        self._cdp = 9333            # embedded Tabbit's remote-debugging port

    def cdp_port(self):
        return self._cdp

    def open(self, url=None):
        self.opened += 1

    def navigate(self, url: str):
        self.navigated.append(url)

    def focus_content(self):
        pass

    def current_url(self):
        return "https://www.youtube.com/watch"

    def shutdown(self):
        self._embedded = False


class _FakeWindowAdapter(WindowAdapter):
    supported = True

    def __init__(self, windows: list[str]):
        self._titles = windows
        self.closed: list[str] = []

    def list_windows(self):
        return [WindowInfo(object(), t) for t in self._titles]

    def foreground_window(self):
        return None

    def close_window(self, win, force=False):
        self.closed.append(win.title)
        return CloseResult(True, "graceful", "ok")


@pytest.fixture()
def win(monkeypatch):
    _app()
    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    FocusMode._reset_for_tests()
    from jarvis.ui.window import MainWindow
    w = MainWindow(services={})
    yield w
    FocusMode._reset_for_tests()


def test_mainwindow_constructs_with_all_new_subsystems(win):
    assert win.notifications is not None
    assert win.command_palette is not None
    assert win.timeline is not None
    assert win._focus_mode is not None
    assert win._target_resolver is not None


def test_boot_default_ke_stage_empty_dan_capabilities_sheet_tersembunyi(win):
    """Register/construct panel tidak boleh sama dengan menampilkannya."""
    from jarvis.ui.stage import ContentStatus

    win.show()
    _app().processEvents()
    assert win.stage.current is None
    assert win.stage.status is ContentStatus.EMPTY
    assert win.capabilities_sheet.isHidden() is True


def test_tiga_boot_default_berurutan_tetap_orb_only(monkeypatch):
    _app()
    import jarvis.browser.embed as embed_mod
    from jarvis.ui.window import MainWindow

    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    windows = [MainWindow(services={}) for _ in range(3)]

    assert all(w.stage.current is None for w in windows)
    assert all(w.capabilities_sheet.isHidden() for w in windows)


def test_startup_panel_vision_hanya_terbuka_bila_config_eksplisit(monkeypatch):
    _app()
    import jarvis.browser.embed as embed_mod
    from jarvis.core import config
    from jarvis.ui.window import MainWindow

    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    original_get = config.get
    monkeypatch.setattr(
        config, "get",
        lambda key, default=None: "vision" if key == "ui.startup.panel"
        else original_get(key, default),
    )
    win = MainWindow(services={})

    assert win.stage.is_loading("vision")
    assert win.stage.current is None
    assert win.capabilities_sheet.isHidden() is True


def test_capabilities_action_opens_local_control_plane_sheet(win):
    win.action_panel._buttons["capabilities"].click()

    assert win.capabilities_sheet.isHidden() is False
    assert win.capabilities_sheet.geometry().width() >= 720


def test_capabilities_sheet_can_be_closed_from_its_own_header(win):
    win.action_panel._buttons["capabilities"].click()

    win.capabilities_sheet._close_button.click()

    assert win.capabilities_sheet.isHidden() is True


def test_orb_is_scoped_to_content_stage_so_header_remains_uncovered(win):
    assert win.orb.parent() is win.stage
    assert win.orb.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_orb_tracks_stage_geometry_after_first_stage_layout(win):
    """A stage resize can arrive after MainWindow's initial resize event."""
    win.stage.resize(741, 389)
    QApplication.instance().processEvents()

    assert win.orb.geometry() == win.stage.rect()


def test_gateway_operations_action_opens_local_control_plane_sheet(win):
    win.action_panel._buttons["gateway_ops"].click()

    assert win.gateway_operations_sheet.isHidden() is False
    assert win.gateway_operations_sheet.geometry().width() >= 720


def test_command_palette_model_has_static_commands(win):
    ids = {c["action_id"] for c in win.command_palette.model._commands}
    assert "go_home" in ids
    assert "toggle_focus_mode" in ids
    assert "reopen_last_tab" in ids


def test_focus_mode_toggle_propagates_to_notifications(win):
    assert win._focus_mode.active is False
    win._toggle_focus_mode()
    assert win._focus_mode.active is True
    assert win.notifications._focus_mode is True
    win._toggle_focus_mode()
    assert win._focus_mode.active is False
    assert win.notifications._focus_mode is False


def test_mute_toggle_propagates_to_notifications(win):
    win.toggle_mute()
    assert win.notifications._muted is True
    win.toggle_mute()
    assert win.notifications._muted is False


def test_close_target_auto_executes_single_high_confidence(win):
    fake = _FakeWindowAdapter(["Notepad"])
    win._target_resolver = TargetResolver(fake)
    win._begin_close_target("Notepad")
    assert win._pending_close_decision is None
    assert fake.closed == ["Notepad"]


def test_close_target_ambiguous_requires_confirm_word(win):
    fake = _FakeWindowAdapter(["Report Draft", "Report Final"])
    win._target_resolver = TargetResolver(fake)
    win._begin_close_target("Report")
    assert win._pending_close_decision is not None
    assert win._pending_close_decision.status == "needs_confirmation"
    assert fake.closed == []

    win.handle_command("confirm")
    _drain_bus()
    assert fake.closed == ["Report Draft"]
    assert win._pending_close_decision is None


def test_close_target_cancel_word_aborts_without_closing(win):
    fake = _FakeWindowAdapter(["Report Draft", "Report Final"])
    win._target_resolver = TargetResolver(fake)
    win._begin_close_target("Report")

    win.handle_command("cancel")
    _drain_bus()
    assert fake.closed == []
    assert win._pending_close_decision is None


def test_close_target_confirmation_via_gesture_bus_topics(win):
    """Thumbs-up/down gesture already publishes confirm/cancel on the BUS
    (jarvis.vision) — this proves the destructive-action gate consumes
    that exact channel, giving the gesture a real purpose."""
    fake = _FakeWindowAdapter(["Report Draft", "Report Final"])
    win._target_resolver = TargetResolver(fake)
    win._begin_close_target("Report")
    assert win._pending_close_decision is not None

    win._on_gesture({"gesture": "THUMBS_UP"})
    _drain_bus()
    assert len(fake.closed) == 1


def test_no_target_found_does_not_create_pending_confirmation(win):
    fake = _FakeWindowAdapter([])
    win._target_resolver = TargetResolver(fake)
    win._begin_close_target("Nonexistent App XYZ")
    assert win._pending_close_decision is None
    assert fake.closed == []


# MK50 §7 — panel browser dibuang; 'reopen tab' embedded ikut pensiun.
def test_reopen_last_tab_with_nothing_closed_is_a_safe_noop(win):
    win._reopen_last_tab()   # must not raise


def test_sentiment_feed_reaches_orb(win):
    win._on_sentiment({"value": 0.6})
    assert win.orb._sentiment_target == pytest.approx(0.6)


def test_awareness_toggle_is_explicit_opt_in_and_lights_indicator(win):
    # Clicking the icon is itself an explicit opt-in, so awareness starts even
    # though awareness.enabled defaults to false (that flag only gates boot-time
    # auto-start). The panel lamp must light while it is actively capturing.
    from jarvis.core import screen_awareness
    screen_awareness._instance = None
    win._toggle_awareness()
    aw = screen_awareness.get()
    try:
        assert aw.running is True
        assert win.action_panel._buttons["awareness"]._active is True
        win._toggle_awareness()                 # second click → pause, lamp off
        assert aw.paused is True
        assert win.action_panel._buttons["awareness"]._active is False
    finally:
        aw.stop()


def test_focus_mode_toggle_lights_indicator(win):
    from jarvis.core.focus_mode import FocusMode
    FocusMode._reset_for_tests()
    win._toggle_focus_mode()
    assert win.action_panel._buttons["focus_mode"]._active is True
    win._toggle_focus_mode()
    assert win.action_panel._buttons["focus_mode"]._active is False
    FocusMode._reset_for_tests()


# MK50 §7 — blok test Tabbit/in-frame agent dihapus bersama fiturnya.
def _mount_agent(win):
    """Kompat: panel agent tiada; kembalikan stub tanpa mount."""
    class _A:
        navigated: list = []
    return _A()


def test_home_command_clears_stage_without_agent(win):
    # MK50 §7 — tanpa panel browser: "kembali" tetap membersihkan stage.
    win.stage.register("content_x", QWidget())
    win.stage.show_child("content_x")
    win.handle_command("kembali")
    _drain_bus()
    assert win.stage.current is None


def test_tutup_browser_agent_is_safe_noop(win):
    # Perintah lama tetap aman walau panel agent sudah dipensiunkan.
    win.handle_command("tutup browser agent")
    _drain_bus()
    assert win.stage.current is None


def test_orb_hides_while_camera_owns_stage(win):
    assert win.orb.isHidden() is False
    win._set_vision_visible(True)            # camera opens
    assert win.orb.isHidden() is True        # orb disappears
    win.stage.activate("vision")
    win._on_stage_status("ACTIVE")
    assert win.orb.isHidden() is True
    win._set_vision_visible(False)           # camera closes
    assert win.orb.isHidden() is False       # orb returns


def test_facade_and_hotkeys_still_intact_after_p1_wiring(win):
    # Do-not-regress: the facade contract and F4/F11/Escape hotkeys must
    # survive every P1 addition made in this pass.
    from jarvis.ui.window import JarvisUI
    for name in ("set_state", "write_log", "show_content", "start_camera_stream",
                "stop_camera_stream", "queue_greeting"):
        assert hasattr(JarvisUI, name)
    import inspect
    source = inspect.getsource(win._bind_hotkeys)
    for key in ("mute", "fullscreen", "interrupt"):
        assert f'"hotkeys.{key}"' in source
