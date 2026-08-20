"""P6-B — Presentation adapter opt-in seam (default off).

Continuation of roadmap P6 / GUI_EVOLUTION_PLAN GUI-1. This slice adds a
config flag ``ui.presentation_adapter.enabled`` (default ``false``) and a
``JarvisUI.adapter`` seam exposing a ``FacadeShim`` around the legacy facade
only when the flag is on. The legacy shell remains the only deployed shell
and looks unchanged; default behavior is bitwise-identical (no shim).

Everything here is offline: EmbeddedBrowser stubbed (QtWebEngine cannot init
offscreen), JARVIS_NO_MIC_METER=1, tools JSONL redirected to tmp_path, no
provider/network/audio/camera/browser calls.

Contracts under test:
- config key defaults to false
- default path: ``ui.adapter is None``; facade surfaces behave as before
- enabled path: ``ui.adapter`` is a FacadeShim; one delegation per call with
  unmuted arguments; viewport mirrors the same state the window received
- submit_text through the shim records exactly one intent and fires the
  facade text-command callback exactly once
- rollback = removing/keeping the flag false (nothing else changes)

Evidence label: focused-tested. No runtime-wired, endpoint-reachable, or
live-proven claim.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtWidgets import QApplication, QWidget

from jarvis.core import config

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


class _StubBrowser(QWidget):
    """EmbeddedBrowser stand-in (see tests/test_window_integration.py)."""
    NO_FX = True

    def navigate(self, url: str, extract: bool = True) -> None:
        pass


def _make_ui(monkeypatch, tmp_path, *, flag_on: bool):
    """Build JarvisUI with the adapter flag pinned, browser stubbed, and the
    tools JSONL tail on a temp file."""
    _app()
    real_get = config.get
    if flag_on:
        monkeypatch.setattr(
            config, "get",
            lambda k, d=None: True
            if k == "ui.presentation_adapter.enabled" else real_get(k, d))
    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    from jarvis.agent import tool_usage
    log_path = tmp_path / "p6b_tools.jsonl"
    log_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(tool_usage, "jsonl_path", lambda: log_path)
    from jarvis.ui.window import JarvisUI
    return JarvisUI(services={})


# ── Config gate ──────────────────────────────────────────────────────────────


def test_config_default_disabled():
    """The seam has a gate that is off by default."""
    assert config.get("ui.presentation_adapter.enabled", False) is False


# ── Default (disabled) path: no shim, pure legacy facade ─────────────────────


def test_default_off_facade_has_no_adapter_and_surfaces_unchanged(
        monkeypatch, tmp_path):
    """Default path: adapter is None, and set_state/write_log behave exactly
    as the legacy facade (no second owner is created)."""
    ui = _make_ui(monkeypatch, tmp_path, flag_on=False)
    try:
        assert ui.adapter is None

        # Facade surfaces still work and reach the window as before
        ui.set_state("THINKING")
        _app().processEvents()
        assert ui._win._legacy_state == "THINKING"

        ui.write_log("catatan p6b")          # no raise, legacy path intact
    finally:
        ui._win.close()


# ── Enabled path: shim wraps the facade ──────────────────────────────────────


def test_flag_on_facade_adapter_is_facade_shim_and_delegates_once(
        monkeypatch, tmp_path):
    """With the flag on, ui.adapter is a FacadeShim around the legacy facade;
    each call delegates exactly once with unmuted arguments, and the viewport
    mirrors what the window received."""
    from jarvis.ui.presentation_adapter import FacadeShim

    ui = _make_ui(monkeypatch, tmp_path, flag_on=True)
    try:
        assert isinstance(ui.adapter, FacadeShim)

        ui.adapter.set_state("LISTENING")
        _app().processEvents()

        # Single delegation reached the real window
        assert ui._win._legacy_state == "LISTENING"
        # Viewport mirrors the same semantic state (bounded, non-secret)
        assert ui.adapter.viewport.state == "LISTENING"

        long_title = "J" * 100
        long_text = "X" * 9000
        ui.adapter.show_content(long_title, long_text)
        # Facade passthrough bounds (same as legacy emit) land in viewport
        assert ui.adapter.viewport.title == long_title[:64]
        assert ui.adapter.viewport.text == long_text[:6000]

        ui.adapter.write_log("lewat shim")
        assert tuple(ui.adapter.viewport.log)[-1] == "lewat shim"
    finally:
        ui._win.close()


def test_flag_on_submit_text_records_one_intent_and_fires_callback_once(
        monkeypatch, tmp_path):
    """submit_text through the shim fires the legacy on_text_command callback
    exactly once and records exactly one intent."""
    ui = _make_ui(monkeypatch, tmp_path, flag_on=True)
    try:
        got: list[str] = []
        ui.on_text_command = got.append

        ui.adapter.submit_text("putar musik")

        assert got == ["putar musik"]
        intents = ui.adapter.recorder.intents
        assert len(intents) == 1
        assert intents[0]["intent"] == "submit_text"
        assert intents[0]["meta"] == {"text": "putar musik"}
    finally:
        ui._win.close()


# ── Shim purity (no Qt needed) ───────────────────────────────────────────────


def test_shim_delegation_never_mutates_arguments():
    """FacadeShim forwards exact argument objects; bounds live only in the
    viewport copy (P6-A contract, re-checked here as the wiring invariant)."""
    from jarvis.ui.presentation_adapter import FacadeShim

    calls: list[tuple] = []

    class FakeFacade:
        def set_state(self, s):
            calls.append(("set_state", s))

        def write_log(self, t):
            calls.append(("write_log", t))

        def show_content(self, title, text):
            calls.append(("show_content", title, text))

    shim = FacadeShim(FakeFacade())
    t, b = "A" * 70, "B" * 6500
    shim.show_content(t, b)

    assert calls == [("show_content", t, b)]        # unmuted passthrough
    assert shim.viewport.title == "A" * 64          # bounds only in viewport
    assert shim.viewport.text == "B" * 6000
