"""Task 7 — pure selected-tab preview projection and fake Qt cursor tests.

All screenshot images and metadata are synthetic in-memory Qt objects. The suite
never launches Chrome, attaches CDP, captures a live page, or performs input.
"""
from __future__ import annotations

import inspect
import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QImage
from PyQt6.QtWidgets import QApplication, QWidget

_APP = QApplication.instance() or QApplication([])

try:
    from jarvis.ui import tab_share_preview as preview_module
except ImportError:
    preview_module = SimpleNamespace()


def _project(**kwargs):
    project = getattr(preview_module, "project_dom_rect", None)
    if not callable(project):
        return None
    return project(**kwargs)


def _generation(*, target=7, document=3, observation=11, preview=5):
    factory = getattr(preview_module, "PreviewGeneration", None)
    assert callable(factory), "PreviewGeneration is not implemented"
    return factory(
        target_generation=target,
        document_generation=document,
        observation_generation=observation,
        preview_generation=preview,
    )


def _metadata(
    *,
    viewport=(1000.0, 500.0),
    screenshot=(2000, 1000),
    generation=None,
    captured_at=100.0,
    expires_at=105.0,
):
    factory = getattr(preview_module, "PreviewMetadata", None)
    assert callable(factory), "PreviewMetadata is not implemented"
    return factory(
        viewport_css=viewport,
        screenshot_px=screenshot,
        generation=generation or _generation(),
        captured_at=captured_at,
        expires_at=expires_at,
    )


def _cursor(
    *,
    rect=(100.0, 50.0, 200.0, 100.0),
    generation=None,
    state="planned",
):
    factory = getattr(preview_module, "CursorVisual", None)
    assert callable(factory), "CursorVisual is not implemented"
    return factory(
        dom_rect=rect,
        generation=generation or _generation(),
        state=state,
    )


def _image(width=2000, height=1000):
    image = QImage(width, height, QImage.Format.Format_RGB32)
    image.fill(QColor(24, 32, 36))
    return image


def _png_bytes(width=2000, height=1000):
    from PyQt6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    assert buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    assert _image(width, height).save(buffer, "PNG")
    buffer.close()
    return bytes(data)


def _widget(*, clock=lambda: 100.0):
    factory = getattr(preview_module, "TabSharePreview", None)
    assert callable(factory), "TabSharePreview is not implemented"
    widget = factory(clock=clock)
    widget.resize(500, 500)
    widget.show()
    _APP.processEvents()
    return widget


def test_pure_projection_maps_1x_and_hidpi_screenshots_to_same_preview_geometry():
    expected_rect = pytest.approx((60.0, 45.0, 100.0, 50.0))
    expected_cursor = pytest.approx((110.0, 70.0))

    one_x = _project(
        dom_rect=(100.0, 50.0, 200.0, 100.0),
        viewport_css=(1000.0, 500.0),
        screenshot_px=(1000, 500),
        preview_rect=(10.0, 20.0, 500.0, 250.0),
    )
    hidpi = _project(
        dom_rect=(100.0, 50.0, 200.0, 100.0),
        viewport_css=(1000.0, 500.0),
        screenshot_px=(2000, 1000),
        preview_rect=(10.0, 20.0, 500.0, 250.0),
    )

    assert one_x is not None and one_x.visible is True
    assert one_x.target_rect == expected_rect
    assert one_x.cursor == expected_cursor
    assert hidpi is not None and hidpi.visible is True
    assert hidpi.target_rect == expected_rect
    assert hidpi.cursor == expected_cursor


def test_pure_projection_applies_aspect_fit_letterbox_and_widget_resize():
    full = (0.0, 0.0, 1000.0, 500.0)

    landscape = _project(
        dom_rect=full,
        viewport_css=(1000.0, 500.0),
        screenshot_px=(2000, 1000),
        preview_rect=(0.0, 0.0, 800.0, 600.0),
    )
    resized = _project(
        dom_rect=full,
        viewport_css=(1000.0, 500.0),
        screenshot_px=(2000, 1000),
        preview_rect=(0.0, 0.0, 400.0, 400.0),
    )

    assert landscape is not None and landscape.visible is True
    assert landscape.target_rect == pytest.approx((0.0, 100.0, 800.0, 400.0))
    assert landscape.cursor == pytest.approx((400.0, 300.0))
    assert resized is not None and resized.visible is True
    assert resized.target_rect == pytest.approx((0.0, 100.0, 400.0, 200.0))
    assert resized.cursor == pytest.approx((200.0, 200.0))


