"""Phase 29 RED — UI surface wired to local facade.

Permukaan UI nyata (window countdown) memakai facade lokal yang sudah
ada; UI TIDAK pernah bypass facade. Offscreen + fixture pattern.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

_APP_REF = None


def _app():
    global _APP_REF
    if _APP_REF is None:
        from PyQt6.QtWidgets import QApplication

        _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def _window(monkeypatch, facades=None):
    _app()
    import jarvis.browser.embed as embed_mod
    from jarvis.ui.window import MainWindow

    class _StubBrowser:
        def __init__(self, *a, **k):
            pass

    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    kwargs = {"services": {}}
    if facades is not None:
        kwargs["facades"] = facades
    return MainWindow(**kwargs)


def test_window_countdown_uses_default_facade(monkeypatch):
    win = _window(monkeypatch)
    assert win.start_countdown(10) is True
    win.cancel_countdown()


def test_window_respects_facade_deny(monkeypatch):
    import jarvis.core.local_facades as lf

    # Registry dengan facade start_countdown yang SELALU menolak
    registry = lf.LocalFacadeRegistry()
    registry.register("start_countdown", (
        ("start_timer", lambda ctx, **kw: {"ok": False,
                                           "reason": "facade_step_failed"}),
    ))
    win = _window(monkeypatch, facades=registry)
    # UI menghormati facade: deny → tidak mulai countdown
    assert win.start_countdown(10) is False
    assert win._countdown is None


def test_window_rejects_invalid_duration_via_facade(monkeypatch):
    win = _window(monkeypatch)
    assert win.start_countdown(0) is False
    assert win.start_countdown(-5) is False
    assert win.start_countdown(99999) is False
    assert win._countdown is None
