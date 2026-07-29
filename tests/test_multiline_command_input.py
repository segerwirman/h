"""PROMPT O — multiline CLI input contract."""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope="module", autouse=True)
def qapp():
    return QApplication.instance() or QApplication([])


def _key(widget, key, modifiers=Qt.KeyboardModifier.NoModifier):
    QApplication.sendEvent(widget, QKeyEvent(QKeyEvent.Type.KeyPress, key, modifiers))


def test_window_imports_runtime_dependencies():
    import jarvis.ui.window as window

    assert window.NotificationBlipStack.__name__ == "NotificationBlipStack"
    assert window.ExecutionTier.__name__ == "Tier"


def test_multiline_input_enter_submits_shift_enter_inserts_newline():
    from jarvis.ui.window import _CliTextEdit

    widget = _CliTextEdit()
    submitted = []
    widget.submitted.connect(submitted.append)
    widget.setPlainText("baris satu")

    _key(widget, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert "\n" in widget.toPlainText()
    _key(widget, Qt.Key.Key_Return)

    assert submitted == ["baris satu"]


def test_multiline_input_caps_height_and_enables_scrollbar():
    from jarvis.ui.window import _CliTextEdit

    widget = _CliTextEdit()
    widget.setPlainText("\n".join(f"baris {i}" for i in range(12)))
    widget._sync_height()

    assert widget.height() >= widget._max_height()
    assert widget.verticalScrollBarPolicy() == Qt.ScrollBarPolicy.ScrollBarAsNeeded


def test_multiline_input_exposes_focus_changed_signal():
    from jarvis.ui.window import _CliTextEdit

    widget = _CliTextEdit()
    states = []
    widget.focus_changed.connect(states.append)
    widget.show()
    widget.setFocus()
    QApplication.processEvents()

    assert states == [True]


def test_slash_first_character_requests_palette():
    from jarvis.ui.window import _CliTextEdit

    widget = _CliTextEdit()
    opened = []
    widget.palette_requested.connect(opened.append)

    _key(widget, Qt.Key.Key_Slash)

    assert opened == [""]


def test_tab_accepts_predictive_ghost_text():
    from jarvis.ui.window import _CliTextEdit

    widget = _CliTextEdit()
    widget.setPlainText("buka")
    widget.set_ghost(" spotify")
    _key(widget, Qt.Key.Key_Tab)

    assert widget.toPlainText() == "buka spotify"


def test_model_indicator_uses_active_light_role_not_hardcoded(monkeypatch):
    from jarvis.ui.window import model_indicator_text
    from jarvis.agent import model_routing

    monkeypatch.setattr(model_routing, "role_statuses", lambda: {
        "light": {"model": "model-nyata", "role": "light"},
    })

    assert model_indicator_text() == "model-nyata · Light"


def test_palette_entities_come_from_action_registry(monkeypatch):
    from jarvis.ui.window import palette_entities
    from jarvis.core import action_registry

    class Registry:
        def all_entities(self):
            return ["Spotify", "kamera"]

    monkeypatch.setattr(action_registry, "default_registry", lambda: Registry())

    assert palette_entities() == ["Spotify", "kamera"]


def test_escape_priority_speaking_before_input_clear():
    from jarvis.ui.window import escape_action

    assert escape_action(speaking=True, has_input=True, panel_open=True) == "interrupt"
    assert escape_action(speaking=False, has_input=True, panel_open=True) == "clear"
    assert escape_action(speaking=False, has_input=False, panel_open=True) == "close_panel"
    assert escape_action(speaking=False, has_input=False, panel_open=False) == "none"


def test_explicit_prefix_resolves_l0_without_clarify(monkeypatch):
    from jarvis.ui.window import resolve_typed_action
    from jarvis.core import action_registry
    from jarvis.core.app_registry import AppMatch

    class Registry(action_registry.ActionRegistry):
        pass

    registry = Registry()
    registry._add("spotify", action_registry.Action("app", "spotify", "open", {"app": "Spotify"}))
    outcome = resolve_typed_action("/open spotify", registry=registry)

    assert outcome.target == "spotify"
    assert outcome.source == "L0"


def test_conversational_spotify_falls_open():
    from jarvis.ui.window import resolve_typed_action
    from jarvis.core.resolver import FallthroughToLLM

    assert isinstance(resolve_typed_action("gimana cara pakai spotify"), FallthroughToLLM)


def test_typed_unsupported_panel_falls_open_to_llm_callback():
    from jarvis.ui.window import route_typed_resolution
    from jarvis.core.action_registry import Action

    calls = []
    route_typed_resolution(
        Action("panel", "kamera", "open", {"panel": "kamera"}),
        "/panel kamera",
        execute=lambda _action: None,
        fall_open=lambda text: calls.append(text),
        clarify=lambda _outcome: None,
    )

    assert calls == ["/panel kamera"]


def test_typed_l1_action_executes_without_llm_callback():
    from jarvis.ui.window import route_typed_resolution
    from jarvis.core.action_registry import Action

    executed, fallback = [], []
    route_typed_resolution(
        Action("app", "spotify", "open", {"app": "Spotify"}),
        "buka spotify",
        execute=lambda action: executed.append(action) or "Membuka Spotify.",
        fall_open=fallback.append,
        clarify=lambda _outcome: None,
    )

    assert [action.target for action in executed] == ["spotify"]
    assert fallback == []
