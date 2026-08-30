"""Process-local host for selecting one controllable everyday-Chrome tab.

The host deliberately exposes only immutable local-UI metadata. Every Playwright
async object remains on one continuously serviced owner thread for its complete
lifetime; callers pass only opaque picker/candidate/target identities across that
boundary.
"""
from __future__ import annotations

import asyncio
import inspect
import math
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable
from urllib.parse import urlsplit

from jarvis.automation.cua_safety import CuaSafetyGate, admit_text_entry
from jarvis.core import log
from jarvis.core.element_model import ScreenElementTree, UIElement, elements_from_harvest
from jarvis.integrations import user_browser

_logger = log.get("integrations.selected_tab_browser")
_SEMANTIC_MAX_ELEMENTS = 100
_SEMANTIC_TTL_S = 5.0
_SCROLL_STEP_PX = 240
_ACTION_TIMEOUT_S = 8.0
_SAFE_STATE_KEYS = frozenset({
    "checked", "disabled", "expanded", "focused", "pressed", "selected",
})
_SENSITIVE_TERMS = (
    "password", "kata sandi", "passcode", "pin", "otp", "one time password",
    "verification code", "credential", "credentials", "sign in", "sign-in",
    "signin", "log in", "log-in", "login", "credit card", "debit card",
    "card number", "cvv", "cvc", "payment", "checkout", "bank", "transfer",
    "security code",
)
_PERMISSION_TERMS = (
    "allow camera", "allow microphone", "allow location", "allow notification",
    "permission", "browser settings", "site settings",
)
_DOWNLOAD_TERMS = ("download", "save file", "export file")
_DESTRUCTIVE_ACTION_TERMS = (
    "delete", "remove", "erase", "format", "reset", "wipe", "discard",
    "uninstall", "overwrite", "send", "submit", "purchase", "pay",
    "confirm order",
)
_CLICK_ROLES = frozenset({
    "button", "checkbox", "dropdown", "expander", "link", "menu_item",
    "radio", "switch", "toggle",
})
_SENSITIVE_AUTOCOMPLETE_TERMS = (
    "current-password", "new-password", "one-time-code", "username", "webauthn",
    "cc-",
)
_ALLOWED_ROLES = frozenset({
    "button", "checkbox", "composer", "dropdown", "expander", "link",
    "menu_item", "radio", "search_field", "slider", "switch",
    "text_field", "textarea", "toggle",
})


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


@dataclass(frozen=True)
class SelectedTabElementDescriptor:
    element_id: str
    role: str
    name: str = ""
    label: str = ""
    text: str = ""
    elem_type: str = ""
    states: dict | None = None


@dataclass(frozen=True)
class SelectedTabObservationResult:
    ok: bool
    state: str
    reason: str = ""
    origin: str = ""
    target_generation: int = 0
    document_generation: int = 0
    observation_generation: int = 0
    observation_id: str = ""
    captured_at: float = 0.0
    expires_at: float = 0.0
    elements: tuple[SelectedTabElementDescriptor, ...] = ()


@dataclass(frozen=True)
class SelectedTabPreviewResult:
    ok: bool
    state: str
    reason: str = ""
    preview_id: str = ""
    image_bytes: bytes = b""
    viewport_css: tuple[float, float] = (0.0, 0.0)
    screenshot_px: tuple[int, int] = (0, 0)
    dom_rect: tuple[float, float, float, float] | None = None
    target_generation: int = 0
    document_generation: int = 0
    observation_generation: int = 0
    preview_generation: int = 0
    captured_at: float = 0.0
    expires_at: float = 0.0


@dataclass(frozen=True)
class SelectedTabActionClassification:
    allowed: bool
    requires_confirmation: bool = False
    reason: str = ""


@dataclass(frozen=True)
class SelectedTabActionResult:
    ok: bool
    state: str
    reason: str = ""
    attempted: bool = False
    executed: bool = False
    verified: bool = False
    ambiguous: bool = False
    requires_confirmation: bool = False
    after_observation: SelectedTabObservationResult | None = None
    preview_id: str = ""


@dataclass
class _SemanticRef:
    handle: object
    element: UIElement


@dataclass
class _SemanticObservationLease:
    session_id: str
    task_id: str
    target_id: str
    target_generation: int
    document_generation: int
    observation_generation: int
    observation_id: str
    captured_at: float
    expires_at: float
    gate: CuaSafetyGate
    gate_observation_id: str
    refs: dict[str, _SemanticRef]


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


@dataclass
class _PreviewLease:
    result: SelectedTabPreviewResult


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
    except BaseException:
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


