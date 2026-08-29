"""Task 4 — process-local host for one selected everyday-Chrome tab.

All browser objects are strict fakes. The suite never launches Chrome, opens a CDP
socket, captures a real tab, or performs browser/native input.
"""
from __future__ import annotations

import threading

import pytest


class _OwnedPage:
    def __init__(self, owner: int, url: str, title: str) -> None:
        self._owner = owner
        self._url = url
        self._title = title
        self.touches: list[tuple[str, int]] = []
        self.listeners: dict[str, list] = {}

    def on(self, event: str, callback) -> None:
        self._touch(f"on:{event}")
        self.listeners.setdefault(event, []).append(callback)

    def emit(self, event: str) -> None:
        for callback in tuple(self.listeners.get(event, ())):
            callback()

    def _touch(self, operation: str) -> None:
        current = threading.get_ident()
        assert current == self._owner
        self.touches.append((operation, current))

    @property
    def url(self) -> str:
        self._touch("url")
        return self._url

    def title(self) -> str:
        self._touch("title")
        return self._title


class _OwnedContext:
    def __init__(self, owner: int, pages: list[_OwnedPage]) -> None:
        self._owner = owner
        self._pages = pages

    @property
    def pages(self) -> list[_OwnedPage]:
        assert threading.get_ident() == self._owner
        return list(self._pages)


class _OwnedBrowser:
    def __init__(self, owner: int, pages: list[_OwnedPage]) -> None:
        self._owner = owner
        self.context = _OwnedContext(owner, pages)
        self._contexts = [self.context]
        self.closed = False
        self.listeners: dict[str, list] = {}

    @property
    def contexts(self) -> list[_OwnedContext]:
        assert threading.get_ident() == self._owner
        return list(self._contexts)

    def on(self, event: str, callback) -> None:
        assert threading.get_ident() == self._owner
        self.listeners.setdefault(event, []).append(callback)

    def emit(self, event: str) -> None:
        for callback in tuple(self.listeners.get(event, ())):
            callback()

    def close(self) -> None:
        assert threading.get_ident() == self._owner
        self.closed = True


def _host(urls, *, fail=None, lifecycle_callback=None):
    from jarvis.integrations.selected_tab_browser import SelectedTabBrowserHost

    created = []
    connector_threads = []

    def connect(_port):
        owner = threading.get_ident()
        connector_threads.append(owner)
        if fail is not None:
            raise fail
        pages = [_OwnedPage(owner, url, title) for url, title in urls]
        browser = _OwnedBrowser(owner, pages)
        created.append((browser, pages))
        return browser

    ids = iter(
        [
            "opaque-picker",
            "opaque-candidate-a",
            "opaque-candidate-b",
            "opaque-candidate-c",
            "opaque-target-a",
            "opaque-target-b",
        ]
    )
    host = SelectedTabBrowserHost(
        connector=connect,
        enabled_check=lambda: True,
        port_provider=lambda: 9222,
        id_factory=lambda: next(ids),
        lifecycle_callback=lifecycle_callback,
    )
    return host, created, connector_threads


def test_process_host_is_lazy_and_can_shutdown_without_import_thread_leak():
    from jarvis.integrations import selected_tab_browser

    assert selected_tab_browser._HOST is None
    before = sum(
        thread.name == "selected-tab-browser-owner"
        for thread in threading.enumerate()
    )

    host = selected_tab_browser.get_host()
    assert sum(
        thread.name == "selected-tab-browser-owner"
        for thread in threading.enumerate()
    ) == before + 1

    assert selected_tab_browser.shutdown_host() is True
    assert selected_tab_browser._HOST is None
    with pytest.raises(RuntimeError, match="selected_tab_host_stopped"):
        host.begin_picker()
    assert sum(
        thread.name == "selected-tab-browser-owner"
        for thread in threading.enumerate()
    ) == before


