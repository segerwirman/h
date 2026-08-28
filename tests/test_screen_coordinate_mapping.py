"""Task 11 — pure virtual-desktop and mixed-DPI coordinate mapping.

All layouts are synthetic. These tests never inspect a live monitor, capture the
screen, move the pointer, or invoke native UI automation.
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest
from pydantic import ValidationError


@pytest.fixture()
def mixed_layout():
    from jarvis.automation.screen_coordinates import MonitorGeometry

    return [
        MonitorGeometry(
            name="left-150",
            logical_rect=(-1280, 0, 1280, 720),
            physical_rect=(-1920, 0, 1920, 1080),
            dpi_scale=1.5,
        ),
        MonitorGeometry(
            name="primary-100",
            logical_rect=(0, 0, 1920, 1080),
            physical_rect=(0, 0, 1920, 1080),
            dpi_scale=1.0,
        ),
    ]


def test_primary_monitor_mapping_is_identity_at_100_percent(mixed_layout):
    from jarvis.automation.screen_coordinates import ScreenCoordinateMapper

    mapper = ScreenCoordinateMapper(lambda: mixed_layout, uia_space="logical")

    assert mapper.to_physical((960, 540), source_space="logical") == (960, 540)
    assert mapper.map_rect(
        (100, 200, 400, 300),
        source_space="logical",
        target_space="physical",
    ) == (100, 200, 400, 300)
    assert mapper.rect_center_to_physical((100, 200, 400, 300)) == (300, 350)


def test_negative_origin_monitor_maps_logical_geometry_at_150_percent(mixed_layout):
    from jarvis.automation.screen_coordinates import ScreenCoordinateMapper

    mapper = ScreenCoordinateMapper(lambda: mixed_layout, uia_space="logical")

    assert mapper.to_physical((-1200, 100), source_space="logical") == (-1800, 150)
    assert mapper.map_rect(
        (-1200, 100, 300, 100),
        source_space="logical",
        target_space="physical",
    ) == (-1800, 150, 450, 150)
    assert mapper.rect_center_to_physical((-1200, 100, 300, 100)) == (-1575, 225)


def test_point_and_rect_round_trip_across_mixed_dpi_layout(mixed_layout):
    from jarvis.automation.screen_coordinates import ScreenCoordinateMapper

    mapper = ScreenCoordinateMapper(lambda: mixed_layout, uia_space="logical")
    logical_point = (-1100, 240)
    logical_rect = (-1180, 120, 240, 160)

    physical_point = mapper.map_point(
        logical_point,
        source_space="logical",
        target_space="physical",
    )
    physical_rect = mapper.map_rect(
        logical_rect,
        source_space="logical",
        target_space="physical",
    )

    assert mapper.map_point(
        physical_point,
        source_space="physical",
        target_space="logical",
    ) == logical_point
    assert mapper.map_rect(
        physical_rect,
        source_space="physical",
        target_space="logical",
    ) == logical_rect


def test_mapping_reads_injected_provider_on_each_operation(mixed_layout):
    from jarvis.automation.screen_coordinates import ScreenCoordinateMapper

    calls = []

    def provider():
        calls.append("layout")
        return mixed_layout

    mapper = ScreenCoordinateMapper(provider, uia_space="logical")

    assert mapper.to_physical((-1200, 100), source_space="logical") == (-1800, 150)
    assert mapper.to_logical((-1800, 150)) == (-1200, 100)
    assert calls == ["layout", "layout"]


@pytest.mark.parametrize(
    ("operation", "match"),
    [
        (lambda mapper: mapper.to_physical((5000, 10), source_space="logical"), "monitor"),
        (
            lambda mapper: mapper.map_rect(
                (-100, 10, 200, 100),
                source_space="logical",
                target_space="physical",
            ),
            "satu monitor",
        ),
        (
            lambda mapper: mapper.map_rect(
                (10, 10, 0, 100),
                source_space="logical",
                target_space="physical",
            ),
            "positif",
        ),
    ],
)
def test_mapping_fails_closed_for_unknown_or_cross_monitor_geometry(
    mixed_layout, operation, match,
):
    from jarvis.automation.screen_coordinates import (
        CoordinateMappingError,
        ScreenCoordinateMapper,
    )

    mapper = ScreenCoordinateMapper(lambda: mixed_layout, uia_space="logical")

    with pytest.raises(CoordinateMappingError, match=match):
        operation(mapper)


def test_monitor_geometry_rejects_dpi_and_rectangle_mismatch():
    from jarvis.automation.screen_coordinates import MonitorGeometry

    with pytest.raises(ValueError, match="DPI"):
        MonitorGeometry(
            name="invalid",
            logical_rect=(0, 0, 1000, 800),
            physical_rect=(0, 0, 1200, 800),
            dpi_scale=1.5,
        )


@dataclass
class _Rect:
    left: int = -1200
    top: int = 100
    right: int = -900
    bottom: int = 200


class _Control:
    handle = 12
    element_info = type("Info", (), {
        "control_type": "Button",
        "is_dialog": False,
        "runtime_id": (12, 1),
    })()

    def window_text(self):
        return "Next"

    def friendly_class_name(self):
        return "Button"

    def rectangle(self):
        return _Rect()

    def is_visible(self):
        return True

    def is_enabled(self):
        return True


class _Window(_Control):
    def __init__(self, child):
        self._child = child

    def descendants(self):
        return [self._child]

    def window_text(self):
        return "Demo"


class _Desktop:
    def __init__(self, window):
        self._window = window

    def get_active(self):
        return self._window


def test_uia_click_derives_physical_center_through_injected_mapper(mixed_layout):
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.screen_coordinates import ScreenCoordinateMapper
    from jarvis.automation.uia_capture import UIACaptureBackend

    driver_calls = []
    driver = type("Driver", (), {
        "click": lambda _self, x, y, **kwargs: driver_calls.append((x, y, kwargs)),
    })()
    mapper = ScreenCoordinateMapper(lambda: mixed_layout, uia_space="logical")
    backend = UIACaptureBackend(
        desktop=_Desktop(_Window(_Control())),
        driver=driver,
        coordinates=mapper,
    )
    gate = CuaSafetyGate()
    observation = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(observation.id, "uia-1")

    backend.click_semantic(ref)

    assert driver_calls == [
        (-1575, 225, {"button": "left", "double": False}),
    ]


@pytest.mark.parametrize(
    ("method_name", "expected_kwargs"),
    [
        ("right_click_semantic", {"button": "right", "double": False}),
        ("double_click_semantic", {"button": "left", "double": True}),
    ],
)
def test_uia_pointer_variants_derive_physical_center_through_injected_mapper(
    mixed_layout, method_name, expected_kwargs,
):
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.screen_coordinates import ScreenCoordinateMapper
    from jarvis.automation.uia_capture import UIACaptureBackend

    driver_calls = []
    driver = type("Driver", (), {
        "click": lambda _self, x, y, **kwargs: driver_calls.append((x, y, kwargs)),
    })()
    mapper = ScreenCoordinateMapper(lambda: mixed_layout, uia_space="logical")
    backend = UIACaptureBackend(
        desktop=_Desktop(_Window(_Control())),
        driver=driver,
        coordinates=mapper,
    )
    gate = CuaSafetyGate()
    observation = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(observation.id, "uia-1")

    getattr(backend, method_name)(ref)

    assert driver_calls == [(-1575, 225, expected_kwargs)]


def test_uia_scroll_derives_physical_center_through_injected_mapper(mixed_layout):
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.screen_coordinates import ScreenCoordinateMapper
    from jarvis.automation.uia_capture import UIACaptureBackend

    control = _Control()
    control.element_info = type("Info", (), {
        "control_type": "ScrollBar",
        "is_dialog": False,
        "runtime_id": (12, 2),
    })()
    control.iface_range_value = type("Range", (), {"CurrentValue": 10.0})()
    driver_calls = []
    driver = type("Driver", (), {
        "scroll": lambda _self, x, y, delta: driver_calls.append((x, y, delta)),
    })()
    mapper = ScreenCoordinateMapper(lambda: mixed_layout, uia_space="logical")
    backend = UIACaptureBackend(
        desktop=_Desktop(_Window(control)),
        driver=driver,
        coordinates=mapper,
    )
    gate = CuaSafetyGate()
    observation = CaptureAdapter(gate, backend.capture).capture()
    ref = gate.reference(observation.id, "uia-1")

    backend.scroll_semantic(ref, -3)

    assert driver_calls == [(-1575, 225, -3)]


def test_uia_reorder_maps_both_centers_through_injected_mapper(mixed_layout):
    from jarvis.automation.cua_safe_click import CaptureAdapter
    from jarvis.automation.cua_safety import CuaSafetyGate
    from jarvis.automation.screen_coordinates import ScreenCoordinateMapper
    from jarvis.automation.uia_capture import UIACaptureBackend

    def card(rect, runtime_id):
        control = _Control()
        control.rectangle = lambda: rect
        control.element_info = type("Info", (), {
            "control_type": "ListItem",
            "is_dialog": False,
            "runtime_id": runtime_id,
        })()
        parent = type("List", (), {
            "element_info": type("Info", (), {
                "control_type": "List",
                "runtime_id": (12, 100),
            })(),
        })()
        parent.parent = lambda: None
        control.parent = lambda: parent
        return control

    source = card(_Rect(-1200, 100, -1000, 200), (12, 11))
    destination = card(_Rect(-1000, 300, -800, 400), (12, 12))
    window = _Window(source)
    window._child = source
    window.descendants = lambda: [source, destination]
    driver_calls = []
    driver = type("Driver", (), {
        "drag": lambda _self, *args, **kwargs: driver_calls.append((args, kwargs)),
    })()
    mapper = ScreenCoordinateMapper(lambda: mixed_layout, uia_space="logical")
    backend = UIACaptureBackend(
        desktop=_Desktop(window),
        driver=driver,
        coordinates=mapper,
    )
    gate = CuaSafetyGate()
    observation = CaptureAdapter(gate, backend.capture).capture()
    src_ref = gate.reference(observation.id, "uia-1")
    dst_ref = gate.reference(observation.id, "uia-2")

    backend.reorder_semantic(src_ref, dst_ref)

    assert driver_calls == [
        ((-1650, 225, -1350, 525), {"duration": 0.35}),
    ]


@pytest.mark.parametrize("forbidden", ["x", "y"])
def test_agent_safe_click_schema_rejects_raw_coordinates(forbidden):
    from jarvis.agent.tools.desktop_safe_click import DesktopSafeClick

    validator = getattr(
        DesktopSafeClick.params_schema,
        "model_validate",
        DesktopSafeClick.params_schema.parse_obj,
    )
    payload = {
        "observation_id": "observation-1",
        "element_id": "uia-1",
        forbidden: 10,
    }

    with pytest.raises(ValidationError):
        validator(payload)