def test_pure_projection_supports_fractional_mixed_dpi_without_os_coordinates():
    result = _project(
        dom_rect=(320.0, 180.0, 160.0, 90.0),
        viewport_css=(1600.0, 900.0),
        screenshot_px=(2400, 1350),
        preview_rect=(25.0, 40.0, 800.0, 600.0),
    )

    assert result is not None and result.visible is True
    assert result.target_rect == pytest.approx((185.0, 205.0, 80.0, 45.0))
    assert result.cursor == pytest.approx((225.0, 227.5))


def test_pure_projection_clips_partial_elements_and_hides_fully_off_viewport_rects():
    partial = _project(
        dom_rect=(-100.0, 100.0, 300.0, 100.0),
        viewport_css=(1000.0, 500.0),
        screenshot_px=(2000, 1000),
        preview_rect=(0.0, 0.0, 1000.0, 500.0),
    )
    outside = _project(
        dom_rect=(1100.0, 100.0, 50.0, 50.0),
        viewport_css=(1000.0, 500.0),
        screenshot_px=(2000, 1000),
        preview_rect=(0.0, 0.0, 1000.0, 500.0),
    )

    assert partial is not None and partial.visible is True
    assert partial.target_rect == pytest.approx((0.0, 100.0, 200.0, 100.0))
    assert partial.cursor == pytest.approx((100.0, 150.0))
    assert outside is not None and outside.visible is False
    assert outside.cursor is None
    assert outside.target_rect is None


@pytest.mark.parametrize(
    ("viewport", "screenshot", "preview", "rect"),
    [
        ((0.0, 500.0), (1000, 500), (0.0, 0.0, 500.0, 250.0), (1, 1, 10, 10)),
        ((1000.0, 500.0), (0, 500), (0.0, 0.0, 500.0, 250.0), (1, 1, 10, 10)),
        ((1000.0, 500.0), (1000, 1000), (0.0, 0.0, 500.0, 250.0), (1, 1, 10, 10)),
        ((1000.0, 500.0), (1000, 500), (0.0, 0.0, 0.0, 250.0), (1, 1, 10, 10)),
        ((1000.0, 500.0), (1000, 500), (0.0, 0.0, 500.0, 250.0), (1, 1, -1, 10)),
        ((1000.0, 500.0), (1000, 500), (0.0, 0.0, 500.0, 250.0), (float("nan"), 1, 10, 10)),
    ],
)
def test_pure_projection_fails_closed_for_missing_invalid_or_inconsistent_metadata(
    viewport,
    screenshot,
    preview,
    rect,
):
    result = _project(
        dom_rect=rect,
        viewport_css=viewport,
        screenshot_px=screenshot,
        preview_rect=preview,
    )

    assert result is not None
    assert result.visible is False
    assert result.cursor is None
    assert result.target_rect is None


def test_preview_widget_is_focusless_click_through_and_has_no_input_handlers():
    widget = _widget()
    try:
        assert widget.focusPolicy() == Qt.FocusPolicy.NoFocus
        assert widget.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        assert widget.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        assert widget.windowFlags() & Qt.WindowType.WindowDoesNotAcceptFocus

        source = inspect.getsource(preview_module)
        for forbidden in (
            "jarvis.automation",
            "pyautogui",
            "NativeCUADriver",
            "DesktopService",
            "mousePressEvent",
            "mouseReleaseEvent",
            "mouseMoveEvent",
            "mouseDoubleClickEvent",
            "wheelEvent",
            "keyPressEvent",
            "keyReleaseEvent",
            "touchEvent",
            "tabletEvent",
            "dragEnterEvent",
            "dropEvent",
        ):
            assert forbidden not in source
    finally:
        widget.close()
        _APP.processEvents()