async def _harvest_semantic_records(page: object) -> list[dict]:
    """Read a bounded DOM set and retain each exact ElementHandle process-locally."""
    query = getattr(page, "query_selector_all", None)
    if not callable(query):
        return []
    selector = (
        "a,button,input,textarea,select,[role],[contenteditable='true']"
    )
    handles = list(await _resolve(query(selector)) or ())[:_SEMANTIC_MAX_ELEMENTS]
    records: list[dict] = []
    for handle in handles:
        try:
            if not bool(await _resolve(handle.is_visible())):
                continue
            box = await _resolve(handle.bounding_box())
            if not _valid_box(box):
                continue
            tag = str(await _resolve(handle.evaluate("el => el.tagName.toLowerCase()")) or "")
            role = str(await _resolve(handle.get_attribute("role")) or "")
            elem_type = str(await _resolve(handle.get_attribute("type")) or "")
            autocomplete = str(
                await _resolve(handle.get_attribute("autocomplete")) or ""
            )
            download = await _resolve(handle.get_attribute("download"))
            name = str(await _resolve(handle.get_attribute("aria-label")) or "")
            if not name:
                name = str(await _resolve(handle.get_attribute("name")) or "")
            text = str(await _resolve(handle.inner_text()) or "")[:200]
            editable = bool(await _resolve(handle.is_editable()))
            disabled = bool(await _resolve(handle.is_disabled()))
            checked = await _resolve(handle.is_checked()) if tag == "input" else None
            focused = bool(await _resolve(handle.evaluate("el => el === document.activeElement")))
            container = str(await _resolve(handle.evaluate(
                "el => { const c = el.closest('aside,dialog,header,nav,form,main,footer'); "
                "return c ? c.tagName.toLowerCase() : ''; }"
            )) or "")
        except Exception as exc:
            _logger.debug(
                "selected_tab.semantic_element_skipped",
                error=type(exc).__name__,
            )
            continue
        record = {
            "handle": handle,
            "tag": tag[:32],
            "role": role[:48],
            "type": elem_type[:48],
            "autocomplete": autocomplete[:80],
            "download": download,
            "name": name[:200],
            "label": "",
            "text": text,
            "editable": editable,
            "disabled": disabled,
            "focused": focused,
            "container": container[:32],
            "visible": True,
            "rect": {
                "x": int(round(float(box["x"]))),
                "y": int(round(float(box["y"]))),
                "w": int(round(float(box["width"]))),
                "h": int(round(float(box["height"]))),
            },
        }
        if isinstance(checked, bool):
            record["checked"] = checked
        records.append(record)
    return records


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
        self._disconnected_connections: set[str] = set()
        self._target_generation = 0
        self._document_generation = 0
        self._observation_generation = 0
        self._preview_generation = 0
        self._preview_lease: _PreviewLease | None = None
        self._semantic_observation: _SemanticObservationLease | None = None
        self._semantic_clock = time.monotonic
        self._action_timeout_s = _ACTION_TIMEOUT_S
        self._semantic_id_factory = _opaque_id
        self._semantic_harvester = _harvest_semantic_records
        self._semantic_binding_check = _selected_tab_binding_error
        self._semantic_lock: asyncio.Lock | None = None
        self._closed = False
        self._startup_abandoned = threading.Event()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._thread = threading.Thread(
            target=self._worker,
            daemon=True,
            name="selected-tab-browser-owner",
        )
        self._thread.start()
        if not self._ready.wait(timeout=2.0):
            self._startup_abandoned.set()
            self._closed = True
            self._thread.join(timeout=0.1)
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

    def observe_selected(
        self,
        *,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
    ) -> SelectedTabObservationResult:
        return self._call(
            self._observe_selected,
            str(session_id or "").strip(),
            str(task_id or "").strip(),
            str(target_id or "").strip(),
            target_generation,
        )

    def capture_preview(
        self,
        *,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
        observation_id: str,
        element_id: str,
    ) -> SelectedTabPreviewResult:
        return self._call(
            self._capture_preview,
            str(session_id or "").strip(),
            str(task_id or "").strip(),
            str(target_id or "").strip(),
            target_generation,
            str(observation_id or "").strip(),
            str(element_id or "").strip(),
        )

    def get_preview(self, preview_id: str) -> SelectedTabPreviewResult | None:
        return self._call(self._get_preview, str(preview_id or "").strip())

    def element_ref_is_actionable(
        self,
        *,
        session_id: str,
        task_id: str,
        observation_id: str,
        element_id: str,
        target_id: str,
        target_generation: int,
        document_generation: int,
        observation_generation: int,
    ) -> bool:
        return self._call(
            self._element_ref_is_actionable,
            str(session_id or "").strip(),
            str(task_id or "").strip(),
            str(observation_id or "").strip(),
            str(element_id or "").strip(),
            str(target_id or "").strip(),
            target_generation,
            document_generation,
            observation_generation,
        )

    def classify_action(
        self,
        *,
        action: str,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
        observation_id: str,
        element_id: str,
        text: str = "",
        direction: str = "",
        count: int = 1,
    ) -> SelectedTabActionClassification:
        return self._call(
            self._classify_action,
            str(action or "").casefold().strip(),
            str(session_id or "").strip(),
            str(task_id or "").strip(),
            str(target_id or "").strip(),
            target_generation,
            str(observation_id or "").strip(),
            str(element_id or "").strip(),
            text,
            str(direction or "").casefold().strip(),
            count,
        )

    def act_selected(
        self,
        *,
        action: str,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
        observation_id: str,
        element_id: str,
        text: str = "",
        direction: str = "",
        count: int = 1,
        confirmation: bool = False,
    ) -> SelectedTabActionResult:
        return self._call(
            self._act_selected,
            str(action or "").casefold().strip(),
            str(session_id or "").strip(),
            str(task_id or "").strip(),
            str(target_id or "").strip(),
            target_generation,
            str(observation_id or "").strip(),
            str(element_id or "").strip(),
            text,
            str(direction or "").casefold().strip(),
            count,
            bool(confirmation),
        )

    def clear_semantic_session(self, session_id: str) -> int:
        return self._call(self._clear_semantic_session, str(session_id or "").strip())

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
        try:
            return future.result(timeout=10.0)
        except TimeoutError:
            future.cancel()
            raise

    @staticmethod
    async def _invoke(callback, args):
        result = callback(*args)
        if inspect.isawaitable(result):
            return await result
        return result

    def _worker(self) -> None:
        if self._startup_abandoned.is_set():
            self._ready.set()
            return
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        if self._startup_abandoned.is_set():
            loop.close()
            self._loop = None
            return
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
            if connection_id in self._disconnected_connections:
                candidates.clear()
                await self._safe_release(browser)
                return PickerResult(
                    False,
                    "unavailable",
                    "selected_tab_browser_disconnected",
                )
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
        except asyncio.CancelledError:
            if browser is not None:
                await self._safe_release(browser)
            raise
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

        admitted_origin = _eligible_origin(getattr(page, "url", ""))
        if not admitted_origin:
            return SelectionResult(False, "closed", "selected_tab_candidate_ineligible")
        navigation = {"reason": ""}
        on = getattr(page, "on", None)
        if callable(on):
            on(
                "framenavigated",
                lambda frame: self._guard_selection_navigation(
                    page,
                    frame,
                    admitted_origin,
                    navigation,
                ),
            )
        try:
            title = str(await _resolve(page.title()) or "")[:160]
        except Exception:
            title = ""
        current_picker = self._picker
        if (
            current_picker is not picker
            or picker.connection_id in self._disconnected_connections
        ):
            return SelectionResult(
                False,
                "disconnected",
                "selected_tab_browser_disconnected",
            )
        is_closed = getattr(page, "is_closed", None)
        if callable(is_closed) and bool(await _resolve(is_closed())):
            self._picker = None
            picker.candidates.clear()
            await self._safe_release(picker.browser)
            return SelectionResult(
                False,
                "closed",
                "selected_tab_target_closed",
            )
        current_origin = _eligible_origin(getattr(page, "url", ""))
        navigation_reason = navigation["reason"] or self._navigation_reason(
            admitted_origin,
            current_origin,
        )
        if navigation_reason:
            self._picker = None
            picker.candidates.clear()
            await self._safe_release(picker.browser)
            return SelectionResult(False, "navigated", navigation_reason)
        target_id = str(self._id_factory() or "")
        if not target_id:
            return SelectionResult(False, "stopped", "selected_tab_target_id_invalid")
        self._target_generation += 1
        target = SelectedTarget(
            target_id=target_id,
            target_generation=self._target_generation,
            title=title,
            origin=current_origin,
        )
        self._selected = _SelectedLease(
            picker.connection_id,
            picker.browser,
            page,
            target,
        )
        self._document_generation = 1
        self._retire_semantic_observation()
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

    async def _observe_selected(
        self,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
    ) -> SelectedTabObservationResult:
        async with self._semantic_lifecycle_lock():
            error = await self._selected_binding_error(
                session_id,
                task_id,
                target_id,
                target_generation,
            )
            if error:
                state, reason = error
                return SelectedTabObservationResult(False, state, reason)
            return await self._capture_semantic_observation(
                session_id,
                task_id,
                expose=True,
            )

    def _semantic_lifecycle_lock(self) -> asyncio.Lock:
        lock = self._semantic_lock
        if lock is None:
            lock = asyncio.Lock()
            self._semantic_lock = lock
        return lock

    async def _selected_binding_error(
        self,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
    ) -> tuple[str, str] | None:
        selected = self._selected
        if selected is None:
            return "stopped", "selected_tab_not_active"
        target = selected.target
        if (
            target.target_id != target_id
            or target.target_generation != target_generation
        ):
            return "blocked", "selected_tab_target_mismatch"
        if not session_id or not task_id:
            return "blocked", "selected_tab_runtime_binding_required"
        try:
            binding_error = str(
                self._semantic_binding_check(
                    session_id,
                    task_id,
                    target.target_id,
                    target.target_generation,
                )
                or ""
            )
        except Exception:
            binding_error = "selected_tab_state_unavailable"
        if binding_error:
            return "blocked", binding_error
        if selected.connection_id in self._disconnected_connections:
            return "disconnected", "selected_tab_browser_disconnected"
        is_closed = getattr(selected.page, "is_closed", None)
        if callable(is_closed) and bool(await _resolve(is_closed())):
            self._retire_semantic_observation()
            return "closed", "selected_tab_target_closed"
        origin = _eligible_origin(getattr(selected.page, "url", ""))
        if not origin or origin != target.origin:
            self._retire_semantic_observation()
            return "navigated", "selected_tab_navigation_ineligible"
        return None

    async def _capture_semantic_observation(
        self,
        session_id: str,
        task_id: str,
        *,
        expose: bool,
        preserve_preview: bool = False,
    ) -> SelectedTabObservationResult:
        selected = self._selected
        if selected is None:
            return SelectedTabObservationResult(
                False, "stopped", "selected_tab_not_active"
            )
        target = selected.target
        origin = _eligible_origin(getattr(selected.page, "url", ""))
        if not origin or origin != target.origin:
            self._retire_semantic_observation()
            return SelectedTabObservationResult(
                False, "navigated", "selected_tab_navigation_ineligible"
            )
        try:
            records = list(await _resolve(self._semantic_harvester(selected.page)) or ())
        except Exception as exc:
            self._retire_semantic_observation(
                keep_preview=preserve_preview,
            )
            return SelectedTabObservationResult(
                False,
                "failed",
                f"selected_tab_observation_failed:{type(exc).__name__}",
            )
        now = float(self._semantic_clock())
        gate = CuaSafetyGate(max_age_s=_SEMANTIC_TTL_S)
        tree = ScreenElementTree()
        admitted: list[tuple[UIElement, object]] = []
        bounded_records = []
        for raw in records[:_SEMANTIC_MAX_ELEMENTS]:
            normalized = dict(raw) if isinstance(raw, dict) else {}
            for key, value in dict(normalized.get("states") or {}).items():
                if key in _SAFE_STATE_KEYS:
                    normalized[key] = value
            bounded_records.append(normalized)
        for raw, element in zip(
            bounded_records,
            elements_from_harvest(bounded_records),
            strict=False,
        ):
            states = dict(element.states or {})
            for source, destination in (
                ("class_name", "_uia_class_name"),
                ("automation_id", "_uia_automation_id"),
            ):
                if source in raw:
                    states[destination] = str(raw.get(source, "") or "")[:160]
            element.states = states
            tree.add(element)
            handle = raw.get("handle") if isinstance(raw, dict) else None
            if handle is not None and _semantic_element_allowed(element, raw):
                admitted.append((element, handle))
        gate_observation = gate.observe(
            surface_id=f"selected-tab:{target.target_generation}:{self._document_generation}",
            tree=tree,
            privacy="normal",
            now=now,
        )
        decision = gate.classify_observation(gate_observation)
        self._retire_semantic_observation(
            keep_preview=preserve_preview and decision.allowed,
        )
        self._observation_generation += 1
        if not decision.allowed:
            gate.invalidate(gate_observation.id)
            return SelectedTabObservationResult(
                False,
                "captcha_handoff",
                "selected_tab_captcha_handoff_required",
                origin=origin,
                target_generation=target.target_generation,
                document_generation=self._document_generation,
                observation_generation=self._observation_generation,
                captured_at=now,
                expires_at=now,
            )
        observation_id = str(self._semantic_id_factory() or "")
        if not observation_id:
            gate.invalidate(gate_observation.id)
            return SelectedTabObservationResult(
                False, "failed", "selected_tab_observation_id_invalid"
            )
        refs: dict[str, _SemanticRef] = {}
        descriptors: list[SelectedTabElementDescriptor] = []
        for element, handle in admitted[:_SEMANTIC_MAX_ELEMENTS]:
            opaque_element_id = str(self._semantic_id_factory() or "")
            if not opaque_element_id or opaque_element_id in refs:
                continue
            refs[opaque_element_id] = _SemanticRef(handle, element)
            if expose:
                descriptors.append(_descriptor(opaque_element_id, element))
        expires_at = now + _SEMANTIC_TTL_S
        self._semantic_observation = _SemanticObservationLease(
            session_id=session_id,
            task_id=task_id,
            target_id=target.target_id,
            target_generation=target.target_generation,
            document_generation=self._document_generation,
            observation_generation=self._observation_generation,
            observation_id=observation_id,
            captured_at=now,
            expires_at=expires_at,
            gate=gate,
            gate_observation_id=gate_observation.id,
            refs=refs,
        )
        return SelectedTabObservationResult(
            True,
            "observed",
            origin=origin,
            target_generation=target.target_generation,
            document_generation=self._document_generation,
            observation_generation=self._observation_generation,
            observation_id=observation_id,
            captured_at=now,
            expires_at=expires_at,
            elements=tuple(descriptors),
        )

    async def _capture_preview(
        self,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
        observation_id: str,
        element_id: str,
    ) -> SelectedTabPreviewResult:
        async with self._semantic_lifecycle_lock():
            error = await self._selected_binding_error(
                session_id,
                task_id,
                target_id,
                target_generation,
            )
            if error:
                return SelectedTabPreviewResult(False, error[0], error[1])
            lease = self._semantic_observation
            selected = self._selected
            if lease is None or selected is None:
                return SelectedTabPreviewResult(
                    False,
                    "blocked",
                    "selected_tab_observation_stale",
                )
            try:
                now = float(self._semantic_clock())
            except Exception:
                now = lease.expires_at
            if now >= lease.expires_at:
                self._retire_semantic_observation()
                return SelectedTabPreviewResult(
                    False,
                    "blocked",
                    "selected_tab_observation_expired",
                )
            if (
                lease.session_id != session_id
                or lease.task_id != task_id
                or lease.target_id != target_id
                or lease.target_generation != target_generation
                or lease.observation_id != observation_id
                or lease.document_generation != self._document_generation
                or selected.target.target_id != target_id
                or selected.target.target_generation != target_generation
            ):
                return SelectedTabPreviewResult(
                    False,
                    "blocked",
                    "selected_tab_observation_mismatch",
                )
            ref = lease.refs.get(element_id)
            if ref is None:
                return SelectedTabPreviewResult(
                    False,
                    "blocked",
                    "selected_tab_element_ref_stale",
                )
            return await self._capture_preview_from_ref(
                lease,
                selected,
                ref,
                now=now,
            )

    async def _capture_preview_from_ref(
        self,
        lease: _SemanticObservationLease,
        selected: _SelectedLease,
        ref: _SemanticRef,
        *,
        now: float | None = None,
    ) -> SelectedTabPreviewResult:
        try:
            captured_at = float(self._semantic_clock()) if now is None else float(now)
        except Exception:
            captured_at = lease.expires_at
        if captured_at >= lease.expires_at:
            return SelectedTabPreviewResult(
                False,
                "blocked",
                "selected_tab_observation_expired",
            )
        try:
            if not bool(await _resolve(ref.handle.is_visible())):
                raise RuntimeError("not-visible")
            box = await _resolve(ref.handle.bounding_box())
        except Exception:
            box = None
        if not _valid_box(box):
            return SelectedTabPreviewResult(
                False,
                "blocked",
                "selected_tab_element_not_actionable",
            )
        viewport = _viewport_css_size(selected.page)
        if viewport is None:
            return SelectedTabPreviewResult(
                False,
                "failed",
                "selected_tab_preview_viewport_unavailable",
            )
        screenshot = getattr(selected.page, "screenshot", None)
        if not callable(screenshot):
            return SelectedTabPreviewResult(
                False,
                "failed",
                "selected_tab_preview_capture_unavailable",
            )
        try:
            image_bytes = bytes(
                await _resolve(screenshot(full_page=False, type="png")) or b""
            )
            screenshot_px = _png_dimensions(image_bytes)
        except Exception:
            image_bytes = b""
            screenshot_px = None
        if screenshot_px is None:
            return SelectedTabPreviewResult(
                False,
                "failed",
                "selected_tab_preview_capture_failed",
            )
        scale_x = screenshot_px[0] / viewport[0]
        scale_y = screenshot_px[1] / viewport[1]
        if not math.isclose(
            scale_x,
            scale_y,
            rel_tol=0.01,
            abs_tol=1e-6,
        ):
            return SelectedTabPreviewResult(
                False,
                "failed",
                "selected_tab_preview_scale_mismatch",
            )
        self._preview_generation += 1
        preview_id = str(self._semantic_id_factory() or "")
        if not preview_id:
            self._retire_preview()
            return SelectedTabPreviewResult(
                False,
                "failed",
                "selected_tab_preview_id_invalid",
            )
        result = SelectedTabPreviewResult(
            True,
            "previewed",
            preview_id=preview_id,
            image_bytes=image_bytes,
            viewport_css=viewport,
            screenshot_px=screenshot_px,
            dom_rect=(
                float(box["x"]),
                float(box["y"]),
                float(box["width"]),
                float(box["height"]),
            ),
            target_generation=lease.target_generation,
            document_generation=lease.document_generation,
            observation_generation=lease.observation_generation,
            preview_generation=self._preview_generation,
            captured_at=captured_at,
            expires_at=lease.expires_at,
        )
        self._retire_preview()
        self._preview_lease = _PreviewLease(result)
        return result

    def _get_preview(self, preview_id: str) -> SelectedTabPreviewResult | None:
        lease = self._preview_lease
        if lease is None or lease.result.preview_id != preview_id:
            return None
        try:
            now = float(self._semantic_clock())
        except Exception:
            now = lease.result.expires_at
        if now >= lease.result.expires_at:
            self._retire_preview()
            return None
        return lease.result

    async def _classify_action(
        self,
        action: str,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
        observation_id: str,
        element_id: str,
        text: str,
        direction: str,
        count: int,
    ) -> SelectedTabActionClassification:
        async with self._semantic_lifecycle_lock():
            error = await self._selected_binding_error(
                session_id,
                task_id,
                target_id,
                target_generation,
            )
            if error:
                return SelectedTabActionClassification(False, reason=error[1])
            admission, _lease, _ref = await self._action_admission(
                action,
                session_id,
                task_id,
                target_id,
                target_generation,
                observation_id,
                element_id,
                text,
                direction,
                count,
            )
            return admission

    async def _action_admission(
        self,
        action: str,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
        observation_id: str,
        element_id: str,
        text: str,
        direction: str,
        count: int,
    ) -> tuple[
        SelectedTabActionClassification,
        _SemanticObservationLease | None,
        _SemanticRef | None,
    ]:
        lease = self._semantic_observation
        selected = self._selected
        if lease is None or selected is None:
            return (
                SelectedTabActionClassification(False, reason="selected_tab_observation_stale"),
                None,
                None,
            )
        try:
            now = float(self._semantic_clock())
        except Exception:
            now = lease.expires_at
        if now >= lease.expires_at:
            self._retire_semantic_observation()
            return (
                SelectedTabActionClassification(False, reason="selected_tab_observation_expired"),
                None,
                None,
            )
        if (
            lease.session_id != session_id
            or lease.task_id != task_id
            or lease.observation_id != observation_id
            or lease.target_id != target_id
            or lease.target_generation != target_generation
            or lease.document_generation != self._document_generation
            or selected.target.target_id != target_id
            or selected.target.target_generation != target_generation
        ):
            return (
                SelectedTabActionClassification(False, reason="selected_tab_observation_mismatch"),
                None,
                None,
            )
        ref = lease.refs.get(element_id)
        if ref is None:
            return (
                SelectedTabActionClassification(False, reason="selected_tab_element_ref_stale"),
                None,
                None,
            )
        try:
            semantic_ref = lease.gate.reference(
                lease.gate_observation_id,
                ref.element.element_id,
                now=lease.captured_at,
            )
            decision = lease.gate.evaluate(
                semantic_ref,
                action=action,
                now=lease.captured_at,
            )
        except Exception:
            return (
                SelectedTabActionClassification(False, reason="selected_tab_element_ref_unsafe"),
                None,
                None,
            )
        if not decision.allowed:
            return (
                SelectedTabActionClassification(False, reason="selected_tab_action_blocked"),
                None,
                None,
            )
        label = " ".join(
            f"{ref.element.name} {ref.element.label} {ref.element.text} "
            f"{ref.element.elem_type}".casefold().split()
        )[:600]
        if any(term in label for term in _SENSITIVE_TERMS):
            return (
                SelectedTabActionClassification(False, reason="selected_tab_sensitive_target"),
                None,
                None,
            )
        requires_confirmation = bool(
            decision.requires_confirmation
            or any(term in label for term in _DESTRUCTIVE_ACTION_TERMS)
        )
        if action == "click":
            if ref.element.role not in _CLICK_ROLES:
                return (
                    SelectedTabActionClassification(False, reason="selected_tab_click_role_blocked"),
                    None,
                    None,
                )
        elif action == "type":
            text_admission = admit_text_entry(ref.element, text)
            if not text_admission.allowed:
                return (
                    SelectedTabActionClassification(False, reason="selected_tab_type_blocked"),
                    None,
                    None,
                )
        elif action == "scroll":
            if direction not in {"up", "down"} or type(count) is not int or not 1 <= count <= 5:
                return (
                    SelectedTabActionClassification(False, reason="selected_tab_scroll_bounds_invalid"),
                    None,
                    None,
                )
        else:
            return (
                SelectedTabActionClassification(False, reason="selected_tab_action_unsupported"),
                None,
                None,
            )
        try:
            if not bool(await _resolve(ref.handle.is_visible())):
                raise RuntimeError("not-visible")
            box = await _resolve(ref.handle.bounding_box())
        except Exception:
            box = None
        if not _valid_box(box):
            return (
                SelectedTabActionClassification(False, reason="selected_tab_element_not_actionable"),
                None,
                None,
            )
        return (
            SelectedTabActionClassification(
                True,
                requires_confirmation=requires_confirmation,
                reason=(
                    "selected_tab_confirmation_required"
                    if requires_confirmation
                    else "selected_tab_action_allowed"
                ),
            ),
            lease,
            ref,
        )

    async def _act_selected(
        self,
        action: str,
        session_id: str,
        task_id: str,
        target_id: str,
        target_generation: int,
        observation_id: str,
        element_id: str,
        text: str,
        direction: str,
        count: int,
        confirmation: bool,
    ) -> SelectedTabActionResult:
        async with self._semantic_lifecycle_lock():
            error = await self._selected_binding_error(
                session_id,
                task_id,
                target_id,
                target_generation,
            )
            if error:
                return _blocked_action(error[1])
            admission, lease, ref = await self._action_admission(
                action,
                session_id,
                task_id,
                target_id,
                target_generation,
                observation_id,
                element_id,
                text,
                direction,
                count,
            )
            if not admission.allowed:
                return _blocked_action(admission.reason)
            if admission.requires_confirmation and not confirmation:
                return SelectedTabActionResult(
                    False,
                    "confirmation_required",
                    "selected_tab_confirmation_required",
                    requires_confirmation=True,
                )
            if lease is None or ref is None:
                return _blocked_action("selected_tab_element_ref_stale")
            selected = self._selected
            if selected is None:
                return _blocked_action("selected_tab_not_active")
            page = selected.page
            before_click_state = None
            before_scroll = None
            if action == "click":
                before_click_state = await _read_click_state(ref.handle)
            elif action == "scroll":
                try:
                    before_scroll = await _read_scroll_y(page)
                except Exception:
                    return _blocked_action("selected_tab_scroll_state_unavailable")
            preview = await self._capture_preview_from_ref(
                lease,
                selected,
                ref,
            )
            preview_id = preview.preview_id if preview.ok else ""
            action_document_generation = self._document_generation
            action_connection_id = selected.connection_id
            self._retire_semantic_observation(keep_preview=bool(preview_id))
            attempted = True
            try:
                if action == "click":
                    operation = ref.handle.click()
                elif action == "type":
                    operation = ref.handle.fill(text)
                else:
                    delta = _SCROLL_STEP_PX * count * (1 if direction == "down" else -1)
                    operation = page.mouse.wheel(0, delta)
                await asyncio.wait_for(
                    _resolve(operation),
                    timeout=float(self._action_timeout_s),
                )
            except Exception:
                return SelectedTabActionResult(
                    False,
                    "attempt_ambiguous",
                    "selected_tab_action_attempt_ambiguous",
                    attempted=attempted,
                    ambiguous=True,
                    preview_id=preview_id,
                )
            executed = True
            boundary_reason = await self._post_action_boundary_reason(
                selected,
                target_id,
                target_generation,
                action_document_generation,
                action_connection_id,
            )
            if boundary_reason:
                return _executed_unverified_action(
                    boundary_reason,
                    preview_id=preview_id,
                )
            verified = False
            if action == "click":
                try:
                    after_click_state = await _read_click_state(ref.handle)
                    verified = _click_state_changed(before_click_state, after_click_state)
                except Exception:
                    verified = False
            elif action == "type":
                try:
                    verified = str(await _resolve(ref.handle.input_value())) == text
                except Exception:
                    verified = False
            else:
                try:
                    after_scroll = await _read_scroll_y(page)
                    verified = bool(
                        before_scroll is not None
                        and (
                            (direction == "down" and after_scroll > before_scroll)
                            or (direction == "up" and after_scroll < before_scroll)
                        )
                    )
                except Exception:
                    verified = False
            try:
                after = await self._capture_semantic_observation(
                    session_id,
                    task_id,
                    expose=True,
                    preserve_preview=bool(preview_id),
                )
            except Exception:
                after = SelectedTabObservationResult(
                    False,
                    "failed",
                    "selected_tab_post_action_capture_failed",
                )
            if not after.ok:
                reason = (
                    "selected_tab_captcha_handoff_required"
                    if after.state == "captcha_handoff"
                    else "selected_tab_post_action_capture_failed"
                )
                return SelectedTabActionResult(
                    False,
                    after.state,
                    reason,
                    attempted=True,
                    executed=executed,
                    ambiguous=True,
                    after_observation=None,
                    preview_id=(
                        "" if after.state == "captcha_handoff" else preview_id
                    ),
                )
            if not verified:
                return SelectedTabActionResult(
                    False,
                    "executed_unverified",
                    "selected_tab_action_executed_unverified",
                    attempted=True,
                    executed=True,
                    ambiguous=True,
                    after_observation=after,
                    preview_id=preview_id,
                )
            return SelectedTabActionResult(
                True,
                "verified",
                "selected_tab_action_verified",
                attempted=True,
                executed=True,
                verified=True,
                after_observation=after,
                preview_id=preview_id,
            )

    async def _post_action_boundary_reason(
        self,
        selected: _SelectedLease,
        target_id: str,
        target_generation: int,
        document_generation: int,
        connection_id: str,
    ) -> str:
        current = self._selected
        if current is not selected:
            return "selected_tab_target_revoked_during_action"
        target = current.target
        if (
            target.target_id != target_id
            or target.target_generation != target_generation
        ):
            return "selected_tab_target_changed_during_action"
        if self._document_generation != document_generation:
            return "selected_tab_navigation_during_action"
        if (
            current.connection_id != connection_id
            or connection_id in self._disconnected_connections
        ):
            return "selected_tab_disconnect_during_action"
        is_closed = getattr(current.page, "is_closed", None)
        try:
            if callable(is_closed) and bool(await _resolve(is_closed())):
                return "selected_tab_close_during_action"
        except Exception:
            return "selected_tab_target_state_ambiguous"
        return ""

    async def _element_ref_is_actionable(
        self,
        session_id: str,
        task_id: str,
        observation_id: str,
        element_id: str,
        target_id: str,
        target_generation: int,
        document_generation: int,
        observation_generation: int,
    ) -> bool:
        lease = self._semantic_observation
        selected = self._selected
        if lease is None or selected is None:
            return False
        if float(self._semantic_clock()) >= lease.expires_at:
            self._retire_semantic_observation()
            return False
        if (
            lease.session_id != session_id
            or lease.task_id != task_id
            or lease.observation_id != observation_id
            or lease.target_id != target_id
            or lease.target_generation != target_generation
            or lease.document_generation != document_generation
            or lease.observation_generation != observation_generation
            or selected.target.target_id != target_id
            or selected.target.target_generation != target_generation
            or self._document_generation != document_generation
        ):
            return False
        ref = lease.refs.get(element_id)
        if ref is None:
            return False
        try:
            if not bool(await _resolve(ref.handle.is_visible())):
                return False
            box = await _resolve(ref.handle.bounding_box())
        except Exception:
            return False
        return _valid_box(box)

    async def _clear_semantic_session(self, session_id: str) -> int:
        async with self._semantic_lifecycle_lock():
            lease = self._semantic_observation
            if lease is None or lease.session_id != session_id:
                return 0
            self._retire_semantic_observation()
            return 1

    def _retire_semantic_observation(self, *, keep_preview: bool = False) -> None:
        if not keep_preview:
            self._retire_preview()
        lease, self._semantic_observation = self._semantic_observation, None
        if lease is None:
            return
        lease.refs.clear()
        lease.gate.invalidate(lease.gate_observation_id)

    def _retire_preview(self) -> None:
        self._preview_lease = None

    @staticmethod
    def _navigation_reason(admitted_origin: str, current_origin: str) -> str:
        if not current_origin:
            return "selected_tab_navigation_ineligible"
        if current_origin != admitted_origin:
            return "selected_tab_cross_origin_navigation"
        return ""

    def _guard_selection_navigation(
        self,
        page: object,
        frame: object,
        admitted_origin: str,
        navigation: dict[str, str],
    ) -> None:
        if frame is not getattr(page, "main_frame", None):
            return
        current_origin = _eligible_origin(getattr(frame, "url", ""))
        navigation["reason"] = self._navigation_reason(
            admitted_origin,
            current_origin,
        ) or "selected_tab_target_navigated"

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
        self._document_generation += 1
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
        self._disconnected_connections.add(connection_id)
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
        async with self._semantic_lifecycle_lock():
            self._disconnected_connections.add(connection_id)
            picker = self._picker
            if picker is not None and picker.connection_id == connection_id:
                self._picker = None
                picker.candidates.clear()
                await self._safe_release(picker.browser)
                return
            selected = self._selected
            if selected is None or selected.connection_id != connection_id:
                return
            await self._retire_selected_lifecycle_locked(
                selected.target.target_id,
                "selected_tab_browser_disconnected",
            )

    async def _retire_selected_lifecycle(
        self,
        target_id: str,
        reason: str,
    ) -> None:
        async with self._semantic_lifecycle_lock():
            await self._retire_selected_lifecycle_locked(target_id, reason)

    async def _retire_selected_lifecycle_locked(
        self,
        target_id: str,
        reason: str,
    ) -> None:
        selected = self._selected
        if selected is None or selected.target.target_id != target_id:
            return
        self._selected = None
        self._retire_semantic_observation()
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
        async with self._semantic_lifecycle_lock():
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
            self._retire_semantic_observation()
            await self._safe_release(selected.browser)
            return True

    async def _retire_all(self) -> None:
        async with self._semantic_lifecycle_lock():
            picker, self._picker = self._picker, None
            selected, self._selected = self._selected, None
            self._retire_semantic_observation()
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


