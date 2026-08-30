"""Process-local host for selecting one controllable everyday-Chrome tab.

The host deliberately exposes only immutable local-UI metadata. Every Playwright
sync object remains on one owner thread for its complete lifetime; callers pass
only opaque picker/candidate/target identities across that boundary.
"""
from __future__ import annotations

import asyncio
import inspect
import secrets
import threading
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from jarvis.core import log
from jarvis.integrations import user_browser

_logger = log.get("integrations.selected_tab_browser")


@dataclass(frozen=True)
class LocalTabCandidate:
    candidate_id: str
    title: str
    origin: str


@dataclass(frozen=True)
class SelectedTarget:
    target_id: str
    target_generation: int
    title: str
    origin: str


@dataclass(frozen=True)
class PickerResult:
    ok: bool
    state: str
    reason: str = ""
    picker_id: str = ""
    candidates: tuple[LocalTabCandidate, ...] = ()


@dataclass(frozen=True)
class SelectionResult:
    ok: bool
    state: str
    reason: str = ""
    target: SelectedTarget | None = None


@dataclass(frozen=True)
class ActiveSelectedTabSnapshot:
    active: bool = False
    target_id: str = ""
    target_generation: int = 0
    title: str = ""
    origin: str = ""


@dataclass
class _PickerLease:
    picker_id: str
    connection_id: str
    browser: object
    candidates: dict[str, object]


@dataclass
class _SelectedLease:
    connection_id: str
    browser: object
    page: object
    target: SelectedTarget


def _opaque_id() -> str:
    return secrets.token_urlsafe(24)


async def _connect(port: int):
    from playwright.async_api import async_playwright

    playwright = await async_playwright().start()
    try:
        browser = await playwright.chromium.connect_over_cdp(
            f"http://127.0.0.1:{int(port)}",
            timeout=5_000,
        )
    except Exception:
        await playwright.stop()
        raise
    browser._jarvis_playwright = playwright
    return browser


async def _resolve(value):
    if inspect.isawaitable(value):
        return await value
    return value


async def _release(browser) -> None:
    playwright = getattr(browser, "_jarvis_playwright", None)
    try:
        await _resolve(browser.close())
    except Exception as exc:
        _logger.warning(
            "selected_tab.browser_close_failed",
            error=type(exc).__name__,
        )
    if playwright is not None:
        try:
            await playwright.stop()
        except Exception as exc:
            _logger.warning(
                "selected_tab.playwright_stop_failed",
                error=type(exc).__name__,
            )


def _eligible_origin(raw_url: object) -> str:
    try:
        parsed = urlsplit(str(raw_url or ""))
        scheme = parsed.scheme.casefold()
        hostname = parsed.hostname
        if scheme not in {"http", "https"} or not hostname:
            return ""
        host = hostname.casefold()
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = parsed.port
        default_port = (scheme == "http" and port == 80) or (
            scheme == "https" and port == 443
        )
        authority = host if port is None or default_port else f"{host}:{port}"
        return f"{scheme}://{authority}"
    except (TypeError, ValueError):
        return ""


