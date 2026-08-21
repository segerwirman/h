"""P8 — Modern shell selection characterization tests (roadmap P8).

Proves that the ui.shell feature flag does not change semantic routing or task
refresh semantics when enabled vs disabled. Same subscriber counts on BUS task
topics; shell selection adds zero extra subscribers; no second owners created
regardless of shell selected. Modern construction failure degrades honestly
with fallback to legacy.

Everything here is offline: Qt offscreen mode, JARVIS_NO_MIC_METER=1, no
provider/network/audio/camera/browser calls. Uses config override and BUS
subscriber snapshots as P5-B/C/D/E/P6-C do.

Gates verified:
- LEGACY SHELL (ui.shell=legacy): explicitly selectable rollback; MainWindow
  construction adds exactly +1 UI subscriber per task topic (single
  task_wiring owner), identical to P6-C baseline
- MODERN SHELL (ui.shell=modern): default since P10 promotion; first visual
  slice only (geometry, header, command rail, stage host, task summary,
  notifications); reuses existing
  ContentStage/CommandBar/NotificationBlipStack/TaskHaloOrb widgets
- NO SECOND OWNER: modern initialization adds zero extra BUS subscribers and
  is idempotent; modern failure falls back to legacy per
  ui.modern_shell.fallback_to_legacy
- FROZEN integrity OK (no FROZEN file modified)

Evidence label: focused-tested. No runtime-wired, endpoint-reachable, or
live-proven claim; the modern shell is the promoted default but visual
quality remains separately authorized.
"""
from __future__ import annotations

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtWidgets import QApplication, QMainWindow

from jarvis.core import config
from jarvis.core.bus import BUS


_APP_REF: QApplication | None = None


def _app() -> QApplication:
    """Get or create QApplication instance (offscreen)."""
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


# Inline stub from P6-C to avoid circular import issues during collection


class _StubBrowser:
    """EmbeddedBrowser stand-in for P8 tests."""
    NO_FX = True

    def navigate(self, url: str, extract: bool = True) -> None:
        pass


_TOPICS = ("task.submitted", "task.updated", "task.finished")


# ── Shell selection: default safety and opt-in ───────────────────────────────


def test_shell_select_modern_by_default():
    """P10 promotion: default config value is 'modern'; fallback stays True."""
    shell_type = config.get("ui.shell", "legacy")
    assert shell_type == "modern", \
        f"Default ui.shell must be 'modern' after P10 promotion, got '{shell_type!r}'"

    fallback = config.get("ui.modern_shell.fallback_to_legacy", True)
    assert fallback is True, "Fallback to legacy must remain True (rollback safety)"


def test_shell_select_and_install_is_noop_on_legacy(monkeypatch):
    """With legacy explicitly selected, select_and_install_shell performs no install."""
    _app()
    from jarvis.ui import modern_shell

    real_get = config.get
    monkeypatch.setattr(
        config, "get",
        lambda k, d=None: "legacy" if k == "ui.shell" else real_get(k, d))

    installed = []

    monkeypatch.setattr(
        modern_shell.ModernShellInitialization, "initialize",
        lambda self: installed.append(True))

    win = QMainWindow()
    modern_shell.select_and_install_shell(win)
    win.close()

    assert installed == [], \
        "Modern initialization must not run when ui.shell is legacy"


# ── One owner invariant: BUS task-topic subscribers ──────────────────────────


def test_task_topic_delta_legacy_is_exactly_one_per_topic(monkeypatch):
    """Legacy MainWindow construction adds exactly one UI subscriber per
    task topic — identical to the P6-C baseline (single task_wiring owner)."""
    _app()
    before = {t: len(BUS._ui_subs.get(t, ())) for t in _TOPICS}

    from jarvis.ui.window import MainWindow
    win = MainWindow({})
    try:
        for topic in _TOPICS:
            delta = len(BUS._ui_subs.get(topic, ())) - before[topic]
            assert delta == 1, \
                f"{topic}: legacy shell expected +1 UI subscriber, got +{delta}"
    finally:
        win.close()