def _blocked_action(reason: str) -> SelectedTabActionResult:
    return SelectedTabActionResult(False, "blocked", str(reason or "selected_tab_action_blocked"))


def _executed_unverified_action(
    reason: str,
    *,
    preview_id: str = "",
) -> SelectedTabActionResult:
    return SelectedTabActionResult(
        False,
        "executed_unverified",
        str(reason or "selected_tab_action_executed_unverified"),
        attempted=True,
        executed=True,
        ambiguous=True,
        preview_id=preview_id,
    )


async def _read_scroll_y(page: object) -> float:
    evaluate = getattr(page, "evaluate", None)
    if not callable(evaluate):
        raise RuntimeError("selected_tab_scroll_sampler_unavailable")
    value = float(await _resolve(evaluate("() => window.scrollY")))
    if not math.isfinite(value):
        raise RuntimeError("selected_tab_scroll_state_invalid")
    return value


async def _read_click_state(handle: object) -> dict[str, object]:
    evaluate = getattr(handle, "evaluate", None)
    if not callable(evaluate):
        return {}
    try:
        raw = await _resolve(evaluate(
            "el => ({ checked: typeof el.checked === 'boolean' ? el.checked : null, "
            "selected: typeof el.selected === 'boolean' ? el.selected : null, "
            "expanded: el.getAttribute('aria-expanded'), "
            "pressed: el.getAttribute('aria-pressed'), "
            "value: 'value' in el ? String(el.value) : null })"
        ))
    except Exception:
        return {}
    if not isinstance(raw, dict):
        return {}
    return {
        key: raw.get(key)
        for key in ("checked", "selected", "expanded", "pressed", "value")
        if raw.get(key) is not None
    }


