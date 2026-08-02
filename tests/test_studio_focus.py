"""Studio C local stage toggle and reversible Focus Mode contract."""
from __future__ import annotations

class _Stage:
    def __init__(self):
        self.current = None
        self.calls = []
    def toggle(self, name):
        self.calls.append(name)
        if self.current == name:
            self.current = None
            return False
        self.current = name
        return True

class _Focus:
    def __init__(self, active=False):
        self.active = active
        self.calls = []
    def activate(self): self.active = True; self.calls.append("activate")
    def deactivate(self): self.active = False; self.calls.append("deactivate")

def test_studio_action_opens_only_studio_and_restores_preexisting_focus_on_close():
    from jarvis.ui.studio_focus import StudioFocusController

    stage, focus = _Stage(), _Focus(active=True)
    controller = StudioFocusController(stage, focus)
    assert controller.toggle() is True
    assert stage.current == "studio"
    assert focus.active is True and focus.calls == []
    assert controller.toggle() is False
    assert stage.current is None
    assert focus.active is True and focus.calls == []

def test_studio_focus_control_restores_prior_off_state_when_studio_closes():
    from jarvis.ui.studio_focus import StudioFocusController

    stage, focus = _Stage(), _Focus(active=False)
    controller = StudioFocusController(stage, focus)
    controller.toggle()
    assert controller.set_studio_focus(True) is True
    assert focus.active is True and focus.calls == ["activate"]
    assert controller.toggle() is False
    assert focus.active is False and focus.calls == ["activate", "deactivate"]

def test_sheet_focus_button_emits_only_requested_boolean():
    import os
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from jarvis.ui.content_studio import ContentStudioSheet

    sheet = ContentStudioSheet()
    requested = []
    sheet.studio_focus_requested.connect(requested.append)
    sheet._toggle_studio_focus()
    assert requested == [True]
    sheet.set_studio_focus_active(True)
    sheet._toggle_studio_focus()
    assert requested == [True, False]
    assert app is not None

def test_focus_control_is_denied_when_studio_is_not_open():
    from jarvis.ui.studio_focus import StudioFocusController

    focus = _Focus()
    controller = StudioFocusController(_Stage(), focus)
    assert controller.set_studio_focus(True) is False
    assert focus.calls == []
