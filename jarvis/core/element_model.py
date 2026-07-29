"""Semantic UI-element model (redesign §8/§10/§11).

One authoritative, *scoped* model of everything interactive that J.A.R.V.I.S
can currently see: OS window controls, browser chrome, and page content are
never flattened into one unscoped list — every element carries its scope in
the Desktop → Window → Chrome → Page hierarchy, plus role, name, bounds,
state, confidence, provenance, and a stale flag.

Recognition sources feed this model in priority order:
  1. DOM / Chromium accessibility (``elements_from_harvest`` — provenance
     "dom", produced by BrowserAgentView's JS harvest).
  2. Qt widget metadata (provenance "qt" — J.A.R.V.I.S-owned windows).
  3. Geometry + icon detection (``classify_detections`` — provenance
     "geometry"/"icon", used for OS/browser chrome outside the embedded
     view and for the screenshot-fixture pipeline).
  4. OCR / coordinate-only fallback (provenance "ocr", lowest confidence).

Nothing in this module performs I/O or touches Qt — it is a pure, headless
model so every classification rule is unit-testable, and interaction code
elsewhere must go through ``ScreenElementTree.actionable()`` which refuses
stale or low-confidence elements outright.
"""
from __future__ import annotations

import itertools
import time
from dataclasses import dataclass, field
from enum import Enum

from jarvis.core import config


class ElementScope(str, Enum):
    """Position in the Desktop → Window → Chrome → Page hierarchy."""

    WINDOW_CHROME = "window_chrome"           # OS title-bar controls
    BROWSER_TAB_STRIP = "browser_tab_strip"
    BROWSER_NAV = "browser_nav"               # back/forward/reload/menu row
    BROWSER_ADDRESS = "browser_address"        # address field + site info
    PAGE_HEADER = "page_header"
    PAGE_MAIN = "page_main"
    PAGE_COMPOSER = "page_composer"            # main input/composer region
    PAGE_SIDEBAR = "page_sidebar"              # assistant/side panel (own composer)
    PAGE_DIALOG = "page_dialog"
    UNKNOWN = "unknown"


# Roles this model normalizes to. Free-form strings are allowed for page
# content, but chrome-level roles come from this set so tests and callers
# can rely on exact semantics (minimize is never "some x-ish button").
KNOWN_ROLES = {
    "minimize", "maximize", "restore", "close",
    "tab", "tab_close", "new_tab", "tab_actions", "browser_menu_icon",
    "back", "forward", "reload", "stop", "home", "site_info", "address",
    "bookmark", "translate", "extensions", "menu", "profile", "chat",
    "title", "button", "link", "menu_item", "text_field", "search_field",
    "textarea", "composer", "checkbox", "radio", "switch", "dropdown",
    "slider", "dialog_control", "upload", "media_control", "scrollbar",
    "expander", "toolbar", "sidebar", "card", "pagination", "send",
    "attachment", "quick_action", "unknown",
}

_ids = itertools.count(1)


@dataclass
class UIElement:
    element_id: str
    scope: ElementScope
    role: str
    name: str = ""
    label: str = ""
    text: str = ""
    elem_type: str = ""
    states: dict = field(default_factory=dict)   # selected/checked/expanded/disabled/focused
    rect: tuple[int, int, int, int] = (0, 0, 0, 0)
    visible: bool = True
    confidence: float = 0.0
    provenance: str = "geometry"
    timestamp: float = field(default_factory=time.time)
    stale: bool = False
    page_id: str = ""
    frame_id: str = ""

    @property
    def uncertain(self) -> bool:
        """Ambiguous elements are marked uncertain rather than being given
        invented exact semantics (redesign §10 acceptance)."""
        return self.role == "unknown" or self.confidence < 0.5