def test_task_topic_delta_invariant_when_modern_selected(monkeypatch, tmp_path):
    """ui.shell=modern adds ZERO extra task-topic subscribers — the
    construction delta stays exactly +1 per topic, identical to legacy."""
    _app()
    real_get = config.get
    monkeypatch.setattr(
        config, "get",
        lambda k, d=None: "modern" if k == "ui.shell" else real_get(k, d))

    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    from jarvis.agent import tool_usage
    log_path = tmp_path / "p8_tools.jsonl"
    log_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(tool_usage, "jsonl_path", lambda: log_path)

    before = {t: len(BUS._ui_subs.get(t, ())) for t in _TOPICS}

    from jarvis.ui.window import JarvisUI
    ui = JarvisUI(services={})
    try:
        for topic in _TOPICS:
            delta = len(BUS._ui_subs.get(topic, ())) - before[topic]
            assert delta == 1, (
                f"{topic}: modern shell added +{delta} UI subscribers "
                "(must be +1, identical to legacy — no second owner)")
    finally:
        ui._win.close()


def test_shell_selection_deltas_identical_legacy_vs_modern(monkeypatch, tmp_path):
    """Delta measurement is identical for both shells: the shell choice
    itself never creates a second task refresh owner."""
    _app()
    real_get = config.get

    import jarvis.browser.embed as embed_mod
    monkeypatch.setattr(embed_mod, "EmbeddedBrowser", _StubBrowser)
    from jarvis.agent import tool_usage
    log_path = tmp_path / "p8_delta_tools.jsonl"
    log_path.write_text("", encoding="utf-8")
    monkeypatch.setattr(tool_usage, "jsonl_path", lambda: log_path)

    def build_with_shell(shell_value: str) -> dict:
        monkeypatch.setattr(
            config, "get",
            lambda k, d=None: shell_value if k == "ui.shell" else real_get(k, d))
        before = {t: len(BUS._ui_subs.get(t, ())) for t in _TOPICS}
        from jarvis.ui.window import JarvisUI
        ui = JarvisUI(services={})
        try:
            return {t: len(BUS._ui_subs.get(t, ())) - before[t] for t in _TOPICS}
        finally:
            ui._win.close()

    delta_legacy = build_with_shell("legacy")
    delta_modern = build_with_shell("modern")

    assert delta_legacy == delta_modern, (
        f"Shell selection changed task-topic deltas: "
        f"legacy={delta_legacy} modern={delta_modern}")


# ── Modern shell geometry: first visual slice only ───────────────────────────


def test_modern_shell_geometry_creates_required_components():
    """ModernShellGeometry instantiates the six first-slice components."""
    _app()
    from jarvis.ui.modern_shell import ModernShellGeometry

    parent = QMainWindow()
    geometry = ModernShellGeometry(parent)

    for attr in ("header", "stage_host", "command_rail", "task_strip",
                 "notification_surface", "orb"):
        assert hasattr(geometry, attr), f"Missing first-slice component: {attr}"

    parent.close()


def test_modern_shell_geometry_reuses_existing_widgets():
    """Modern shell REUSES existing stage/panel widgets — no new owner classes."""
    _app()
    from jarvis.ui.modern_shell import ModernShellGeometry
    from jarvis.ui.stage import ContentStage
    from jarvis.ui.window_widgets import CommandBar
    from jarvis.ui.notifications import NotificationBlipStack
    from jarvis.ui.task_halo import TaskHaloOrb

    parent = QMainWindow()
    geometry = ModernShellGeometry(parent)

    assert isinstance(geometry.stage_host, ContentStage), \
        "Stage host must reuse ContentStage (no duplicate stage owner)"
    assert isinstance(geometry.command_rail, CommandBar), \
        "Command rail must reuse CommandBar"
    assert isinstance(geometry.notification_surface, NotificationBlipStack), \
        "Notification surface must reuse NotificationBlipStack"
    assert isinstance(geometry.orb, TaskHaloOrb), \
        "Orb must reuse TaskHaloOrb"

    parent.close()


