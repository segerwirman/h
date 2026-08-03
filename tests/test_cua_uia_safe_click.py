"""Narrow real-backend seam: UIA capture + leased semantic left click."""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.core.element_model import ElementScope


@dataclass
class _Rect:
    left: int
    top: int
    right: int
    bottom: int


class _Control:
    def __init__(self, *, handle=12, title="Demo", text="Next", kind="Button",
                 rect=_Rect(10, 20, 110, 60), visible=True, enabled=True, dialog=False,
                 runtime_id=(12, 1)):
        self.handle = handle
        self._title = title
        self._text = text
        self._kind = kind
        self._rect = rect
        self._visible = visible
        self._enabled = enabled
        self.element_info = type("Info", (), {
            "control_type": kind,
            "is_dialog": dialog,
            "runtime_id": runtime_id,
        })()

    def window_text(self): return self._text
    def friendly_class_name(self): return self._kind
    def rectangle(self): return self._rect
    def is_visible(self): return self._visible
    def is_enabled(self): return self._enabled
    def descendants(self): return []


class _Window(_Control):
    def __init__(self, *children, **kwargs):
        super().__init__(**kwargs)
        self._children = list(children)

    def descendants(self): return list(self._children)


class _Desktop:
    def __init__(self, window): self.window = window
    def get_active(self): return self.window


def test_uia_backend_normalizes_foreground_window_to_semantic_frame():
    from jarvis.automation.uia_capture import UIACaptureBackend

    backend = UIACaptureBackend(desktop=_Desktop(_Window(
        _Control(text="Next", kind="Button"),
        title="Demo", text="Demo",
    )))

    frame = backend.capture()
    element = frame.tree.by_scope(ElementScope.PAGE_MAIN)[0]

    assert frame.surface_id == "uia:12"
    assert frame.privacy == "normal"
    assert element.name == "Next"
    assert element.role == "button"
    assert element.rect == (10, 20, 100, 40)
    assert element.provenance == "uia"


def test_uia_backend_bounds_descendants_before_semantic_normalization():
    from jarvis.automation.uia_capture import UIACaptureBackend

    backend = UIACaptureBackend(desktop=_Desktop(_Window(
        *[_Control(text=f"Action {index}", kind="Button") for index in range(5)],
        title="Demo", text="Demo",
    )), max_elements=2)

    frame = backend.capture()

    assert len(frame.tree.by_scope(ElementScope.PAGE_MAIN)) == 2


def test_uia_scope_mapping_separates_window_chrome_dialog_and_page_main():
    from jarvis.automation.uia_capture import UIACaptureBackend

    backend = UIACaptureBackend(desktop=_Desktop(_Window(
        _Control(text="Minimize", kind="Button", rect=_Rect(950, 5, 980, 30)),
        _Control(text="Cancel", kind="Button", rect=_Rect(200, 150, 280, 180), dialog=True),
        _Control(text="Next", kind="Button", rect=_Rect(100, 300, 180, 330)),
        title="Demo", text="Demo",
    )))

    frame = backend.capture()

    by_name = {element.name: element.scope for scope in frame.tree.scopes()
               for element in frame.tree.by_scope(scope)}
    assert by_name["Minimize"] is ElementScope.WINDOW_CHROME
    assert by_name["Cancel"] is ElementScope.PAGE_DIALOG
    assert by_name["Next"] is ElementScope.PAGE_MAIN


