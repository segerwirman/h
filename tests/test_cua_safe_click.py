"""Vertical safety slice: semantic capture → single click → recapture proof."""
from __future__ import annotations

from dataclasses import dataclass

from jarvis.core.element_model import ElementScope, ScreenElementTree, UIElement


@dataclass
class _Frame:
    surface_id: str
    tree: ScreenElementTree
    privacy: str = "normal"


def _tree(label: str = "Next") -> ScreenElementTree:
    tree = ScreenElementTree()
    tree.add(UIElement(
        element_id="uia-next", scope=ElementScope.PAGE_MAIN, role="button",
        name=label, rect=(40, 60, 100, 30), visible=True,
        confidence=0.95, provenance="uia",
    ))
    return tree


def test_capture_adapter_turns_uia_frame_into_current_safety_observation():
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate

    gate = CuaSafetyGate()
    adapter = CaptureAdapter(gate, lambda: _Frame("window:demo", _tree()))

    observation = adapter.capture()
    ref = gate.reference(observation.id, "uia-next")

    assert observation.surface_id == "window:demo"
    assert ref.label == "Next"


def test_capture_adapter_normalizes_dom_harvest_into_semantic_tree():
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate

    gate = CuaSafetyGate()
    adapter = CaptureAdapter.from_dom_harvest(
        gate,
        lambda: ("page:docs", [{"tag": "button", "name": "Next", "rect": {"x": 1, "y": 2, "w": 3, "h": 4}}]),
    )

    observation = adapter.capture()
    element_id = observation.tree.by_scope(ElementScope.PAGE_MAIN)[0].element_id
    ref = gate.reference(observation.id, element_id)

    assert ref.role == "button"
    assert ref.rect == (1, 2, 3, 4)


def test_safe_click_executes_once_then_requires_newer_same_surface_recapture():
    from jarvis.automation.cua_safe_click import CaptureAdapter, SafeClickPlan
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter([_Frame("window:demo", _tree()), _Frame("window:demo", _tree("Done"))])
    clicks = []
    gate = CuaSafetyGate()
    adapter = CaptureAdapter(gate, lambda: next(frames))
    before = adapter.capture()
    ref = gate.reference(before.id, "uia-next")

    outcome = SafeClickPlan(gate, adapter, lambda rect: clicks.append(rect)).execute(ref)

    assert outcome.ok is True
    assert outcome.verified is True
    assert clicks == [(40, 60, 100, 30)]
    assert outcome.after is not None


def test_safe_click_never_calls_executor_when_confirmation_or_blocked():
    from jarvis.automation.cua_safe_click import CaptureAdapter, SafeClickPlan
    from jarvis.automation.cua_safety import CuaSafetyGate

    clicks = []
    gate = CuaSafetyGate()
    adapter = CaptureAdapter(gate, lambda: _Frame("window:demo", _tree("Delete all")))
    before = adapter.capture()
    ref = gate.reference(before.id, "uia-next")

    outcome = SafeClickPlan(gate, adapter, lambda rect: clicks.append(rect)).execute(ref)

    assert outcome.ok is False
    assert outcome.requires_confirmation is True
    assert clicks == []


def test_safe_click_fails_closed_when_recapture_does_not_prove_same_surface():
    from jarvis.automation.cua_safe_click import CaptureAdapter, SafeClickPlan
    from jarvis.automation.cua_safety import CuaSafetyGate

    frames = iter([_Frame("window:demo", _tree()), _Frame("window:other", _tree())])
    clicks = []
    gate = CuaSafetyGate()
    adapter = CaptureAdapter(gate, lambda: next(frames))
    before = adapter.capture()
    ref = gate.reference(before.id, "uia-next")

    outcome = SafeClickPlan(gate, adapter, lambda rect: clicks.append(rect)).execute(ref)

    assert outcome.ok is False
    assert outcome.executed is True
    assert outcome.verified is False
    assert clicks == [(40, 60, 100, 30)]


def test_safe_click_accepts_only_plain_left_single_click():
    from jarvis.automation.cua_safe_click import CaptureAdapter, SafeClickPlan
    from jarvis.automation.cua_safety import CuaSafetyGate

    gate = CuaSafetyGate()
    adapter = CaptureAdapter(gate, lambda: _Frame("window:demo", _tree()))
    before = adapter.capture()
    ref = gate.reference(before.id, "uia-next")

    outcome = SafeClickPlan(gate, adapter, lambda _rect: None).execute(ref, button="right")

    assert outcome.ok is False
    assert outcome.executed is False
    assert "left" in outcome.reason


def test_safe_click_does_not_expose_type_key_drag_or_coordinate_api():
    from jarvis.automation.cua_safe_click import SafeClickPlan

    assert not hasattr(SafeClickPlan, "type")
    assert not hasattr(SafeClickPlan, "key")
    assert not hasattr(SafeClickPlan, "drag")
    assert not hasattr(SafeClickPlan, "click_at")
    assert not hasattr(SafeClickPlan, "screenshot")
    assert not hasattr(SafeClickPlan, "vision_analyze")