class SelectedTabBrowserHost:
    """Own one picker or selected target on a dedicated browser thread."""

    def __init__(
        self,
        *,
        connector: Callable[[int], object] | None = None,
        releaser: Callable[[object], None] | None = None,
        enabled_check: Callable[[], bool] | None = None,
        port_provider: Callable[[], int] | None = None,
        unavailable_reason: Callable[[object], str] | None = None,
        id_factory: Callable[[], str] | None = None,
        lifecycle_callback: Callable[[str, int, str], None] | None = None,
    ) -> None:
        self._connector = connector or _connect
        self._releaser = releaser or _release
        self._enabled_check = enabled_check or user_browser.enabled
        self._port_provider = port_provider or user_browser.debug_port
        self._unavailable_reason = unavailable_reason or user_browser._unreachable_reason
        self._id_factory = id_factory or _opaque_id
        self._lifecycle_callback = lifecycle_callback
        self._picker: _PickerLease | None = None
        self._selected: _SelectedLease | None = None
        self._target_generation = 0
        self._closed = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="selected-tab-browser-owner",
        )
        self._thread.start()
        if not self._ready.wait(timeout=2.0):
            self._closed = True
            raise RuntimeError("selected_tab_host_start_timeout")

    def begin_picker(self) -> PickerResult:
        return self._call(self._begin_picker)

    def cancel_picker(self, picker_id: str) -> bool:
        return self._call(self._cancel_picker, str(picker_id or ""))

    def select_candidate(self, picker_id: str, candidate_id: str) -> SelectionResult:
        return self._call(
            self._select_candidate,
            str(picker_id or ""),
            str(candidate_id or ""),
        )

    def active_snapshot(self) -> ActiveSelectedTabSnapshot:
        return self._call(self._active_snapshot)

    def selection_is_active(self, target_id: str, target_generation: int) -> bool:
        snapshot = self.active_snapshot()
        return bool(
            snapshot.active
            and snapshot.target_id == str(target_id or "")
            and snapshot.target_generation == target_generation
        )

    def stop_selected(self, target_id: str, target_generation: int) -> bool:
        return self._call(
            self._stop_selected,
            str(target_id or ""),
            target_generation,
        )

    def shutdown(self) -> None:
        if self._closed:
            return
        loop = self._loop
        try:
            self._call(self._retire_all)
        finally:
            self._closed = True
            if loop is not None:
                loop.call_soon_threadsafe(loop.stop)
            if threading.get_ident() != self._thread.ident:
                self._thread.join(timeout=2.0)

    def _call(self, callback, *args):
        if self._closed:
            if callback == self._active_snapshot:
                return ActiveSelectedTabSnapshot()
            raise RuntimeError("selected_tab_host_stopped")
        if threading.get_ident() == self._thread.ident:
            result = callback(*args)
            if inspect.isawaitable(result):
                raise RuntimeError("selected_tab_owner_reentrant_async_call")
            return result
        loop = self._loop
        if loop is None:
            raise RuntimeError("selected_tab_host_not_ready")
        future = asyncio.run_coroutine_threadsafe(
            self._invoke(callback, args),
            loop,
        )
        return future.result(timeout=10.0)

    @staticmethod
    async def _invoke(callback, args):
        result = callback(*args)
        if inspect.isawaitable(result):
            return await result
        return result

    def _worker(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        try:
            loop.run_forever()
        finally:
            pending = asyncio.all_tasks(loop)
            for task in pending:
                task.cancel()
            if pending:
                loop.run_until_complete(
                    asyncio.gather(*pending, return_exceptions=True)
                )
            loop.close()
            self._loop = None

    async def _begin_picker(self) -> PickerResult:
        if self._selected is not None:
            return PickerResult(False, "sharing", "selected_tab_already_active")
        if self._picker is not None:
            return PickerResult(False, "checking", "selected_tab_picker_active")
        try:
            enabled = bool(self._enabled_check())
            port = int(self._port_provider())
        except Exception:
            enabled = False
            port = 9222
        if not enabled:
            return PickerResult(
                False,
                "unavailable",
                "Akses browser user dimatikan di config (user_browser.enabled).",
            )

        browser = None
        try:
            picker_id = str(self._id_factory() or "")
            if not picker_id:
                raise RuntimeError("selected_tab_picker_id_invalid")
            browser = await _resolve(self._connector(port))
            connection_id = picker_id
            on = getattr(browser, "on", None)
            if callable(on):
                on(
                    "disconnected",
                    lambda *_args: self._on_browser_disconnected(connection_id),
                )
            candidates: dict[str, object] = {}
            local_items: list[LocalTabCandidate] = []
            for context in getattr(browser, "contexts", ()) or ():
                for page in getattr(context, "pages", ()) or ():
                    origin = _eligible_origin(getattr(page, "url", ""))
                    if not origin:
                        continue
                    try:
                        title = str(await _resolve(page.title()) or "")[:160]
                    except Exception:
                        title = ""
                    candidate_id = str(self._id_factory() or "")
                    if not candidate_id or candidate_id in candidates:
                        raise RuntimeError("selected_tab_candidate_id_invalid")
                    candidates[candidate_id] = page
                    local_items.append(LocalTabCandidate(candidate_id, title, origin))
            self._picker = _PickerLease(
                picker_id,
                connection_id,
                browser,
                candidates,
            )
            return PickerResult(
                True,
                "tabs_available" if local_items else "zero_tabs",
                picker_id=picker_id,
                candidates=tuple(local_items),
            )
        except Exception as exc:
            if browser is not None:
                await self._safe_release(browser)
            return PickerResult(
                False,
                "unavailable",
                self._unavailable_reason(exc),
            )

    async def _cancel_picker(self, picker_id: str) -> bool:
        picker = self._picker
        if picker is None or picker.picker_id != picker_id:
            return False
        self._picker = None
        picker.candidates.clear()
        await self._safe_release(picker.browser)
        return True

    async def _select_candidate(self, picker_id: str, candidate_id: str) -> SelectionResult:
        if self._selected is not None:
            return SelectionResult(False, "sharing", "selected_tab_already_active")
        picker = self._picker
        if picker is None:
            return SelectionResult(False, "stopped", "selected_tab_picker_not_active")
        if picker.picker_id != picker_id:
            return SelectionResult(False, "stopped", "selected_tab_picker_mismatch")
        page = picker.candidates.get(candidate_id)
        if page is None:
            return SelectionResult(False, "selected", "selected_tab_candidate_not_found")

        origin = _eligible_origin(getattr(page, "url", ""))
        if not origin:
            return SelectionResult(False, "closed", "selected_tab_candidate_ineligible")
        try:
            title = str(await _resolve(page.title()) or "")[:160]
        except Exception:
            title = ""
        target_id = str(self._id_factory() or "")
        if not target_id:
            return SelectionResult(False, "stopped", "selected_tab_target_id_invalid")
        self._target_generation += 1
        target = SelectedTarget(
            target_id=target_id,
            target_generation=self._target_generation,
            title=title,
            origin=origin,
        )
        self._selected = _SelectedLease(
            picker.connection_id,
            picker.browser,
            page,
            target,
        )
        on = getattr(page, "on", None)
        if callable(on):
            on("close", lambda *_args: self._on_selected_target_closed(target_id))
            on(
                "framenavigated",
                lambda frame: self._on_selected_frame_navigated(
                    target_id,
                    page,
                    frame,
                ),
            )
        picker.candidates.clear()
        self._picker = None
        return SelectionResult(True, "sharing", target=target)

    def _active_snapshot(self) -> ActiveSelectedTabSnapshot:
        selected = self._selected
        if selected is None:
            return ActiveSelectedTabSnapshot()
        target = selected.target
        return ActiveSelectedTabSnapshot(
            True,
            target.target_id,
            target.target_generation,
            target.title,
            target.origin,
        )

    def _on_selected_target_closed(self, target_id: str) -> None:
        self._schedule_owner(
            self._retire_selected_lifecycle,
            target_id,
            "selected_tab_target_closed",
        )

    def _on_selected_frame_navigated(
        self,
        target_id: str,
        page: object,
        frame: object,
    ) -> None:
        if frame is not getattr(page, "main_frame", None):
            return
        selected = self._selected
        if selected is None or selected.target.target_id != target_id:
            return
        origin = _eligible_origin(getattr(frame, "url", ""))
        if not origin:
            reason = "selected_tab_navigation_ineligible"
        elif origin != selected.target.origin:
            reason = "selected_tab_cross_origin_navigation"
        else:
            reason = "selected_tab_target_navigated"
        self._schedule_owner(
            self._retire_selected_lifecycle,
            target_id,
            reason,
        )

    def _on_browser_disconnected(self, connection_id: str) -> None:
        self._schedule_owner(
            self._retire_disconnected_connection,
            connection_id,
        )

    def _schedule_owner(self, callback, *args) -> None:
        loop = self._loop
        if self._closed or loop is None or loop.is_closed():
            return
        if threading.get_ident() == self._thread.ident:
            loop.create_task(self._invoke(callback, args))
            return
        asyncio.run_coroutine_threadsafe(self._invoke(callback, args), loop)

    async def _retire_disconnected_connection(self, connection_id: str) -> None:
        picker = self._picker
        if picker is not None and picker.connection_id == connection_id:
            self._picker = None
            picker.candidates.clear()
            await self._safe_release(picker.browser)
            return
        selected = self._selected
        if selected is None or selected.connection_id != connection_id:
            return
        await self._retire_selected_lifecycle(
            selected.target.target_id,
            "selected_tab_browser_disconnected",
        )

    async def _retire_selected_lifecycle(
        self,
        target_id: str,
        reason: str,
    ) -> None:
        selected = self._selected
        if selected is None or selected.target.target_id != target_id:
            return
        self._selected = None
        await self._safe_release(selected.browser)
        callback = self._lifecycle_callback
        if callback is None:
            return
        target = selected.target
        try:
            await _resolve(
                callback(target.target_id, target.target_generation, reason)
            )
        except Exception as exc:
            _logger.warning(
                "selected_tab.lifecycle_callback_failed",
                error=type(exc).__name__,
            )

    async def _stop_selected(
        self,
        target_id: str,
        target_generation: int,
    ) -> bool:
        selected = self._selected
        if selected is None:
            return False
        target = selected.target
        if (
            target.target_id != target_id
            or target.target_generation != target_generation
        ):
            return False
        self._selected = None
        await self._safe_release(selected.browser)
        return True

    async def _retire_all(self) -> None:
        picker, self._picker = self._picker, None
        selected, self._selected = self._selected, None
        if picker is not None:
            picker.candidates.clear()
            await self._safe_release(picker.browser)
        if selected is not None and (
            picker is None or selected.browser is not picker.browser
        ):
            await self._safe_release(selected.browser)

    async def _safe_release(self, browser: object) -> None:
        try:
            await _resolve(self._releaser(browser))
        except Exception as exc:
            _logger.warning(
                "selected_tab.release_failed",
                error=type(exc).__name__,
            )


def _revoke_screen_control_target(
    target_id: str,
    target_generation: int,
    reason: str,
) -> None:
    from jarvis.ui import screen_control

    screen_control.COORDINATOR.revoke_browser_tab(
        target_id=target_id,
        target_generation=target_generation,
        reason=reason,
    )


_HOST: SelectedTabBrowserHost | None = None
_HOST_LOCK = threading.Lock()


def get_host() -> SelectedTabBrowserHost:
    global _HOST
    with _HOST_LOCK:
        if _HOST is None:
            _HOST = SelectedTabBrowserHost(
                lifecycle_callback=_revoke_screen_control_target,
            )
        return _HOST


def shutdown_host() -> bool:
    global _HOST
    with _HOST_LOCK:
        host, _HOST = _HOST, None
    if host is None:
        return False
    host.shutdown()
    return True


__all__ = [
    "ActiveSelectedTabSnapshot",
    "get_host",
    "shutdown_host",
    "LocalTabCandidate",
    "PickerResult",
    "SelectedTabBrowserHost",
    "SelectedTarget",
    "SelectionResult",
]