def test_uia_scope_mapping_uses_explicit_uia_browser_or_composer_evidence_only():
    from jarvis.automation.uia_capture import _scope_for

    def control(kind, automation_id="", class_name=""):
        return type("C", (), {"element_info": type("I", (), {
            "is_dialog": False, "control_type": kind,
            "automation_id": automation_id, "class_name": class_name,
        })()})()

    assert _scope_for(control("TabItem", class_name="Chrome_WidgetWin"), 10, 10) is ElementScope.BROWSER_TAB_STRIP
    assert _scope_for(control("Edit", automation_id="address and search bar", class_name="Chrome_Omnibox"), 10, 70) is ElementScope.BROWSER_ADDRESS
    assert _scope_for(control("Button", automation_id="Back", class_name="Chrome_Toolbar"), 10, 70) is ElementScope.BROWSER_NAV
    assert _scope_for(control("Edit", automation_id="message-composer"), 10, 200) is ElementScope.PAGE_COMPOSER
    assert _scope_for(control("TabItem", class_name="GenericApp"), 10, 10) is ElementScope.PAGE_MAIN


def test_uia_scrollbar_exposes_range_value_as_deterministic_state_marker():
    from jarvis.automation.uia_capture import _element_from_control

    control = _Control(kind="ScrollBar")
    control.iface_range_value = type("Range", (), {"CurrentValue": 42.5})()

    element = _element_from_control(control, 1)

    assert element.role == "scrollbar"
    assert element.states["position"] == 42.5


def test_uia_slider_exposes_complete_bounded_range_value_state():
    from jarvis.automation.uia_capture import _element_from_control

    control = _Control(kind="Slider")
    control.iface_range_value = type("Range", (), {
        "CurrentValue": 25.0, "Minimum": 0.0, "Maximum": 100.0,
    })()

    element = _element_from_control(control, 1)

    assert element.role == "slider"
    assert element.states["value"] == 25.0
    assert element.states["minimum"] == 0.0
    assert element.states["maximum"] == 100.0


def test_uia_slider_accepts_native_range_value_current_bound_names():
    from jarvis.automation.uia_capture import _element_from_control

    control = _Control(kind="Slider")
    control.iface_range_value = type("Range", (), {
        "CurrentValue": 25.0, "CurrentMinimum": 0.0, "CurrentMaximum": 100.0,
    })()

    element = _element_from_control(control, 1)

    assert element.states == {
        "disabled": False, "value": 25.0, "minimum": 0.0, "maximum": 100.0,
        "_uia_runtime_id": "12.1",
    }


def test_uia_slider_without_complete_range_value_is_not_actionable():
    from jarvis.automation.uia_capture import _element_from_control

    control = _Control(kind="Slider")
    control.iface_range_value = type("Range", (), {"CurrentValue": 25.0})()

    assert _element_from_control(control, 1) is None


def test_uia_slider_with_non_finite_range_is_not_actionable():
    from jarvis.automation.uia_capture import _element_from_control

    control = _Control(kind="Slider")
    control.iface_range_value = type("Range", (), {
        "CurrentValue": float("inf"), "CurrentMinimum": float("inf"),
        "CurrentMaximum": float("inf"),
    })()

    assert _element_from_control(control, 1) is None


def test_uia_backend_rejects_replaced_button_before_native_click():
    import pytest

    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    original = _Control(kind="Button", runtime_id=(12, 101))
    replacement = _Control(kind="Button", runtime_id=(12, 202))
    desktop = _Desktop(_Window(original, title="Demo", text="Demo"))
    calls = []
    backend = UIACaptureBackend(
        desktop=desktop,
        driver=type("Driver", (), {"click": lambda _, *args, **kwargs: calls.append(args)})(),
    )
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")
    desktop.window = _Window(replacement, title="Demo", text="Demo")

    with pytest.raises(RuntimeError, match="identitas"):
        backend.click_semantic(ref)

    assert calls == []


def test_uia_backend_rejects_replaced_scrollbar_before_native_scroll():
    import pytest

    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    def scrollbar(runtime_id):
        control = _Control(kind="ScrollBar", runtime_id=runtime_id)
        control.iface_range_value = type("Range", (), {"CurrentValue": 20.0})()
        return control

    original = scrollbar((12, 101))
    replacement = scrollbar((12, 202))
    desktop = _Desktop(_Window(original, title="Demo", text="Demo"))
    calls = []
    backend = UIACaptureBackend(
        desktop=desktop,
        driver=type("Driver", (), {"scroll": lambda _, *args: calls.append(args)})(),
    )
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")
    desktop.window = _Window(replacement, title="Demo", text="Demo")

    with pytest.raises(RuntimeError, match="identitas"):
        backend.scroll_semantic(ref, -3)

    assert calls == []