def test_picker_browser_objects_are_owned_by_one_dedicated_thread():
    host, created, connector_threads = _host(
        [("https://example.test/a?secret=1", "Example A")]
    )
    caller_thread = threading.get_ident()
    try:
        result = host.begin_picker()
        assert result.ok is True
        assert result.state == "tabs_available"
        assert len(result.candidates) == 1
        assert connector_threads and connector_threads[0] != caller_thread
        assert all(
            touched_thread == connector_threads[0]
            for _operation, touched_thread in created[0][1][0].touches
        )

        assert host.cancel_picker(result.picker_id) is True
        assert created[0][0].closed is True
    finally:
        host.shutdown()


def test_candidate_identity_survives_reorder_and_never_uses_tab_index():
    host, created, _threads = _host(
        [
            ("https://one.test/path", "One"),
            ("https://two.test/path", "Two"),
        ]
    )
    try:
        picker = host.begin_picker()
        first = picker.candidates[0]
        assert first.candidate_id == "opaque-candidate-a"
        assert "one.test" not in first.candidate_id
        assert not hasattr(first, "index")

        browser, pages = created[0]
        browser.context._pages[:] = list(reversed(pages))
        selected = host.select_candidate(picker.picker_id, first.candidate_id)

        assert selected.ok is True
        assert selected.target is not None
        assert selected.target.title == "One"
        assert selected.target.origin == "https://one.test"
        assert selected.target.target_id == "opaque-candidate-c"
        assert selected.target.target_id != first.candidate_id
        assert selected.target.target_generation == 1
    finally:
        host.shutdown()


def test_picker_lists_only_http_pages_and_excludes_internal_surfaces():
    host, _created, _threads = _host(
        [
            ("chrome://settings", "Settings"),
            ("devtools://devtools/bundled/inspector.html", "DevTools"),
            ("chrome-extension://abc/panel.html", "Extension"),
            ("file:///C:/private.txt", "Private file"),
            ("about:blank", "Blank"),
            ("https://safe.test/path?q=private", "Safe HTTPS"),
            ("http://plain.test/page", "Safe HTTP"),
        ]
    )
    try:
        result = host.begin_picker()
        assert result.ok is True
        assert [candidate.title for candidate in result.candidates] == [
            "Safe HTTPS",
            "Safe HTTP",
        ]
        assert [candidate.origin for candidate in result.candidates] == [
            "https://safe.test",
            "http://plain.test",
        ]
        assert all("private" not in candidate.origin for candidate in result.candidates)
    finally:
        host.shutdown()


def test_closed_port_uses_honest_unavailable_contract(monkeypatch):
    from jarvis.integrations import user_browser

    host, _created, _threads = _host([], fail=ConnectionRefusedError("closed"))
    monkeypatch.setattr(user_browser, "debug_port", lambda: 9222)
    try:
        result = host.begin_picker()
        assert result.ok is False
        assert result.state == "unavailable"
        assert result.candidates == ()
        assert "remote-debugging-port" in result.reason.casefold()
        assert "belum bisa melihat" in result.reason.casefold()
        assert "tidak ada tab" not in result.reason.casefold()
    finally:
        host.shutdown()


def test_picker_disconnect_retires_temporary_inventory_fail_closed():
    host, created, _threads = _host([("https://safe.test", "Safe")])
    try:
        picker = host.begin_picker()
        candidate_id = picker.candidates[0].candidate_id

        created[0][0].emit("disconnected")

        assert host.active_snapshot().active is False
        selected = host.select_candidate(picker.picker_id, candidate_id)
        assert selected.ok is False
        assert selected.state == "stopped"
        assert created[0][0].closed is True
    finally:
        host.shutdown()


def test_cancel_retires_temporary_inventory_and_stale_ids_fail_closed():
    host, created, _threads = _host([("https://safe.test", "Safe")])
    try:
        picker = host.begin_picker()
        candidate_id = picker.candidates[0].candidate_id

        assert host.cancel_picker("wrong-picker") is False
        assert host.cancel_picker(picker.picker_id) is True
        assert created[0][0].closed is True

        selected = host.select_candidate(picker.picker_id, candidate_id)
        assert selected.ok is False
        assert selected.state == "stopped"
        assert host.active_snapshot().active is False
    finally:
        host.shutdown()


