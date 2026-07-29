"""Fase 5 (§7/§8) — ContentStage vision/info/home, Tabbit hilang, panel
Home Assistant (CCTV/lampu/cuaca), kartu berita ke panel info, lazy vision.

Pola offscreen sama dengan test_parity_panels.py — tanpa event loop nyata.
"""
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("JARVIS_NO_MIC_METER", "1")

import pytest
from PyQt6.QtWidgets import QApplication

from jarvis.core.bus import BUS

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def _drain_bus():
    BUS.drain_ui()
    _app().processEvents()


# ── ContentStage §7.2 ───────────────────────────────────────────────────────

def test_tabbit_modules_gone():
    for mod in ("jarvis.browser.skill_memory", "jarvis.browser.frame_agent",
                "jarvis.browser.tabbit_embed", "jarvis.browser.tabbit_resolver"):
        with pytest.raises(ModuleNotFoundError):
            __import__(mod)
    assert not os.path.exists("config/tabbit_skills.json")
    for path in ("config.yaml", "jarvis/ui/window.py",
                 "jarvis/core/router.py", "jarvis/agent/router.py",
                 "jarvis/browser/agent.py"):
        assert "tabbit" not in Path(path).read_text(
            encoding="utf-8").casefold(), path


def test_actionpanel_home_signal_and_icon():
    from jarvis.ui.actionpanel import _ICONS, ActionPanel
    assert "home" in _ICONS
    assert hasattr(ActionPanel, "home_clicked")
    from jarvis.core import config
    assert "home" in list(config.get("action_panel.icons", []))


# ── InfoPanel §7.2/§6.4 ─────────────────────────────────────────────────────

def test_info_panel_card_via_bus():
    _app()
    from jarvis.ui.info_panel import InfoPanel
    panel = InfoPanel()
    # kuras backlog publish dari test lain (queue BUS global antar-test)
    for _ in range(8):
        _drain_bus()
    before = panel.card_count
    BUS.publish("info.card", kind="news", title="berita uji",
                lines=["Judul A  [Kompas 2026-07-20]"],
                source="DuckDuckGo News", ts="")
    _drain_bus()
    assert panel.card_count == before + 1


def test_info_panel_card_cap():
    _app()
    from jarvis.ui import info_panel as ip
    panel = ip.InfoPanel()
    for i in range(ip.MAX_CARDS + 4):
        panel.add_card("news", f"t{i}", ["x"])
    assert panel.card_count <= ip.MAX_CARDS


def test_info_card_borderless_by_default(monkeypatch):
    _app()
    from jarvis.core import config
    from jarvis.ui.info_panel import _InfoCard
    orig = config.get
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: False if k == "ui.info_panel.card_border"
                        else orig(k, d))
    card = _InfoCard("result", "AGENT — hasil tugas", ["baris"], "Jarvis", "")
    css = card.styleSheet()
    assert "border: none;" in css
    assert "1px solid" not in css


def test_info_card_border_opt_in(monkeypatch):
    _app()
    from jarvis.core import config
    from jarvis.ui.info_panel import _InfoCard
    orig = config.get
    monkeypatch.setattr(config, "get",
                        lambda k, d=None: True if k == "ui.info_panel.card_border"
                        else orig(k, d))
    card = _InfoCard("result", "AGENT", ["baris"], "Jarvis", "")
    assert "1px solid" in card.styleSheet()


def test_action_news_publishes_info_card(monkeypatch):
    from actions import web_search as action

    seen: list[dict] = []
    monkeypatch.setattr(action, "_ddg_news", lambda q, max_results=8: [
        {"title": "Berita panjang sekali supaya lolos ambang enam puluh "
                  "karakter minimal", "snippet": "isi", "url": "u",
         "source": "Kompas", "date": "2026-07-20"}])
    monkeypatch.setattr(
        action, "_gemini_search",
        lambda q: (_ for _ in ()).throw(RuntimeError("offline")))

    def fake_publish(topic, **data):
        seen.append({"topic": topic, **data})

    from jarvis.core import bus
    monkeypatch.setattr(bus.BUS, "publish", fake_publish)
    out = action._news("berita terbaru hari ini")
    cards = [s for s in seen if s["topic"] == "info.card"]
    assert cards and cards[0]["kind"] == "news"
    assert "Kompas" in cards[0]["lines"][0]
    assert "Berita panjang" in out