def _click_state_changed(before: object, after: object) -> bool:
    if not isinstance(before, dict) or not isinstance(after, dict):
        return False
    return any(
        key in before and key in after and before[key] != after[key]
        for key in ("checked", "selected", "expanded", "pressed", "value")
    )


def _valid_box(box: object) -> bool:
    if not isinstance(box, dict):
        return False
    try:
        values = tuple(float(box[key]) for key in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError):
        return False
    return all(math.isfinite(value) for value in values) and values[2] >= 2 and values[3] >= 2


def _viewport_css_size(page: object) -> tuple[float, float] | None:
    viewport = getattr(page, "viewport_size", None)
    if not isinstance(viewport, dict):
        return None
    try:
        width = float(viewport["width"])
        height = float(viewport["height"])
    except (KeyError, TypeError, ValueError):
        return None
    if not all(math.isfinite(value) and value > 0 for value in (width, height)):
        return None
    return width, height


def _png_dimensions(data: bytes) -> tuple[int, int] | None:
    if len(data) < 24 or data[:8] != b"\x89PNG\r\n\x1a\n" or data[12:16] != b"IHDR":
        return None
    width = int.from_bytes(data[16:20], "big")
    height = int.from_bytes(data[20:24], "big")
    if width <= 0 or height <= 0:
        return None
    return width, height