class ScreenElementTree:
    """Scope-preserving container. There is deliberately no method that
    returns one flat unscoped list mixing window chrome with page buttons —
    consumers query by scope, and every result still carries its scope."""

    def __init__(self):
        self._by_scope: dict[ElementScope, list[UIElement]] = {}
        self._by_id: dict[str, UIElement] = {}
        self._min_conf = float(config.get(
            "awareness.element_recognition.min_confidence", 0.35))
        self._stale_after_s = float(config.get(
            "awareness.element_recognition.stale_after_s", 10))

    def add(self, el: UIElement) -> None:
        self._by_scope.setdefault(el.scope, []).append(el)
        self._by_id[el.element_id] = el

    def scopes(self) -> list[ElementScope]:
        return list(self._by_scope.keys())

    def by_scope(self, scope: ElementScope) -> list[UIElement]:
        return list(self._by_scope.get(scope, ()))

    def find(self, scope: ElementScope | None = None, role: str | None = None,
             text_contains: str | None = None) -> list[UIElement]:
        pools = ([self._by_scope.get(scope, ())] if scope is not None
                 else self._by_scope.values())
        out = []
        for pool in pools:
            for el in pool:
                if role is not None and el.role != role:
                    continue
                if text_contains is not None:
                    hay = f"{el.name} {el.label} {el.text}".lower()
                    if text_contains.lower() not in hay:
                        continue
                out.append(el)
        return out

    def invalidate(self, reason: str = "") -> None:
        """Navigation, resize, scroll, zoom, tab or monitor changes make every
        recorded bound stale — nothing may act on them afterwards."""
        for el in self._by_id.values():
            el.stale = True

    def actionable(self, element_id: str) -> UIElement | None:
        """The single gate interaction code must use: refuses stale,
        expired, invisible, or low-confidence elements (redesign §8)."""
        el = self._by_id.get(element_id)
        if el is None or el.stale or not el.visible:
            return None
        if el.confidence < self._min_conf:
            return None
        if time.time() - el.timestamp > self._stale_after_s:
            el.stale = True
            return None
        return el


# ── source 1: DOM harvest (BrowserAgentView) ─────────────────────────────

_CONTAINER_SCOPE = {
    "aside": ElementScope.PAGE_SIDEBAR,
    "header": ElementScope.PAGE_HEADER,
    "nav": ElementScope.PAGE_HEADER,
    "dialog": ElementScope.PAGE_DIALOG,
    "form": ElementScope.PAGE_COMPOSER,
    "footer": ElementScope.PAGE_MAIN,
    "main": ElementScope.PAGE_MAIN,
}

_TAG_ROLE = {
    "a": "link", "button": "button", "select": "dropdown",
    "textarea": "textarea", "input": "text_field",
}

_INPUT_TYPE_ROLE = {
    "checkbox": "checkbox", "radio": "radio", "range": "slider",
    "search": "search_field", "file": "upload", "submit": "button",
    "button": "button", "password": "text_field",
}


def elements_from_harvest(items: list[dict], page_id: str = "",
                          frame_id: str = "") -> list[UIElement]:
    """Normalize the JSON produced by the in-page harvest script into
    UIElements with provenance "dom"."""
    out: list[UIElement] = []
    now = time.time()
    for it in items:
        tag = str(it.get("tag", "")).lower()
        aria_role = str(it.get("role", "")).lower()
        input_type = str(it.get("type", "")).lower()
        editable = bool(it.get("editable"))
        container = str(it.get("container", "")).lower()

        role = (aria_role if aria_role in KNOWN_ROLES else "")
        if not role and tag == "input":
            role = _INPUT_TYPE_ROLE.get(input_type, "text_field")
        if not role:
            role = _TAG_ROLE.get(tag, "")
        if editable and role in ("", "textarea", "text_field"):
            role = "composer"
        if not role:
            role = "unknown"

        scope = _CONTAINER_SCOPE.get(container, ElementScope.PAGE_MAIN)
        if role in ("composer", "textarea") and scope is ElementScope.PAGE_MAIN:
            scope = ElementScope.PAGE_COMPOSER

        r = it.get("rect", {}) or {}
        name = str(it.get("name", "") or it.get("label", ""))
        conf = 0.9 if name else 0.8
        out.append(UIElement(
            element_id=f"dom-{next(_ids)}",
            scope=scope, role=role, name=name,
            label=str(it.get("label", "")), text=str(it.get("text", ""))[:200],
            elem_type=input_type or tag,
            states={k: bool(it.get(k)) for k in
                    ("disabled", "checked", "focused", "selected", "expanded")
                    if k in it},
            rect=(int(r.get("x", 0)), int(r.get("y", 0)),
                  int(r.get("w", 0)), int(r.get("h", 0))),
            visible=bool(it.get("visible", True)),
            confidence=conf, provenance="dom", timestamp=now,
            page_id=page_id, frame_id=frame_id))
    return out


# ── source 3: geometry + icon classification (fixture pipeline) ──────────

_WINDOW_ICON_ROLE = {"hline": "minimize", "square": "maximize",
                     "overlap_square": "restore", "x": "close"}

_NAV_ICON_ROLE = {
    "arrow_left": "back", "arrow_right": "forward",
    "circular_arrow": "reload", "square": "stop", "house": "home",
    "lock": "site_info", "tune": "site_info", "star": "bookmark",
    "translate": "translate", "puzzle": "extensions", "dots3": "menu",
    "avatar": "profile", "chat": "chat",
}

_CONF_BY_SOURCE = {"dom": 0.9, "uia": 0.9, "qt": 0.95,
                   "geometry": 0.7, "ocr": 0.6, "icon": 0.55}