def test_action_search_publishes_info_card(monkeypatch):
    from actions import web_search as action

    seen: list[dict] = []
    monkeypatch.setattr(action, "_gemini_search",
                        lambda q: "Ringkasan hasil pencarian yang nyata.")
    from jarvis.core import bus
    monkeypatch.setattr(
        bus.BUS, "publish",
        lambda topic, **data: seen.append({"topic": topic, **data}))
    out = action._search("dokumentasi asyncio")
    assert "Ringkasan" in out
    assert seen and seen[0]["kind"] == "search"
    assert seen[0]["source"] == "Gemini Search"


def test_weather_action_publishes_info_card(monkeypatch):
    from actions import weather_report as action

    seen: list[dict] = []
    import webbrowser
    monkeypatch.setattr(webbrowser, "open", lambda _url: True)
    from jarvis.core import bus
    monkeypatch.setattr(
        bus.BUS, "publish",
        lambda topic, **data: seen.append({"topic": topic, **data}))
    out = action.weather_action({"city": "Jakarta", "time": "hari ini"})
    assert "Jakarta" in out
    assert seen and seen[0]["kind"] == "weather"
    assert "ID" in seen[0]["lines"][0]


# ── HomePanel §8 ────────────────────────────────────────────────────────────

@pytest.fixture()
def ha_fake(monkeypatch):
    from jarvis.agent.tools import home_assistant as ha

    calls: dict = {"get": [], "post": [], "snapshots": []}
    states = [
        {"entity_id": "camera.teras", "state": "idle",
         "attributes": {"friendly_name": "Kamera Teras"}},
        {"entity_id": "light.ruang_tamu", "state": "on",
         "attributes": {"friendly_name": "Lampu Ruang Tamu",
                        "brightness": 180}},
        {"entity_id": "weather.rumah", "state": "partlycloudy",
         "attributes": {"friendly_name": "Cuaca Rumah",
                        "temperature": 29, "humidity": 78}},
    ]
    monkeypatch.setattr(ha, "available", lambda: True)
    monkeypatch.setattr(ha, "_url", lambda: "http://ha.local:8123")
    monkeypatch.setattr(ha, "_headers", lambda: {})

    def fake_get(path):
        calls["get"].append(path)
        return states

    def fake_post(path, payload):
        calls["post"].append((path, payload))
        return {}

    class _SnapshotResponse:
        content = b"not-an-image"

        def raise_for_status(self):
            return None

    def fake_snapshot_get(url, headers=None, timeout=10):
        calls["snapshots"].append((url, headers, timeout))
        return _SnapshotResponse()

    monkeypatch.setattr(ha, "_get", fake_get)
    monkeypatch.setattr(ha, "_post", fake_post)
    import requests
    monkeypatch.setattr(requests, "get", fake_snapshot_get)
    return calls


def _wait_signal(panel, attr="_busy", timeout_s=3.0):
    import time
    t0 = time.time()
    while getattr(panel, attr) and time.time() - t0 < timeout_s:
        _drain_bus()
        time.sleep(0.02)
    _drain_bus()


def test_home_panel_builds_sections_from_ha(ha_fake):
    _app()
    from jarvis.ui.home_panel import HomePanel
    panel = HomePanel()
    panel.refresh(force=True)
    _wait_signal(panel)
    assert "1 kamera" in panel._status.text()
    assert "1 lampu" in panel._status.text()
    assert panel._weather_card.isVisibleTo(panel)
    assert "29" in panel._weather_card.text()
    assert len(panel._lights_rows) == 1
    assert panel._lights_rows[0].toggle.isChecked()
    assert "camera.teras" in panel._camera_labels


def test_home_camera_click_opens_enlarged_view(ha_fake):
    _app()
    from jarvis.ui.home_panel import HomePanel
    panel = HomePanel()
    panel.refresh(force=True)
    _wait_signal(panel)
    panel._camera_labels["camera.teras"].activated.emit("camera.teras")
    assert panel._camera_dialog is not None
    assert panel._camera_dialog.isVisible()
    panel._camera_dialog.close()


def test_home_camera_uses_ha_snapshot_proxy(ha_fake):
    _app()
    from jarvis.ui.home_panel import HomePanel
    panel = HomePanel()
    panel.refresh(force=True)
    _wait_signal(panel)
    import time
    t0 = time.time()
    while not ha_fake["snapshots"] and time.time() - t0 < 3.0:
        _drain_bus()
        time.sleep(0.02)
    assert ha_fake["snapshots"]
    url, _headers, timeout = ha_fake["snapshots"][0]
    assert url == "http://ha.local:8123/api/camera_proxy/camera.teras"
    assert timeout == 10