def _bounded(value: object, limit: int) -> str:
    return " ".join(str(value or "").split())[:limit]


def _semantic_element_allowed(element: UIElement, raw: dict) -> bool:
    if element.role not in _ALLOWED_ROLES or element.role in {"unknown", "upload"}:
        return False
    if not element.visible or bool(element.states.get("disabled")):
        return False
    elem_type = str(element.elem_type or "").casefold()
    if elem_type in {"file", "password", "hidden"}:
        return False
    autocomplete = str(raw.get("autocomplete", "") or "").casefold()
    if any(term in autocomplete for term in _SENSITIVE_AUTOCOMPLETE_TERMS):
        return False
    label = f" {element.name} {element.label} {element.text} {elem_type} ".casefold()
    if any(term in label for term in _SENSITIVE_TERMS):
        return False
    if any(term in label for term in _PERMISSION_TERMS):
        return False
    if raw.get("download") is not None or any(term in label for term in _DOWNLOAD_TERMS):
        return False
    return _valid_rect(element.rect)


def _valid_rect(rect: object) -> bool:
    if not isinstance(rect, tuple) or len(rect) != 4:
        return False
    try:
        values = tuple(float(value) for value in rect)
    except (TypeError, ValueError):
        return False
    return all(math.isfinite(value) for value in values) and values[2] >= 2 and values[3] >= 2


def _descriptor(element_id: str, element: UIElement) -> SelectedTabElementDescriptor:
    states = {
        str(key): bool(value)
        for key, value in dict(element.states or {}).items()
        if str(key) in _SAFE_STATE_KEYS and isinstance(value, bool)
    }
    return SelectedTabElementDescriptor(
        element_id=element_id,
        role=_bounded(element.role, 48),
        name=_bounded(element.name, 160),
        label=_bounded(element.label, 160),
        text=_bounded(element.text, 200),
        elem_type=_bounded(element.elem_type, 48),
        states=states,
    )


def _selected_tab_binding_error(
    session_id: str,
    task_id: str,
    target_id: str,
    target_generation: int,
) -> str:
    from jarvis.ui import screen_control

    return screen_control.COORDINATOR.selected_tab_binding_error(
        session_id=session_id,
        task_id=task_id,
        target_id=target_id,
        target_generation=target_generation,
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
    "SelectedTabActionClassification",
    "SelectedTabActionResult",
    "SelectedTabBrowserHost",
    "SelectedTabElementDescriptor",
    "SelectedTabObservationResult",
    "SelectedTabPreviewResult",
    "SelectedTarget",
    "SelectionResult",
]
