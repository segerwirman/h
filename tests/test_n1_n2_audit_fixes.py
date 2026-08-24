"""N-1/N-2 audit fix tests (2026-08-24): speech gate + cancel gesture.

All tests are offline/fake — no browser, no network, no audio, no Gemini Live.
Use ``--basetemp`` outside the repository for real suites.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import threading
import time
import types
from unittest import mock

import pytest
from PyQt6.QtWidgets import QApplication, QWidget


# ═══════════════════════════════════════════════════════════════════════════
# helpers
# ═══════════════════════════════════════════════════════════════════════════


def _make_fake_legacy(busy_factory=None):
    """Build a fake legacy module with a JarvisLive class for gate tests."""
    from jarvis.integrations import voice_speech_gate

    mod = types.ModuleType("fake_legacy_gate")

    class _Live:
        """Minimal Live stub."""

        _is_speaking = False
        audio_in_queue = None         # None = no queue, not empty
        _voice_turn_drained_epoch = 0

        def __init__(self):
            self.calls: list[tuple[tuple, dict]] = []

        def speak(self, text, *args, **kwargs):
            """Original speak the gate wraps."""
            self.calls.append(((text,) + args, kwargs))

    mod.JarvisLive = _Live
    return mod


# ═══════════════════════════════════════════════════════════════════════════
# N-1: voice_speech_gate — test offline
# ═══════════════════════════════════════════════════════════════════════════


def test_gate_install_idempotent(monkeypatch):
    """Install twice → True both times, no double-wrap."""
    from jarvis.integrations import voice_speech_gate

    monkeypatch.setattr(voice_speech_gate, "_logger", mock.MagicMock())
    legacy = _make_fake_legacy()
    assert voice_speech_gate.install(legacy) is True
    assert getattr(legacy.JarvisLive, "_jarvis_speech_gate", False) is True
    assert voice_speech_gate.install(legacy) is True


def test_gate_install_no_class_returns_false(monkeypatch):
    """Legacy module without JarvisLive → safe False."""
    from jarvis.integrations import voice_speech_gate

    monkeypatch.setattr(voice_speech_gate, "_logger", mock.MagicMock())
    mod = types.ModuleType("empty")
    assert voice_speech_gate.install(mod) is False


def test_gate_install_no_speak_returns_false(monkeypatch):
    """JarvisLive without speak method → safe False."""
    from jarvis.integrations import voice_speech_gate

    monkeypatch.setattr(voice_speech_gate, "_logger", mock.MagicMock())
    mod = types.ModuleType("no_speak")

    class _Live:
        pass

    mod.JarvisLive = _Live
    assert voice_speech_gate.install(mod) is False


def test_gate_sends_immediately_when_lane_idle(monkeypatch):
    """Lane idle + boundary safe → original_speak langsung, tidak ditahan."""
    from jarvis.integrations import voice_speech_gate

    monkeypatch.setattr(voice_speech_gate, "_logger", mock.MagicMock())
    monkeypatch.setattr(voice_speech_gate, "_lane_busy", lambda _live: False)
    monkeypatch.setattr(
        voice_speech_gate.voice_speech, "current_delivery_scope",
        lambda: None)
    monkeypatch.setattr(
        voice_speech_gate.voice_speech, "turn_boundary_safe",
        lambda _live: True)

    legacy = _make_fake_legacy()
    voice_speech_gate.install(legacy)
    live = legacy.JarvisLive()

    live.speak("halo")
    assert live.calls == [(("halo",), {})]


def test_gate_holds_when_lane_is_speaking(monkeypatch):
    """Lane sedang bicara → teks ditahan, drainer mengirim setelah idle."""
    from jarvis.integrations import voice_speech_gate

    monkeypatch.setattr(voice_speech_gate, "_logger", mock.MagicMock())

    busy_flag = {"busy": True}

    def _fake_busy(_live):
        return busy_flag["busy"]

    monkeypatch.setattr(voice_speech_gate, "_lane_busy", _fake_busy)
    monkeypatch.setattr(
        voice_speech_gate.voice_speech, "current_delivery_scope",
        lambda: None)
    monkeypatch.setattr(
        voice_speech_gate.voice_speech, "turn_boundary_safe",
        lambda _live: True)

    legacy = _make_fake_legacy()
    voice_speech_gate.install(legacy)
    live = legacy.JarvisLive()

    live.speak("ditahan")
    # Belum dikirim karena busy
    assert live.calls == []

    # Un-busy, drainer harus mengirim
    busy_flag["busy"] = False
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if live.calls:
            break
        time.sleep(0.01)
    assert live.calls == [(("ditahan",), {})]


def test_gate_scope_passthrough(monkeypatch):
    """Ucapan ber-delivery-scope langsung ke original, tanpa gerbang."""
    from jarvis.integrations import voice_speech_gate

    monkeypatch.setattr(voice_speech_gate, "_logger", mock.MagicMock())
    monkeypatch.setattr(
        voice_speech_gate.voice_speech, "current_delivery_scope",
        lambda: "ack")

    legacy = _make_fake_legacy()
    voice_speech_gate.install(legacy)
    live = legacy.JarvisLive()

    live.speak("scoped text")
    assert live.calls == [(("scoped text",), {})]


def test_gate_drain_timeout_sends_anyway(monkeypatch):
    """Batas waktu drain terlampaui → kirim apa adanya, jangan hilang."""
    from jarvis.integrations import voice_speech_gate

    monkeypatch.setattr(voice_speech_gate, "_logger", mock.MagicMock())
    # lane_busy selalu True → drainer akan timeout
    monkeypatch.setattr(voice_speech_gate, "_lane_busy", lambda _live: True)
    monkeypatch.setattr(
        voice_speech_gate.voice_speech, "current_delivery_scope",
        lambda: None)
    monkeypatch.setattr(
        voice_speech_gate.voice_speech, "turn_boundary_safe",
        lambda _live: False)
    # Short timeout so test is fast
    monkeypatch.setattr(voice_speech_gate.config, "get",
                        lambda k, d=None: {
                            "voice.speech_gate.max_hold_s": 0.05,
                            "voice.speech_gate.poll_s": 0.01,
                        }.get(k, d))

    legacy = _make_fake_legacy()
    voice_speech_gate.install(legacy)
    live = legacy.JarvisLive()

    live.speak("timeout-item")
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        if live.calls:
            break
        time.sleep(0.01)
    assert live.calls == [(("timeout-item",), {})]
    # boundary_timeout should have been logged
    assert voice_speech_gate._logger.warning.called


# ═══════════════════════════════════════════════════════════════════════════
# N-2: cancel gesture — test offline
# ═══════════════════════════════════════════════════════════════════════════


def test_cancel_icon_in_config():
    """'cancel' must be in action_panel.icons so the button renders."""
    from jarvis.core import config

    icons = config.get("action_panel.icons", [])
    assert "cancel" in icons, (
        "ikon 'cancel' harus ada di config.yaml action_panel.icons agar "
        "ActionPanel merender tombol pembatalan"
    )


def test_cancel_icon_in_dict():
    """'cancel' must be in the _ICONS dict with glyph + tooltip."""
    from jarvis.ui.actionpanel import _ICONS
    assert "cancel" in _ICONS
    glyph, tooltip = _ICONS["cancel"]
    assert glyph, "cancel harus punya glyph"
    assert "Batalkan" in tooltip or "cancel" in tooltip.lower()


def test_cancel_has_signal():
    """cancel_clicked pyqtSignal must exist on ActionPanel."""
    from jarvis.ui.actionpanel import ActionPanel
    assert hasattr(ActionPanel, "cancel_clicked"), (
        "ActionPanel harus punya cancel_clicked pyqtSignal"
    )


def test_cancel_button_renders_in_panel():
    """When 'cancel' is in config icons, the button is in _buttons."""
    _app = QApplication.instance() or QApplication([])
    host = QWidget()
    from jarvis.ui.actionpanel import ActionPanel
    panel = ActionPanel(host)
    assert "cancel" in panel._buttons, (
        "Tombol cancel harus ada di panel._buttons saat config mencantumkannya"
    )
    host.close()


def test_cancel_button_click_emits_signal():
    """Clicking the cancel button fires cancel_clicked exactly once."""
    _app = QApplication.instance() or QApplication([])
    host = QWidget()
    from jarvis.ui.actionpanel import ActionPanel
    panel = ActionPanel(host)

    hits: list[int] = []
    panel.cancel_clicked.connect(lambda: hits.append(1))

    panel._buttons["cancel"].click()
    assert hits == [1], "cancel button harus emit cancel_clicked 1x"
    host.close()


def test_cancel_button_tooltip_and_accessible_name():
    """Cancel button must have tooltip == accessibleName (P5-C contract)."""
    _app = QApplication.instance() or QApplication([])
    host = QWidget()
    from jarvis.ui.actionpanel import ActionPanel
    panel = ActionPanel(host)

    btn = panel._buttons["cancel"]
    assert btn.toolTip(), "cancel button harus punya tooltip"
    assert btn.accessibleName() == btn.toolTip(), (
        "accessibleName harus sama dengan tooltip (kontrak P5-C)"
    )
    host.close()


def test_cancel_handler_calls_dispatch_cancel_all(monkeypatch):
    """_on_cancel_tasks_clicked memanggil dispatch.cancel_all()."""
    from jarvis.ui.window_actions import CommandActionsMixin

    fake_cancel = mock.MagicMock(return_value=3)
    monkeypatch.setattr(
        "jarvis.agent.dispatch.cancel_all", fake_cancel,
    )

    mixin = CommandActionsMixin()
    mixin.write_log = mock.MagicMock()
    mixin._speak_line = mock.MagicMock()
    mixin.notifications = mock.MagicMock()
    mixin.notifications.push = mock.MagicMock()

    mixin._on_cancel_tasks_clicked()

    fake_cancel.assert_called_once()
    log_lines = [str(c.args[0]) for c in mixin.write_log.call_args_list if c.args]
    assert any("3 tugas" in line for line in log_lines)
    mixin._speak_line.assert_called_once()


def test_cancel_handler_no_tasks(monkeypatch):
    """Saat tidak ada task berjalan, handler tetap berfungsi."""
    from jarvis.ui.window_actions import CommandActionsMixin

    fake_cancel = mock.MagicMock(return_value=0)
    monkeypatch.setattr(
        "jarvis.agent.dispatch.cancel_all", fake_cancel,
    )

    mixin = CommandActionsMixin()
    mixin.write_log = mock.MagicMock()
    mixin._speak_line = mock.MagicMock()
    mixin.notifications = mock.MagicMock()
    mixin.notifications.push = mock.MagicMock()

    mixin._on_cancel_tasks_clicked()

    fake_cancel.assert_called_once()


def test_cancel_handler_dispatch_exception_is_caught(monkeypatch):
    """Jika dispatch.cancel_all() melempar, handler menangkap dan mencatat."""
    from jarvis.ui.window_actions import CommandActionsMixin

    fake_cancel = mock.MagicMock(side_effect=RuntimeError("dispatch down"))
    monkeypatch.setattr(
        "jarvis.agent.dispatch.cancel_all", fake_cancel,
    )

    mixin = CommandActionsMixin()
    mixin.write_log = mock.MagicMock()
    mixin._speak_line = mock.MagicMock()
    mixin.notifications = mock.MagicMock()
    mixin.notifications.push = mock.MagicMock()

    # Must not raise
    mixin._on_cancel_tasks_clicked()

    fake_cancel.assert_called_once()
    log_lines = [str(c.args[0]) for c in mixin.write_log.call_args_list if c.args]
    assert any("ERR" in line or "gagal" in line for line in log_lines)
    mixin._speak_line.assert_not_called()