def test_home_panel_toggle_light_calls_service(ha_fake):
    _app()
    from jarvis.ui.home_panel import HomePanel
    panel = HomePanel()
    panel.refresh(force=True)
    _wait_signal(panel)
    row = panel._lights_rows[0]
    row.toggle.setChecked(False)
    row._on_toggle()
    import time
    t0 = time.time()
    while not ha_fake["post"] and time.time() - t0 < 3.0:
        _drain_bus()
        time.sleep(0.02)
    assert ha_fake["post"]
    path, payload = ha_fake["post"][0]
    assert path == "/api/services/light/turn_off"
    assert payload["entity_id"] == "light.ruang_tamu"
    t0 = time.time()
    while len(ha_fake["get"]) < 2 and time.time() - t0 < 3.0:
        _drain_bus()
        time.sleep(0.02)
    assert len(ha_fake["get"]) >= 2     # refresh untuk verifikasi state server


def test_home_panel_brightness_payload(ha_fake):
    _app()
    from jarvis.ui.home_panel import HomePanel
    panel = HomePanel()
    panel.refresh(force=True)
    _wait_signal(panel)
    row = panel._lights_rows[0]
    row.toggle.setChecked(True)
    row.slider.setValue(120)
    row._on_brightness()
    import time
    t0 = time.time()
    while not ha_fake["post"] and time.time() - t0 < 3.0:
        _drain_bus()
        time.sleep(0.02)
    path, payload = ha_fake["post"][0]
    assert path == "/api/services/light/turn_on"
    assert payload["brightness"] == 120


def test_home_panel_empty_state_without_credentials(monkeypatch):
    _app()
    from jarvis.agent.tools import home_assistant as ha
    monkeypatch.setattr(ha, "available", lambda: False)
    from jarvis.ui.home_panel import HomePanel
    panel = HomePanel()
    panel.refresh(force=True)
    assert "belum terhubung" in panel._status.text()
    assert not panel._lights_rows


def test_home_panel_error_reported_honestly(monkeypatch):
    _app()
    from jarvis.agent.tools import home_assistant as ha
    monkeypatch.setattr(ha, "available", lambda: True)

    def boom(path):
        raise RuntimeError("connection refused")

    monkeypatch.setattr(ha, "_get", boom)
    from jarvis.ui.home_panel import HomePanel
    panel = HomePanel()
    panel.refresh(force=True)
    _wait_signal(panel)
    assert "tidak merespons" in panel._status.text()


# ── lazy vision (efisiensi #7) ──────────────────────────────────────────────

def test_vision_constructor_does_not_spawn_or_import_heavy():
    """Konstruksi VisionSystem (boot jarvis.main) tidak boleh memuat
    cv2/mediapipe/ultralytics atau spawn process — hanya start()/arm."""
    code = (
        "import sys\n"
        "from jarvis.vision.process import VisionSystem\n"
        "v = VisionSystem()\n"
        "assert v._proc is None, 'process spawned at construction'\n"
        "for heavy in ('cv2', 'mediapipe', 'ultralytics'):\n"
        "    assert heavy not in sys.modules, heavy + ' imported eagerly'\n"
        "print('LAZY-OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=120,
                       cwd=os.path.dirname(os.path.dirname(
                           os.path.abspath(__file__))))
    assert "LAZY-OK" in r.stdout, r.stderr[-800:]


def test_boot_import_does_not_load_qtwebengine_or_heavy_vision():
    """MK50 §7: jarvis.main tidak lagi memuat QtWebEngine saat import; heavy
    vision juga tidak ikut."""
    code = (
        "import os, sys\n"
        "os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')\n"
        "import jarvis.main\n"
        "for heavy in ('PyQt6.QtWebEngineWidgets', 'cv2', 'mediapipe',\n"
        "              'ultralytics'):\n"
        "    assert heavy not in sys.modules, heavy + ' loaded at import'\n"
        "print('BOOT-LEAN-OK')\n"
    )
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=120,
                       cwd=os.path.dirname(os.path.dirname(
                           os.path.abspath(__file__))))
    assert "BOOT-LEAN-OK" in r.stdout, r.stderr[-800:]