def test_widget_requires_exact_fresh_generation_and_supported_visual_state():
    now = [100.0]
    widget = _widget(clock=lambda: now[0])
    try:
        assert widget.replace_preview(_image(), _metadata()) is True
        assert widget.has_preview is True

        assert widget.update_cursor(_cursor(state="planned")) is True
        assert widget.cursor_state == "planned"
        assert widget.cursor is not None

        for field in ("target", "document", "observation", "preview"):
            values = {"target": 7, "document": 3, "observation": 11, "preview": 5}
            values[field] += 1
            assert widget.update_cursor(
                _cursor(
                    generation=_generation(
                        target=values["target"],
                        document=values["document"],
                        observation=values["observation"],
                        preview=values["preview"],
                    )
                )
            ) is False
            assert widget.cursor is None

        assert widget.update_cursor(_cursor(state="unsupported")) is False
        assert widget.cursor is None

        now[0] = 105.0
        assert widget.update_cursor(_cursor(state="verified")) is False
        assert widget.has_preview is False
        assert widget.cursor is None
    finally:
        widget.close()
        _APP.processEvents()


@pytest.mark.parametrize(
    "state",
    ["planned", "attempted", "verified", "ambiguous"],
)
def test_widget_distinguishes_visual_states_without_treating_them_as_evidence(state):
    widget = _widget()
    try:
        assert widget.replace_preview(_image(), _metadata()) is True
        assert widget.update_cursor(_cursor(state=state)) is True

        assert widget.cursor_state == state
        assert widget.cursor is not None
        assert not hasattr(widget, "executed")
        assert not hasattr(widget, "verified")
        assert not hasattr(widget, "action_result")
    finally:
        widget.close()
        _APP.processEvents()


def test_preview_replacement_resize_and_invalid_image_recompute_or_clear_fail_closed():
    widget = _widget()
    try:
        assert widget.replace_preview(_image(), _metadata()) is True
        assert widget.update_cursor(_cursor()) is True
        before = widget.target_rect

        widget.resize(800, 600)
        _APP.processEvents()
        assert widget.target_rect != before

        next_generation = _generation(observation=12, preview=6)
        assert widget.replace_preview(
            _image(1000, 500),
            _metadata(
                screenshot=(1000, 500),
                generation=next_generation,
            ),
        ) is True
        assert widget.has_preview is True
        assert widget.cursor is None
        assert widget.cursor_state == ""

        assert widget.replace_preview(
            _image(1000, 500),
            _metadata(screenshot=(2000, 1000), generation=next_generation),
        ) is False
        assert widget.has_preview is False
        assert widget.cursor is None
    finally:
        widget.close()
        _APP.processEvents()


def test_widget_clear_and_close_retire_volatile_image_and_cursor():
    widget = _widget()
    assert widget.replace_preview(_image(), _metadata()) is True
    assert widget.update_cursor(_cursor(state="attempted")) is True

    widget.clear_preview()
    assert widget.has_preview is False
    assert widget.cursor is None
    assert widget.cursor_state == ""

    assert widget.replace_preview(_image(), _metadata()) is True
    assert widget.update_cursor(_cursor(state="ambiguous")) is True
    widget.close()
    _APP.processEvents()

    assert widget.has_preview is False
    assert widget.cursor is None


class _PreviewPage:
    def __init__(self) -> None:
        self.url = "https://safe.test/path?private=query#fragment"
        self.viewport_size = {"width": 1000, "height": 500}
        self.closed = False
        self.listeners = {}
        self.main_frame = object()
        self.screenshot_calls = 0

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    async def title(self):
        return "Offline fake tab"

    def is_closed(self):
        return self.closed

    async def screenshot(self, **kwargs):
        assert kwargs == {"full_page": False, "type": "png"}
        self.screenshot_calls += 1
        return _png_bytes()


class _PreviewBrowser:
    def __init__(self, page) -> None:
        self.contexts = [SimpleNamespace(pages=[page])]
        self.listeners = {}

    def on(self, event, callback):
        self.listeners.setdefault(event, []).append(callback)

    async def close(self):
        return None