def test_uia_backend_sets_slider_only_from_matching_semantic_ref():
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    slider = _Control(kind="Slider")
    slider.iface_range_value = type("Range", (), {
        "CurrentValue": 25.0, "Minimum": 0.0, "Maximum": 100.0,
        "SetValue": lambda self, value: setattr(self, "CurrentValue", float(value)),
    })()
    backend = UIACaptureBackend(desktop=_Desktop(_Window(slider, title="Demo", text="Demo")))
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")

    backend.set_slider_value(ref, 30.0)

    assert slider.iface_range_value.CurrentValue == 30.0


def test_uia_backend_rechecks_current_slider_range_before_set_value():
    import pytest

    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    slider = _Control(kind="Slider")
    slider.iface_range_value = type("Range", (), {
        "CurrentValue": 25.0, "CurrentMinimum": 0.0, "CurrentMaximum": 100.0,
        "SetValue": lambda self, value: setattr(self, "CurrentValue", float(value)),
    })()
    backend = UIACaptureBackend(desktop=_Desktop(_Window(slider, title="Demo", text="Demo")))
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")
    slider.iface_range_value.CurrentValue = 10.0
    slider.iface_range_value.CurrentMaximum = 20.0

    with pytest.raises(RuntimeError, match="rentang"):
        backend.set_slider_value(ref, 30.0)

    assert slider.iface_range_value.CurrentValue == 10.0


def test_uia_backend_rejects_replaced_slider_with_same_index_rect_and_surface():
    import pytest

    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    def slider(runtime_id):
        control = _Control(kind="Slider", runtime_id=runtime_id)
        control.iface_range_value = type("Range", (), {
            "CurrentValue": 25.0, "CurrentMinimum": 0.0, "CurrentMaximum": 100.0,
            "SetValue": lambda self, value: setattr(self, "CurrentValue", float(value)),
        })()
        return control

    original = slider((12, 101))
    replacement = slider((12, 202))
    desktop = _Desktop(_Window(original, title="Demo", text="Demo"))
    backend = UIACaptureBackend(desktop=desktop)
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")
    desktop.window = _Window(replacement, title="Demo", text="Demo")

    with pytest.raises(RuntimeError, match="identitas"):
        backend.set_slider_value(ref, 30.0)

    assert original.iface_range_value.CurrentValue == 25.0
    assert replacement.iface_range_value.CurrentValue == 25.0


def test_uia_dropdown_exposes_stable_selected_option_id_not_free_text():
    from jarvis.automation.uia_capture import _element_from_control

    control = _Control(text="Sensitive option label", kind="ComboBox")
    control.iface_selection = type("Selection", (), {
        "GetSelection": lambda self: [type("Item", (), {
            "element_info": type("Info", (), {"automation_id": "option-2"})(),
        })()],
    })()

    element = _element_from_control(control, 1)

    assert element.role == "dropdown"
    assert element.states["selected_id"] == "option-2"
    assert "Sensitive option label" not in str(element.states)


def test_uia_dropdown_option_requires_selection_item_and_stable_identity():
    from jarvis.automation.uia_capture import _element_from_control

    item = _Control(kind="ListItem", runtime_id=(12, 99))
    dropdown = type("Combo", (), {
        "element_info": type("Info", (), {"control_type": "ComboBox", "runtime_id": (12, 88)})(),
    })()
    parent = type("List", (), {"element_info": type("Info", (), {"control_type": "List"})()})()
    parent.parent = lambda: dropdown
    item.parent = lambda: parent
    item.iface_selection_item = type("SelectionItem", (), {"CurrentIsSelected": False})()

    element = _element_from_control(item, 1)

    assert element.role == "dropdown_option"
    assert element.states == {
        "disabled": False, "_uia_runtime_id": "12.99",
        "_uia_parent_runtime_id": "12.88", "selected": False,
    }


