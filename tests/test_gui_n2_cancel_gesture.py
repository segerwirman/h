"""N-2 (audit 2026-08-24) — gestur pembatalan task dari UI.

Sebelumnya hanya Telegram yang bisa memanggil ``dispatch.cancel_all()``
(telegram.py:394); user mouse/touch tidak punya jalan keluar. Test ini
membekukan kontrak baru: ikon ``cancel`` di ActionPanel, signal
``cancel_clicked``, dan wiring MainWindow ke ``dispatch.cancel_all()``.

Semua offline: QT_QPA_PLATFORM=offscreen, EmbeddedBrowser di-stub, dispatch
dimonkeypatch — tidak ada browser/network/audio/camera/provider. Panel
terisolasi dipakai untuk kontrak signal (klik tidak boleh menyentuh router
nyata), persis pola test_gui_p5c_action_focus_confirm.py.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


class _StubBrowser(QWidget):
    """EmbeddedBrowser stand-in (pola test_window_integration.py)."""
    NO_FX = True

    def navigate(self, url: str, extract: bool = True) -> None:
        pass


# ── Kontrak ikon + signal (panel terisolasi) ─────────────────────────────────


@pytest.fixture()
def panel():
    """ISOLATED ActionPanel — klik hanya menyentuh perekam lokal."""
    _app()
    from jarvis.ui.actionpanel import ActionPanel
    host = QWidget()
    p = ActionPanel(host)
    yield p
    host.close()


def test_cancel_registered_in_icons_dict_with_alert_glyph():
    """Registry ikon tahu tentang cancel: glyph ⏹ + tooltip pembatalan."""
    from jarvis.ui.actionpanel import _ICONS
    assert "cancel" in _ICONS
    glyph, tip = _ICONS["cancel"]
    assert glyph == "⏹"
    assert "batalkan" in tip.lower()


def test_cancel_listed_in_config_icons():
    """config.yaml action_panel.icons menyertakan cancel — tanpanya tombol
    tidak pernah dibangun (konfigurasi adalah sumber kebenaran panel)."""
    from jarvis.core import config
    icons = list(config.get("action_panel.icons", []))
    assert "cancel" in icons


def test_cancel_button_installed_and_owns_signal(panel):
    """Panel nyata (config asli) memasang tombol cancel dan signalnya."""
    assert "cancel" in panel._buttons
    assert hasattr(panel, "cancel_clicked")


def test_cancel_click_emits_exactly_its_own_signal(panel):
    """Satu klik cancel → hanya cancel_clicked yang menyala, sekali."""
    names = [n for n in panel._buttons if n != "tasks"]
    hits = {n: 0 for n in names}
    for n in names:
        getattr(panel, f"{n}_clicked").connect(
            lambda n=n: hits.__setitem__(n, hits[n] + 1))
    panel._buttons["cancel"].click()
    assert hits == {n: (1 if n == "cancel" else 0) for n in names}


def test_cancel_button_styled_with_alert_color(panel):
    """Tombol cancel merah (theme.PAL.alert) — pembeda darurat dari ikon lain."""
    from jarvis.ui import theme
    style = panel._buttons["cancel"].styleSheet()
    assert str(theme.PAL.alert) in style


# ── Wiring MainWindow → dispatch.cancel_all ──────────────────────────────────


@pytest.fixture()
def ui(monkeypatch):
    """Facade penuh; EmbeddedBrowser stub + FocusMode reset (pola p5c)."""
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


def test_window_click_cancel_calls_dispatch_cancel_all(win, monkeypatch):
    """Klik tombol cancel di window nyata memanggil dispatch.cancel_all()."""
    from jarvis.agent import dispatch
    calls = []
    monkeypatch.setattr(dispatch, "cancel_all",
                        lambda: calls.append(1) or 2)
    win.action_panel._buttons["cancel"].click()
    _app().processEvents()
    assert calls == [1]


def test_cancel_handler_reports_count_and_zero_case(win, monkeypatch):
    """Handler jujur: jumlah dibatalkan vs 'tidak ada tugas' — lewat
    write_log yang direkam (panggilan asli tetap jalan)."""
    from jarvis.agent import dispatch
    logs: list[str] = []
    real_write_log = win.write_log

    def spy(text: str) -> None:
        logs.append(str(text))
        real_write_log(text)

    monkeypatch.setattr(win, "write_log", spy)

    monkeypatch.setattr(dispatch, "cancel_all", lambda: 3)
    win._on_cancel_tasks_clicked()
    assert any("3" in line and "dibatalkan" in line for line in logs)

    logs.clear()
    monkeypatch.setattr(dispatch, "cancel_all", lambda: 0)
    win._on_cancel_tasks_clicked()
    assert any("tidak ada tugas" in line.lower() for line in logs)


def test_cancel_handler_survives_dispatch_failure(win, monkeypatch):
    """Dispatch meledak pun tombol tidak boleh menjatuhkan UI thread."""
    from jarvis.agent import dispatch

    def boom() -> int:
        raise RuntimeError("dispatch offline")

    monkeypatch.setattr(dispatch, "cancel_all", boom)
    # Tidak boleh raise — kegagalan dilaporkan, UI tetap hidup.
    win._on_cancel_tasks_clicked()