@pytest.mark.parametrize(
    ("event", "expected_reason"),
    [
        ("page_close", "selected_tab_target_closed"),
        ("browser_disconnected", "selected_tab_browser_disconnected"),
    ],
)
def test_selected_target_lifecycle_retires_exact_host_and_authority_leases(
    event,
    expected_reason,
):
    from jarvis.automation.selected_tab_session import SelectedTabSessionOwner
    from jarvis.ui.screen_control import ScreenControlCoordinator

    selected_tabs = SelectedTabSessionOwner(clock=lambda: 100.0)
    coordinator = ScreenControlCoordinator(
        selected_tabs=selected_tabs,
        bus=SimpleBus(),
        clock=lambda: 100.0,
        scheduler=SimpleScheduler(),
        selected_tab_scope_check=lambda session_id, task_id: (
            session_id == "session-a" and task_id == "T-a"
        ),
    )
    lifecycle_events = []

    def on_lifecycle(target_id, target_generation, reason):
        lifecycle_events.append((target_id, target_generation, reason))
        coordinator.revoke_browser_tab(
            target_id=target_id,
            target_generation=target_generation,
            reason=reason,
        )

    host, created, _threads = _host(
        [("https://safe.test", "Safe")],
        lifecycle_callback=on_lifecycle,
    )
    try:
        picker = host.begin_picker()
        selected = host.select_candidate(
            picker.picker_id,
            picker.candidates[0].candidate_id,
        )
        assert selected.ok is True
        assert selected.target is not None
        assert coordinator.activate_browser_tab(
            "session-a",
            "T-a",
            target_id=selected.target.target_id,
            target_generation=selected.target.target_generation,
            ttl_s=30,
        ) is True

        if event == "page_close":
            created[0][1][0].emit("close")
        else:
            created[0][0].emit("disconnected")

        assert host.active_snapshot().active is False
        assert coordinator.snapshot().state == "off"
        assert selected_tabs.snapshot().active is False
        assert lifecycle_events == [
            (
                selected.target.target_id,
                selected.target.target_generation,
                expected_reason,
            )
        ]
        assert created[0][0].closed is True
    finally:
        host.shutdown()


class SimpleBus:
    def subscribe(self, _topic, _handler, ui=False):
        assert ui is False

    def publish(self, _topic, **_data):
        return None


class SimpleScheduled:
    def cancel(self):
        return None


class SimpleScheduler:
    def call_later(self, _delay_s, _callback):
        return SimpleScheduled()


def test_stale_disconnect_from_retired_picker_cannot_revoke_newer_target():
    host, created, _threads = _host([("https://safe.test", "Safe")])
    try:
        first_picker = host.begin_picker()
        assert host.cancel_picker(first_picker.picker_id) is True

        second_picker = host.begin_picker()
        selected = host.select_candidate(
            second_picker.picker_id,
            second_picker.candidates[0].candidate_id,
        )
        assert selected.ok is True

        created[0][0].emit("disconnected")

        assert host.active_snapshot().active is True
        assert host.active_snapshot().target_id == selected.target.target_id
    finally:
        host.shutdown()


def test_exactly_one_selection_becomes_active_and_cannot_silently_rebind():
    host, created, _threads = _host(
        [
            ("https://one.test", "One"),
            ("https://two.test", "Two"),
        ]
    )
    try:
        picker = host.begin_picker()
        first, second = picker.candidates
        selected = host.select_candidate(picker.picker_id, first.candidate_id)
        assert selected.ok is True

        rebound = host.select_candidate(picker.picker_id, second.candidate_id)
        assert rebound.ok is False
        assert rebound.state == "sharing"
        active = host.active_snapshot()
        assert active.active is True
        assert active.target_id == selected.target.target_id
        assert active.title == "One"

        owner = created[0][1][0]._owner
        popup = _OwnedPage(owner, "https://popup.test", "Popup")
        created[0][0].context._pages.append(popup)
        still_active = host.active_snapshot()
        assert still_active.target_id == selected.target.target_id
        assert still_active.title == "One"

        assert host.stop_selected(
            selected.target.target_id,
            selected.target.target_generation,
        ) is True
        assert host.active_snapshot().active is False
        assert created[0][0].closed is True
    finally:
        host.shutdown()