def _dropdown_option(*, option_runtime=(12, 99), dropdown_runtime=(12, 88),
                     commit_parent_value: bool = True):
    calls = []
    item = _Control(kind="ListItem", runtime_id=option_runtime)
    value = type("Value", (), {"CurrentValue": "Fixture current"})()
    dropdown = type("Combo", (), {
        "element_info": type("Info", (), {
            "control_type": "ComboBox", "runtime_id": dropdown_runtime,
        })(),
        "iface_value": value,
    })()
    parent = type("List", (), {
        "element_info": type("Info", (), {"control_type": "List"})(),
    })()
    parent.parent = lambda: dropdown
    item.parent = lambda: parent

    def select(_self):
        calls.append("select")
        if commit_parent_value:
            value.CurrentValue = "Fixture alternative"

    item.iface_selection_item = type("SelectionItem", (), {
        "CurrentIsSelected": False,
        "Select": select,
    })()
    return item, calls


def test_uia_backend_selects_exact_dropdown_option_once():
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    option, calls = _dropdown_option()
    backend = UIACaptureBackend(desktop=_Desktop(_Window(option, title="Demo", text="Demo")))
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")

    committed = backend.select_option_semantic(ref)

    assert committed is True
    assert calls == ["select"]


def test_uia_backend_reports_uncommitted_or_duplicate_dropdown_parent_value():
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    option, calls = _dropdown_option(commit_parent_value=False)
    backend = UIACaptureBackend(desktop=_Desktop(_Window(option, title="Demo", text="Demo")))
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")

    committed = backend.select_option_semantic(ref)

    assert committed is False
    assert calls == ["select"]


def test_uia_backend_rejects_missing_parent_value_pattern_before_select():
    import pytest

    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    option, calls = _dropdown_option()
    dropdown = option.parent().parent()
    delattr(type(dropdown), "iface_value")
    backend = UIACaptureBackend(desktop=_Desktop(_Window(option, title="Demo", text="Demo")))
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")

    with pytest.raises(RuntimeError, match="ValuePattern"):
        backend.select_option_semantic(ref)

    assert calls == []


def test_uia_backend_after_value_read_failure_never_retries_select():
    import pytest

    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    option, calls = _dropdown_option()
    dropdown = option.parent().parent()

    class _FailAfterMutation:
        reads = 0

        @property
        def CurrentValue(self):
            self.reads += 1
            if self.reads == 1:
                return "Fixture current"
            raise RuntimeError("fixture after-read failure")

    dropdown.iface_value = _FailAfterMutation()
    backend = UIACaptureBackend(desktop=_Desktop(_Window(option, title="Demo", text="Demo")))
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")

    with pytest.raises(RuntimeError, match="setelah select"):
        backend.select_option_semantic(ref)

    assert calls == ["select"]


def test_uia_backend_rejects_changed_dropdown_parent_before_select():
    import pytest

    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    original, original_calls = _dropdown_option(dropdown_runtime=(12, 88))
    replacement, replacement_calls = _dropdown_option(dropdown_runtime=(12, 188))
    desktop = _Desktop(_Window(original, title="Demo", text="Demo"))
    backend = UIACaptureBackend(desktop=desktop)
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")
    desktop.window = _Window(replacement, title="Demo", text="Demo")

    with pytest.raises(RuntimeError, match="dropdown berubah"):
        backend.select_option_semantic(ref)

    assert original_calls == []
    assert replacement_calls == []


