"""Semantic element model + screenshot-fixture recognition (§8/§10/§26).

The reference screenshot's element inventory ships as a machine-readable
fixture (tests/fixtures/screenshot_element_inventory.json) of raw
detections — rect, icon/text/type/container hints, source — exactly what
the geometry/icon/OCR stage emits before semantics. These tests drive the
real classification pipeline over it and assert the §26 acceptance list.
No Qt required: the model is deliberately headless.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from jarvis.core.element_model import (ElementScope, ScreenElementTree, UIElement,
                                       classify_detections, elements_from_harvest)

_FIXTURE = Path(__file__).parent / "fixtures" / "screenshot_element_inventory.json"


@pytest.fixture(scope="module")
def tree() -> ScreenElementTree:
    data = json.loads(_FIXTURE.read_text(encoding="utf-8"))
    return classify_detections(data["detections"], data["viewport"])


# ── §26 fixture acceptance ────────────────────────────────────────────────

def test_three_os_window_controls_detected_as_separate_semantics(tree):
    chrome = tree.by_scope(ElementScope.WINDOW_CHROME)
    roles = {el.role for el in chrome}
    assert {"minimize", "maximize", "close"} <= roles
    assert len({el.element_id for el in chrome}) >= 3


def test_tab_strip_detected_and_active_tab_distinguished(tree):
    tabs = tree.find(scope=ElementScope.BROWSER_TAB_STRIP, role="tab")
    assert len(tabs) >= 4
    active = [t for t in tabs if t.states.get("selected")]
    assert len(active) == 1
    assert "Peta Kemampuan" in active[0].name


def test_browser_tabs_are_not_confused_with_page_cards(tree):
    tabs = tree.find(scope=ElementScope.BROWSER_TAB_STRIP, role="tab")
    cards = tree.find(role="card")
    assert tabs and cards
    assert {t.scope for t in tabs} == {ElementScope.BROWSER_TAB_STRIP}
    assert ElementScope.BROWSER_TAB_STRIP not in {c.scope for c in cards}


def test_tab_close_x_and_window_close_x_are_scoped_differently(tree):
    # the same "x" glyph means different things in different scopes —
    # scope-first classification is what keeps them apart
    win_close = tree.find(scope=ElementScope.WINDOW_CHROME, role="close")
    tab_close = tree.find(scope=ElementScope.BROWSER_TAB_STRIP, role="tab_close")
    assert len(win_close) == 1 and len(tab_close) == 1


def test_nav_controls_classified_with_disabled_forward(tree):
    nav = tree.by_scope(ElementScope.BROWSER_NAV)
    roles = {el.role for el in nav}
    assert {"back", "forward", "reload", "menu"} <= roles
    fwd = tree.find(scope=ElementScope.BROWSER_NAV, role="forward")[0]
    assert fwd.states.get("disabled") is True
    new_tab = tree.find(scope=ElementScope.BROWSER_TAB_STRIP, role="new_tab")
    assert len(new_tab) == 1


def test_address_bar_not_confused_with_page_composers(tree):
    address = tree.find(role="address")
    assert len(address) == 1
    assert address[0].scope is ElementScope.BROWSER_ADDRESS
    composers = tree.find(role="composer")
    assert composers
    assert ElementScope.BROWSER_ADDRESS not in {c.scope for c in composers}


def test_main_and_sidebar_composers_remain_separate(tree):
    composers = tree.find(role="composer")
    scopes = {c.scope for c in composers}
    assert ElementScope.PAGE_COMPOSER in scopes
    assert ElementScope.PAGE_SIDEBAR in scopes


def test_two_send_buttons_scoped_to_their_containers(tree):
    sends = tree.find(role="send")
    assert len(sends) == 2
    assert {s.scope for s in sends} == {ElementScope.PAGE_COMPOSER,
                                        ElementScope.PAGE_SIDEBAR}


def test_page_title_and_document_chip_detected(tree):
    titles = tree.find(scope=ElementScope.PAGE_HEADER, role="title")
    assert titles and "Peta Kemampuan" in titles[0].text
    chips = tree.find(role="attachment", text_contains="uimk50.md")
    assert len(chips) == 1


def test_sidebar_quick_actions_detected(tree):
    qa = tree.find(scope=ElementScope.PAGE_SIDEBAR, role="quick_action")
    names = {el.name for el in qa}
    assert {"Summarize", "Explain", "Polish"} <= names


def test_every_element_carries_confidence_and_provenance(tree):
    total = 0
    for scope in tree.scopes():
        for el in tree.by_scope(scope):
            total += 1
            assert 0.0 < el.confidence <= 0.98
            assert el.provenance in ("geometry", "icon", "ocr", "dom", "uia", "qt")
    assert total >= 35


def test_ambiguous_icon_marked_uncertain_not_invented(tree):
    mystery = [el for el in tree.by_scope(ElementScope.BROWSER_NAV)
               if el.element_id == "nav-mystery"]
    assert len(mystery) == 1
    assert mystery[0].role == "unknown"
    assert mystery[0].uncertain is True


def test_no_unscoped_flat_view_scopes_are_preserved(tree):
    assert len(tree.scopes()) >= 6      # window/tab/nav/address/page scopes
    for el in tree.find(role="send"):
        assert el.scope is not ElementScope.UNKNOWN


# ── DOM-harvest normalization (§26 test 19) ───────────────────────────────

def test_harvest_elements_receive_roles_labels_bounds_confidence_provenance():
    items = [
        {"tag": "a", "text": "Docs", "rect": {"x": 10, "y": 20, "w": 60, "h": 18},
         "container": "nav"},
        {"tag": "button", "name": "Send message", "rect": {"x": 300, "y": 700, "w": 40, "h": 40},
         "container": "form"},
        {"tag": "input", "type": "password", "name": "pwd",
         "rect": {"x": 100, "y": 300, "w": 200, "h": 28}, "container": "form"},
        {"tag": "textarea", "text": "draft", "rect": {"x": 100, "y": 600, "w": 400, "h": 80},
         "container": "main"},
        {"tag": "div", "editable": True, "rect": {"x": 900, "y": 600, "w": 300, "h": 60},
         "container": "aside"},
        {"tag": "select", "rect": {"x": 50, "y": 400, "w": 120, "h": 24},
         "container": "main"},
        {"tag": "input", "type": "checkbox", "checked": True,
         "rect": {"x": 60, "y": 450, "w": 16, "h": 16}, "container": "main"},
    ]
    els = elements_from_harvest(items, page_id="tab-0")
    assert len(els) == 7
    by_tag = {e.elem_type: e for e in els}
    assert by_tag["a"].role == "link"
    assert by_tag["button"].role == "button" and by_tag["button"].name == "Send message"
    assert by_tag["password"].role == "text_field"       # type recorded, never bypassed
    assert by_tag["textarea"].scope is ElementScope.PAGE_COMPOSER
    assert by_tag["div"].role == "composer"
    assert by_tag["div"].scope is ElementScope.PAGE_SIDEBAR
    assert by_tag["select"].role == "dropdown"
    assert by_tag["checkbox"].states.get("checked") is True
    for e in els:
        assert e.provenance == "dom"
        assert e.confidence >= 0.8
        assert e.rect[2] > 0 and e.page_id == "tab-0"


# ── stale/actionable gate (§26 test 20) ───────────────────────────────────

def test_stale_elements_cannot_be_executed():
    tree = ScreenElementTree()
    el = UIElement(element_id="e1", scope=ElementScope.PAGE_MAIN, role="button",
                   name="OK", confidence=0.9, rect=(10, 10, 40, 20))
    tree.add(el)
    assert tree.actionable("e1") is el
    tree.invalidate("navigation")
    assert tree.actionable("e1") is None


def test_low_confidence_and_expired_elements_are_refused():
    tree = ScreenElementTree()
    weak = UIElement(element_id="weak", scope=ElementScope.PAGE_MAIN,
                     role="unknown", confidence=0.2)
    old = UIElement(element_id="old", scope=ElementScope.PAGE_MAIN,
                    role="button", confidence=0.9,
                    timestamp=time.time() - 3600)
    tree.add(weak)
    tree.add(old)
    assert tree.actionable("weak") is None
    assert tree.actionable("old") is None       # expired → auto-stale
    assert tree.actionable("missing") is None