def _preview_host(records):
    from jarvis.integrations.selected_tab_browser import SelectedTabBrowserHost

    page = _PreviewPage()
    browser = _PreviewBrowser(page)
    ids = iter(("picker-opaque", "candidate-opaque", "target-opaque"))
    host = SelectedTabBrowserHost(
        connector=lambda _port: browser,
        enabled_check=lambda: True,
        port_provider=lambda: 9222,
        id_factory=lambda: next(ids),
    )
    host._semantic_harvester = lambda _page: records
    host._semantic_binding_check = lambda *_args: ""
    host._semantic_clock = lambda: 100.0
    host._semantic_id_factory = iter(
        (
            "observation-opaque-a",
            "element-opaque-a",
            "preview-opaque-a",
            "preview-opaque-b",
        )
    ).__next__
    picker = host.begin_picker()
    selected = host.select_candidate(
        picker.picker_id,
        picker.candidates[0].candidate_id,
    )
    assert selected.ok is True
    return host, selected.target


def test_fake_host_captures_one_volatile_preview_with_exact_generation_and_geometry():
    handle = SimpleNamespace(
        is_visible=lambda: True,
        bounding_box=lambda: {"x": 100, "y": 50, "width": 200, "height": 100},
    )
    records = [
        {
            "handle": handle,
            "tag": "button",
            "role": "button",
            "name": "Continue",
            "label": "",
            "text": "",
            "type": "",
            "container": "main",
            "visible": True,
            "rect": {"x": 100, "y": 50, "w": 200, "h": 100},
            "states": {},
        }
    ]
    host, target = _preview_host(records)
    try:
        observation = host.observe_selected(
            session_id="session-a",
            task_id="T-a",
            target_id=target.target_id,
            target_generation=target.target_generation,
        )
        result = host.capture_preview(
            session_id="session-a",
            task_id="T-a",
            target_id=target.target_id,
            target_generation=target.target_generation,
            observation_id=observation.observation_id,
            element_id=observation.elements[0].element_id,
        )

        assert result.ok is True
        assert result.state == "previewed"
        assert result.image_bytes.startswith(b"\x89PNG")
        assert result.viewport_css == (1000.0, 500.0)
        assert result.screenshot_px == (2000, 1000)
        assert result.dom_rect == (100.0, 50.0, 200.0, 100.0)
        assert result.target_generation == target.target_generation
        assert result.document_generation == observation.document_generation
        assert result.observation_generation == observation.observation_generation
        assert result.preview_generation == 1
        assert result.preview_id
        assert result.expires_at == observation.expires_at
        retained = host.get_preview(result.preview_id)
        assert retained == result
        assert not hasattr(result, "path")
    finally:
        host.shutdown()


def test_new_preview_retires_previous_process_local_image():
    handle = SimpleNamespace(
        is_visible=lambda: True,
        bounding_box=lambda: {"x": 100, "y": 50, "width": 200, "height": 100},
    )
    records = [
        {
            "handle": handle,
            "tag": "button",
            "role": "button",
            "name": "Continue",
            "label": "",
            "text": "",
            "type": "",
            "container": "main",
            "visible": True,
            "rect": {"x": 100, "y": 50, "w": 200, "h": 100},
            "states": {},
        }
    ]
    host, target = _preview_host(records)
    try:
        observation = host.observe_selected(
            session_id="session-a",
            task_id="T-a",
            target_id=target.target_id,
            target_generation=target.target_generation,
        )
        args = {
            "session_id": "session-a",
            "task_id": "T-a",
            "target_id": target.target_id,
            "target_generation": target.target_generation,
            "observation_id": observation.observation_id,
            "element_id": observation.elements[0].element_id,
        }
        first = host.capture_preview(**args)
        second = host.capture_preview(**args)

        assert second.preview_generation == first.preview_generation + 1
        assert host.get_preview(first.preview_id) is None
        assert host.get_preview(second.preview_id) == second
    finally:
        host.shutdown()