def test_uia_checkbox_requires_binary_toggle_pattern_and_stable_identity():
    from jarvis.automation.uia_capture import _element_from_control

    checkbox = _Control(kind="CheckBox", runtime_id=(12, 55))
    checkbox.iface_toggle = type("Toggle", (), {"CurrentToggleState": 1})()

    element = _element_from_control(checkbox, 1)

    assert element.role == "checkbox"
    assert element.states == {
        "disabled": False, "_uia_runtime_id": "12.55", "checked": True,
    }


def test_uia_checkbox_tristate_or_missing_toggle_pattern_is_not_actionable():
    from jarvis.automation.uia_capture import _element_from_control

    tristate = _Control(kind="CheckBox")
    tristate.iface_toggle = type("Toggle", (), {"CurrentToggleState": 2})()
    missing_pattern = _Control(kind="CheckBox")

    assert _element_from_control(tristate, 1) is None
    assert _element_from_control(missing_pattern, 1) is None


def test_uia_backend_rejects_replaced_checkbox_before_native_toggle():
    import pytest

    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend

    def checkbox(runtime_id):
        control = _Control(kind="CheckBox", runtime_id=runtime_id)
        control.iface_toggle = type("Toggle", (), {
            "CurrentToggleState": 0,
            "Toggle": lambda self: setattr(self, "CurrentToggleState", 1),
        })()
        return control

    original = checkbox((12, 101))
    replacement = checkbox((12, 202))
    desktop = _Desktop(_Window(original, title="Demo", text="Demo"))
    backend = UIACaptureBackend(desktop=desktop)
    gate = CuaSafetyGate()
    before = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(before.id, "uia-1")
    desktop.window = _Window(replacement, title="Demo", text="Demo")

    with pytest.raises(RuntimeError, match="identitas"):
        backend.toggle_checkbox_semantic(ref)

    assert original.iface_toggle.CurrentToggleState == 0
    assert replacement.iface_toggle.CurrentToggleState == 0


def test_uia_backend_redacts_denylisted_window_without_elements(monkeypatch):
    from jarvis.automation.uia_capture import UIACaptureBackend

    monkeypatch.setattr("jarvis.automation.uia_capture.is_denylisted", lambda *_: True)
    backend = UIACaptureBackend(desktop=_Desktop(_Window(title="Vault", text="Vault")))

    frame = backend.capture()

    assert frame.privacy == "redacted"
    assert frame.tree.scopes() == []


def test_uia_safe_click_uses_lease_clicks_center_once_and_recaptures():
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend, UIASafeClickService

    first = _Window(_Control(text="Next", kind="Button"), title="Demo", text="Demo")
    second = _Window(_Control(text="Done", kind="Button"), title="Demo", text="Demo")
    windows = iter((first, second))
    backend = UIACaptureBackend(desktop=type("D", (), {"get_active": lambda self: next(windows)})())
    gate = CuaSafetyGate()
    adapter = CaptureAdapter(gate, backend.capture)
    before = adapter.capture()
    element = before.tree.by_scope(ElementScope.PAGE_MAIN)[0]
    ref = gate.reference(before.id, element.element_id)

    class _Lease:
        def __init__(self): self.calls = []
        def claim(self, owner): self.calls.append(("claim", owner)); return True
        def release(self, owner): self.calls.append(("release", owner))

    class _Driver:
        def __init__(self): self.calls = []
        def click(self, x, y, **kwargs): self.calls.append((x, y, kwargs))

    lease, driver = _Lease(), _Driver()
    outcome = UIASafeClickService(gate, adapter, driver=driver, desktop=lease).click(
        ref, session_id="safe-test")

    assert outcome.ok is True
    assert outcome.verified is True
    assert driver.calls == [(60, 40, {"button": "left", "double": False})]
    assert lease.calls == [("claim", "safe-test"), ("release", "safe-test")]