def classify_detections(detections: list[dict], viewport: dict) -> ScreenElementTree:
    """Assign scope + role + confidence + provenance to raw detections
    (each: rect, optional icon/text/type/container/source/states hints).

    Scope comes first — an "x" icon in the top-right corner strip is a
    window close control; the same icon inside a tab's bounds is that tab's
    close button; inside the page it is a generic button. This ordering is
    what keeps OS chrome, browser chrome, and page content separate.
    """
    w = int(viewport.get("width", 1920))
    tab_band = int(viewport.get("tab_band_h", 44))
    nav_band = int(viewport.get("nav_band_h", 88))
    sidebar_x = float(viewport.get("sidebar_split", 0.78)) * w

    tree = ScreenElementTree()
    for d in detections:
        x, y, rw, rh = d.get("rect", (0, 0, 0, 0))
        icon = str(d.get("icon", ""))
        text = str(d.get("text", ""))
        typ = str(d.get("type", ""))
        container = str(d.get("container", "")).lower()
        source = str(d.get("source", "geometry"))
        states = dict(d.get("states", {}) or {})

        scope, role = _classify_one(x, y, rw, w, tab_band, nav_band,
                                    sidebar_x, icon, text, typ, container)

        conf = _CONF_BY_SOURCE.get(source, 0.5)
        if text:
            conf += 0.05
        if icon and role != "unknown":
            conf += 0.05
        if role == "unknown":
            conf *= 0.6      # ambiguous → uncertain, never invented semantics
        conf = min(0.98, round(conf, 3))

        tree.add(UIElement(
            element_id=str(d.get("id") or f"det-{next(_ids)}"),
            scope=scope, role=role, name=text[:80], text=text[:200],
            elem_type=typ, states=states, rect=(x, y, rw, rh),
            visible=bool(d.get("visible", True)),
            confidence=conf, provenance=source))
    return tree


def _classify_one(x: int, y: int, rw: int, w: int, tab_band: int,
                  nav_band: int, sidebar_x: float, icon: str, text: str,
                  typ: str, container: str) -> tuple[ElementScope, str]:
    # OS window controls: topmost band, right corner strip
    if y < tab_band and x > w - 160:
        return (ElementScope.WINDOW_CHROME,
                _WINDOW_ICON_ROLE.get(icon, "unknown"))

    if y < tab_band:
        if icon == "plus":
            return ElementScope.BROWSER_TAB_STRIP, "new_tab"
        if icon == "x":
            return ElementScope.BROWSER_TAB_STRIP, "tab_close"
        if icon == "chevron":
            return ElementScope.BROWSER_TAB_STRIP, "tab_actions"
        if icon == "app":
            return ElementScope.BROWSER_TAB_STRIP, "browser_menu_icon"
        if typ == "tab" or (text and rw > 60):
            return ElementScope.BROWSER_TAB_STRIP, "tab"
        return ElementScope.BROWSER_TAB_STRIP, "unknown"

    if y < nav_band:
        if typ == "field":
            return ElementScope.BROWSER_ADDRESS, "address"
        if icon in ("lock", "tune"):
            return ElementScope.BROWSER_ADDRESS, "site_info"
        return ElementScope.BROWSER_NAV, _NAV_ICON_ROLE.get(icon, "unknown")

    # page area — sidebar gets its own scope so its composer/send stay
    # separate from the main page's (redesign §10 acceptance)
    sidebar = container == "aside" or x > sidebar_x
    if sidebar:
        if icon == "send":
            return ElementScope.PAGE_SIDEBAR, "send"
        if typ in ("textarea", "contenteditable"):
            return ElementScope.PAGE_SIDEBAR, "composer"
        if typ == "card":
            return ElementScope.PAGE_SIDEBAR, "card"
        if typ == "button" and text:
            return ElementScope.PAGE_SIDEBAR, "quick_action"
        return (ElementScope.PAGE_SIDEBAR,
                "unknown" if not text else "button")

    if typ in ("textarea", "contenteditable"):
        return ElementScope.PAGE_COMPOSER, "composer"
    if icon == "send":
        return ElementScope.PAGE_COMPOSER, "send"
    if typ == "title" or container == "header":
        return ElementScope.PAGE_HEADER, "title" if text else "unknown"
    if icon == "chip" or text.lower().endswith((".md", ".pdf", ".docx", ".txt")):
        return ElementScope.PAGE_MAIN, "attachment"
    if icon == "scrollbar":
        return ElementScope.PAGE_MAIN, "scrollbar"
    if typ == "button":
        return ElementScope.PAGE_MAIN, "button" if (text or icon) else "unknown"
    if typ == "link":
        return ElementScope.PAGE_MAIN, "link"
    if typ == "card":
        return ElementScope.PAGE_MAIN, "card"
    return ElementScope.PAGE_MAIN, "unknown"