def test_action_tool_uses_host_owned_preview_once_and_publishes_opaque_result_id(
    monkeypatch,
):
    from jarvis.agent.execution_context import ExecutionContext
    from jarvis.agent.tools.selected_tab import SelectedTabClick
    from jarvis.core.bus import BUS

    handle = SimpleNamespace(
        checked=False,
        is_visible=lambda: True,
        bounding_box=lambda: {"x": 100, "y": 50, "width": 200, "height": 100},
        evaluate=lambda _expression: {
            "checked": handle.checked,
            "selected": None,
            "expanded": None,
            "pressed": None,
            "value": None,
        },
    )

    async def click():
        handle.checked = True
        records[0]["states"] = {"checked": True}
        records[0]["checked"] = True

    handle.click = click
    records = [
        {
            "handle": handle,
            "tag": "input",
            "role": "checkbox",
            "name": "Continue",
            "label": "",
            "text": "",
            "type": "checkbox",
            "container": "main",
            "visible": True,
            "checked": False,
            "rect": {"x": 100, "y": 50, "w": 200, "h": 100},
            "states": {"checked": False},
        }
    ]
    host, target = _preview_host(records)
    events = []
    monkeypatch.setattr(
        "jarvis.agent.policy.selected_tab_context_error",
        lambda *_args, **_kwargs: "",
    )
    monkeypatch.setattr(
        BUS,
        "publish",
        lambda topic, **data: events.append((topic, data)),
    )
    try:
        observation = host.observe_selected(
            session_id="session-a",
            task_id="T-a",
            target_id=target.target_id,
            target_generation=target.target_generation,
        )
        tool = SelectedTabClick(host=host)
        tool._snapshot_provider = lambda: SimpleNamespace(
            surface_id=target.target_id,
            surface_generation=target.target_generation,
        )
        import asyncio

        result = asyncio.run(tool.run(
            observation_id=observation.observation_id,
            element_id=observation.elements[0].element_id,
            _session=SimpleNamespace(id="session-a", registry_task_id="T-a"),
            _context=ExecutionContext.create(
                source="ui",
                actor_id="local",
                session_id="session-a",
                surface="browser_tab",
                toolsets={"selected_tab"},
            ),
        ))

        assert result.ok is False
        assert result.meta["attempted"] is True
        assert result.meta["executed"] is True
        assert result.meta["ambiguous"] is True
        assert host._call(lambda: host._selected.page.screenshot_calls) == 1
        assert events == [
            (
                "selected_tab.visual",
                {
                    "session_id": "session-a",
                    "task_id": "T-a",
                    "preview_id": "preview-opaque-a",
                    "state": "ambiguous",
                },
            )
        ]
        assert host.get_preview("preview-opaque-a") is not None
        visible = repr((result.content, result.meta)).casefold()
        assert "preview-opaque-a" not in visible
        assert "image_bytes" not in visible
        assert "dom_rect" not in visible
    finally:
        host.shutdown()


def test_fake_host_preview_fails_closed_for_stale_ref_without_screenshot():
    screenshots = []
    host, target = _preview_host([])
    selected = host.active_snapshot()
    assert selected.active is True
    host._call(
        lambda: setattr(
            host._selected.page,
            "screenshot",
            lambda **_kwargs: screenshots.append(True),
        )
    )
    try:
        result = host.capture_preview(
            session_id="session-a",
            task_id="T-a",
            target_id=target.target_id,
            target_generation=target.target_generation,
            observation_id="stale-observation",
            element_id="stale-element",
        )

        assert result.ok is False
        assert result.image_bytes == b""
        assert result.dom_rect is None
        assert screenshots == []
    finally:
        host.shutdown()


def test_visual_bridge_sends_only_opaque_ids_and_bounded_state_over_bus():
    from jarvis.agent.tools.selected_tab import _publish_preview_visual

    events = []
    bus = SimpleNamespace(
        publish=lambda topic, **data: events.append((topic, data))
    )

    _publish_preview_visual(
        bus,
        session_id="session-a",
        task_id="T-a",
        preview_id="preview-opaque",
        state="verified",
    )

    assert events == [
        (
            "selected_tab.visual",
            {
                "session_id": "session-a",
                "task_id": "T-a",
                "preview_id": "preview-opaque",
                "state": "verified",
            },
        )
    ]
    visible = repr(events).casefold()
    for forbidden in (
        "image_bytes",
        "screenshot",
        "dom_rect",
        "viewport",
        "target_id",
        "selector",
        "coordinate",
        "typed text",
    ):
        assert forbidden not in visible