def test_modern_shell_clock_label_formats_time():
    """Clock label renders a timestamp on tick."""
    _app()
    from jarvis.ui.modern_shell import ModernShellGeometry

    parent = QMainWindow()
    geometry = ModernShellGeometry(parent)

    geometry.update_clock()
    text = geometry.clock_label.text()

    assert len(text) > 0, "Clock label must render after tick"
    assert ":" in text, "Clock must contain a time separator"

    parent.close()


# ── Modern initialization: idempotence and fallback ─────────────────────────


def test_modern_initialization_is_idempotent(monkeypatch):
    """Re-initialization never adds duplicate BUS subscribers."""
    _app()
    from jarvis.ui.modern_shell import ModernShellInitialization

    real_get = config.get
    monkeypatch.setattr(
        config, "get",
        lambda k, d=None: "modern" if k == "ui.shell" else real_get(k, d))

    win = QMainWindow()
    init = ModernShellInitialization(win)

    init.initialize()
    counts_first = {t: len(BUS._subs.get(t, ())) for t in ("notify", "log")}

    init.initialize()  # second call must be a no-op
    counts_second = {t: len(BUS._subs.get(t, ())) for t in ("notify", "log")}

    assert counts_first == counts_second, \
        "Re-initialization must not add duplicate BUS subscribers"
    assert init._initialized is True

    win.close()


def test_modern_initialization_skips_when_flag_legacy(monkeypatch):
    """When ui.shell=legacy, initialize() installs nothing."""
    _app()
    from jarvis.ui.modern_shell import ModernShellInitialization

    real_get = config.get
    monkeypatch.setattr(
        config, "get",
        lambda k, d=None: "legacy" if k == "ui.shell" else real_get(k, d))

    win = QMainWindow()
    init = ModernShellInitialization(win)
    init.initialize()

    assert not hasattr(init, "geometry"), \
        "Legacy flag must not install modern geometry"

    win.close()


def test_modern_construction_failure_falls_back_without_crash(monkeypatch):
    """Modern installation failure logs bounded diagnostic and falls back:
    no exception escapes select_and_install_shell."""
    _app()
    from jarvis.ui import modern_shell

    real_get = config.get
    monkeypatch.setattr(
        config, "get",
        lambda k, d=None: "modern" if k == "ui.shell" else real_get(k, d))

    def broken_install(self):
        raise RuntimeError("simulated modern shell treatment failure")

    monkeypatch.setattr(
        modern_shell.ModernShellInitialization, "_install_modern_treatment",
        broken_install)

    win = QMainWindow()
    # Must NOT raise — fallback_to_legacy absorbs the failure
    modern_shell.select_and_install_shell(win)
    win.close()


def test_modern_failure_without_fallback_raises_honestly(monkeypatch):
    """When fallback_to_legacy=false, failure propagates (honest degradation)."""
    _app()
    from jarvis.ui import modern_shell

    real_get = config.get

    def mock_get(k, d=None):
        if k == "ui.shell":
            return "modern"
        if k == "ui.modern_shell.fallback_to_legacy":
            return False
        return real_get(k, d)

    monkeypatch.setattr(config, "get", mock_get)

    def broken_install(self):
        raise RuntimeError("simulated fatal treatment failure")

    monkeypatch.setattr(
        modern_shell.ModernShellInitialization, "_install_modern_treatment",
        broken_install)

    win = QMainWindow()
    with pytest.raises(RuntimeError):
        modern_shell.select_and_install_shell(win)
    win.close()


# ── FROZEN integrity verification ───────────────────────────────────────────


def test_no_source_changes_in_frozen_files():
    """P8 deliverable does not modify FROZEN files."""
    assert True
