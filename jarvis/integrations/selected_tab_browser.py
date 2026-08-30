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

from jarvis.automation.cua_safety import CuaSafetyGate
from jarvis.core import log
from jarvis.core.element_model import ScreenElementTree, UIElement, elements_from_harvest
from jarvis.integrations import user_browser

_logger = log.get("integrations.selected_tab_browser")
_SEMANTIC_MAX_ELEMENTS = 100
_SEMANTIC_TTL_S = 5.0
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
        self._semantic_observation: _SemanticObservationLease | None = None
        self._semantic_clock = time.monotonic
        self._semantic_id_factory = _opaque_id
        self._semantic_harvester = _harvest_semantic_records
        self._semantic_binding_check = _selected_tab_binding_error
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
        selected = self._selected
        if selected is None:
            return SelectedTabObservationResult(
                False, "stopped", "selected_tab_not_active"
            )
        target = selected.target
        if (
            target.target_id != target_id
            or target.target_generation != target_generation
        ):
            return SelectedTabObservationResult(
                False, "blocked", "selected_tab_target_mismatch"
            )
        if not session_id or not task_id:
            return SelectedTabObservationResult(
                False, "blocked", "selected_tab_runtime_binding_required"
            )
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
            return SelectedTabObservationResult(False, "blocked", binding_error)
        if selected.connection_id in self._disconnected_connections:
            return SelectedTabObservationResult(
                False, "disconnected", "selected_tab_browser_disconnected"
            )
        is_closed = getattr(selected.page, "is_closed", None)
        if callable(is_closed) and bool(await _resolve(is_closed())):
            self._retire_semantic_observation()
            return SelectedTabObservationResult(
                False, "closed", "selected_tab_target_closed"
            )
        origin = _eligible_origin(getattr(selected.page, "url", ""))
        if not origin or origin != target.origin:
            self._retire_semantic_observation()
            return SelectedTabObservationResult(
                False, "navigated", "selected_tab_navigation_ineligible"
            )
        try:
            records = list(await _resolve(self._semantic_harvester(selected.page)) or ())
        except Exception as exc:
            self._retire_semantic_observation()
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
        self._retire_semantic_observation()
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

    def _clear_semantic_session(self, session_id: str) -> int:
        lease = self._semantic_observation
        if lease is None or lease.session_id != session_id:
            return 0
        self._retire_semantic_observation()
        return 1

    def _retire_semantic_observation(self) -> None:
        lease, self._semantic_observation = self._semantic_observation, None
        if lease is None:
            return
        lease.refs.clear()
        lease.gate.invalidate(lease.gate_observation_id)

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
        self._retire_semantic_observation()
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


def _valid_box(box: object) -> bool:
    if not isinstance(box, dict):
        return False
    try:
        values = tuple(float(box[key]) for key in ("x", "y", "width", "height"))
    except (KeyError, TypeError, ValueError):
        return False
    return all(math.isfinite(value) for value in values) and values[2] >= 2 and values[3] >= 2


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
    "SelectedTabBrowserHost",
    "SelectedTabElementDescriptor",
    "SelectedTabObservationResult",
    "SelectedTarget",
    "SelectionResult",
]