def test_uia_safe_click_refuses_when_desktop_lease_is_busy():
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend, UIASafeClickService

    backend = UIACaptureBackend(desktop=_Desktop(_Window(_Control(), title="Demo", text="Demo")))
    gate = CuaSafetyGate()
    adapter = CaptureAdapter(gate, backend.capture)
    before = adapter.capture()
    ref = gate.reference(before.id, before.tree.by_scope(ElementScope.PAGE_MAIN)[0].element_id)
    desktop = type("Lease", (), {"claim": lambda *_: False, "release": lambda *_: None})()
    driver = type("Driver", (), {"click": lambda *_a, **_k: (_ for _ in ()).throw(AssertionError())})()

    outcome = UIASafeClickService(gate, adapter, driver=driver, desktop=desktop).click(ref, session_id="busy")

    assert outcome.ok is False
    assert outcome.executed is False
    assert "dikendalikan" in outcome.reason


def test_uia_safe_click_emits_structured_audit_without_sensitive_label():
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.uia_capture import UIACaptureBackend, UIASafeClickService

    windows = iter((_Window(_Control(text="Next"), title="Demo", text="Demo"),
                    _Window(_Control(text="Done"), title="Demo", text="Demo")))
    backend = UIACaptureBackend(desktop=type("D", (), {"get_active": lambda self: next(windows)})())
    gate = CuaSafetyGate()
    adapter = CaptureAdapter(gate, backend.capture)
    before = adapter.capture()
    ref = gate.reference(before.id, before.tree.by_scope(ElementScope.PAGE_MAIN)[0].element_id)
    events = []
    service = UIASafeClickService(
        gate, adapter,
        driver=type("Driver", (), {"click": lambda *_a, **_k: None})(),
        desktop=type("Lease", (), {"claim": lambda *_: True, "release": lambda *_: None})(),
        audit=lambda event, **fields: events.append((event, fields)),
    )

    assert service.click(ref, session_id="audit").ok is True
    names = [event for event, _ in events]
    assert {"cua.safe_click.capture", "cua.safe_click.decision", "cua.safe_click.lease", "cua.safe_click.attempt", "cua.safe_click.recapture"} <= set(names)
    assert all("Next" not in str(fields) for _, fields in events)


def test_uia_capture_backend_has_no_screenshot_or_vision_api():
    from jarvis.automation.uia_capture import UIACaptureBackend

    assert not hasattr(UIACaptureBackend, "screenshot")
    assert not hasattr(UIACaptureBackend, "vision_analyze")
    assert not hasattr(UIACaptureBackend, "click")
    assert not hasattr(UIACaptureBackend, "type")


def test_uia_text_field_exposes_runtime_identity_when_available():
    # Phase 21C regression (G1): text_field harus membawa _uia_runtime_id
    # supaya desktop_safe_set_content_title dapat membuktikan identitas
    # stabil (native_identity) — tanpa ini tool selalu fail-closed.
    from jarvis.automation.uia_capture import _element_from_control

    control = _Control(kind="Edit", runtime_id=(12, 77))

    element = _element_from_control(control, 1)

    assert element is not None
    assert element.role == "text_field"
    assert element.states["_uia_runtime_id"] == "12.77"  # RED: saat ini kosong


def test_uia_plain_list_item_becomes_card_with_parent_identity():
    # Phase 21C regression (G2): listitem biasa (parent List tanpa ComboBox,
    # mis. scene cards Content Studio / QListWidget) harus muncul sebagai
    # "card" dengan runtime identity + parent identity — saat ini dibuang.
    from jarvis.automation.uia_capture import _element_from_control

    item = _Control(kind="ListItem", runtime_id=(12, 101))
    parent = type("List", (), {
        "element_info": type("Info", (), {
            "control_type": "List", "runtime_id": (12, 100),
        })(),
    })()
    parent.parent = lambda: None   # grandparent bukan ComboBox -> plain list item
    item.parent = lambda: parent

    element = _element_from_control(item, 1)

    assert element is not None                       # RED: saat ini None
    assert element.role == "card"
    assert element.states["_uia_runtime_id"] == "12.101"
    assert element.states["_uia_parent_runtime_id"] == "12.100"