def test_tab_share_sheet_applies_fake_preview_and_cursor_update_without_input():
    from jarvis.ui.tab_share_sheet import TabShareSheet

    class Host:
        def get_preview(self, preview_id):
            assert preview_id == "preview-opaque"
            return SimpleNamespace(
                ok=True,
                state="previewed",
                reason="",
                preview_id=preview_id,
                image_bytes=_png_bytes(),
                viewport_css=(1000.0, 500.0),
                screenshot_px=(2000, 1000),
                dom_rect=(100.0, 50.0, 200.0, 100.0),
                target_generation=7,
                document_generation=3,
                observation_generation=11,
                preview_generation=5,
                captured_at=100.0,
                expires_at=105.0,
            )

    parent = QWidget()
    sheet = TabShareSheet(host=Host(), coordinator=SimpleNamespace(), parent=parent)
    sheet.preview_widget._clock = lambda: 100.0
    try:
        sheet._scope = SimpleNamespace(session_id="session-a", task_id="T-a")
        sheet._active_target_id = "target-opaque"
        sheet._active_target_generation = 7
        sheet.set_runtime_state("sharing")

        assert sheet.refresh_preview(
            preview_id="preview-opaque",
            cursor_state="verified",
        ) is True
        assert sheet.preview_widget.has_preview is True
        assert sheet.preview_widget.cursor_state == "verified"
        assert sheet.preview_widget.cursor is not None
    finally:
        sheet.close()
        parent.close()
        _APP.processEvents()


def test_tab_share_sheet_consumes_opaque_visual_event_for_exact_scope_only():
    from jarvis.ui.tab_share_sheet import TabShareSheet

    calls = []
    parent = QWidget()
    sheet = TabShareSheet(
        host=SimpleNamespace(),
        coordinator=SimpleNamespace(),
        parent=parent,
    )
    sheet._scope = SimpleNamespace(session_id="session-a", task_id="T-a")
    sheet._active_target_id = "target-opaque"
    sheet._active_target_generation = 7
    sheet.set_runtime_state("sharing")
    sheet.refresh_preview = lambda **kwargs: calls.append(kwargs) or True
    try:
        assert sheet.apply_visual_state(
            {
                "session_id": "session-b",
                "task_id": "T-a",
                "preview_id": "preview-opaque",
                "state": "planned",
            }
        ) is False
        assert sheet.apply_visual_state(
            {
                "session_id": "session-a",
                "task_id": "T-a",
                "preview_id": "preview-opaque",
                "state": "attempted",
            }
        ) is True
        assert calls == [
            {
                "preview_id": "preview-opaque",
                "cursor_state": "attempted",
            }
        ]
    finally:
        sheet.close()
        parent.close()
        _APP.processEvents()


def test_tab_share_sheet_clears_preview_on_all_inactive_lifecycle_boundaries():
    from jarvis.ui.tab_share_sheet import TabShareSheet

    class Host:
        def stop_selected(self, _target_id, _target_generation):
            return True

    class Coordinator:
        def revoke_browser_tab(self, **_kwargs):
            return True

    parent = QWidget()
    parent.resize(900, 700)
    parent.show()
    sheet = TabShareSheet(host=Host(), coordinator=Coordinator(), parent=parent)
    try:
        preview = getattr(sheet, "preview_widget", None)
        assert preview is not None
        preview._clock = lambda: 100.0
        sheet._active_target_id = "target-opaque"
        sheet._active_target_generation = 7
        sheet.set_runtime_state("sharing")

        for reason in (
            "selected_tab_target_navigated",
            "selected_tab_target_closed",
            "selected_tab_browser_disconnected",
            "handoff",
            "expired",
            "task_terminal",
            "user_stop_sharing",
            "application.shutdown",
        ):
            sheet._active_target_id = "target-opaque"
            sheet._active_target_generation = 7
            sheet.set_runtime_state("sharing")
            assert preview.replace_preview(_image(), _metadata()) is True
            assert preview.update_cursor(_cursor()) is True

            sheet.apply_screen_control_state(
                {
                    "active": False,
                    "reason": reason,
                    "surface_kind": "",
                }
            )

            assert preview.has_preview is False
            assert preview.cursor is None

        sheet._active_target_id = "target-opaque"
        sheet._active_target_generation = 7
        sheet.set_runtime_state("sharing")
        assert preview.replace_preview(_image(), _metadata()) is True
        assert preview.update_cursor(_cursor()) is True
        sheet.close()
        _APP.processEvents()
        assert preview.has_preview is False
        assert preview.cursor is None
    finally:
        parent.close()
        _APP.processEvents()
