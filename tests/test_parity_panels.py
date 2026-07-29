"""Unit test komponen panel legacy yang belum direlokasi ke Settings.

MK50 §7 melarang panel ini didaftarkan ke ContentStage; pengujian di sini
hanya menjaga logika komponen sampai relokasi Fase 8.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PyQt6.QtWidgets import QApplication, QWidget

from jarvis.ui.actionpanel import ActionPanel
from jarvis.ui.panels import (CapabilitiesPanel, MessagingPanel,
                              SettingsPanel)

_APP_REF: QApplication | None = None


def _app() -> QApplication:
    global _APP_REF
    _APP_REF = QApplication.instance() or QApplication([])
    return _APP_REF


def test_actionpanel_punya_ikon_baru():
    _app()
    host = QWidget()
    panel = ActionPanel(host)
    assert "capabilities" in panel._buttons
    assert "messaging" in panel._buttons
    # ikon lama tetap utuh
    for name in ("vision", "upload", "spotify", "settings"):
        assert name in panel._buttons


def test_klik_ikon_emit_sinyal():
    _app()
    host = QWidget()
    panel = ActionPanel(host)
    hits: list[str] = []
    panel.capabilities_clicked.connect(lambda: hits.append("capabilities"))
    panel.messaging_clicked.connect(lambda: hits.append("messaging"))
    panel._buttons["capabilities"].click()
    panel._buttons["messaging"].click()
    assert hits == ["capabilities", "messaging"]


class _FakeService:
    """Stand-in capability_service — tanpa file, tanpa config."""

    def __init__(self):
        self.toggles: list[tuple[str, bool]] = []
        self.items = [
            {"name": "browser-media", "description": "kontrol media",
             "category": "Media", "triggers": [], "usage": 44,
             "provenance": "agent", "enabled": True},
            {"name": "airtable", "description": "basis data",
             "category": "General", "triggers": [], "usage": 0,
             "provenance": "bundled", "enabled": False},
        ]

    def list_skills(self, filter_text=""):
        return [s for s in self.items
                if filter_text.lower() in s["name"].lower()]

    def sort_skills(self, items, descending=True):
        return items

    def skill_count(self):
        return len(self.items)

    def skill_detail(self, name):
        for s in self.items:
            if s["name"] == name:
                return {**s, "body": "BODY", "use": s["usage"],
                        "view": 0, "patch": 0}
        return None

    def set_skill_enabled(self, name, enabled):
        self.toggles.append((name, enabled))
        return True

    # ── tools (Fase 2c) ──
    groups = [
        {"id": "file_operations", "name": "File Operations",
         "subtitle": "read, write, patch, search",
         "tools": ["read_file", "write_file"], "available": True,
         "enabled": True, "calls": 5,
         "tool_calls": {"read_file": 4, "write_file": 1}},
        {"id": "spotify", "name": "Spotify", "subtitle": "playback",
         "tools": [], "available": False, "enabled": True,
         "calls": 0, "tool_calls": {}},
    ]

    def list_tool_groups(self, filter_text=""):
        return [g for g in self.groups
                if filter_text.lower() in g["name"].lower()]

    def sort_tool_groups(self, items, descending=True):
        return items

    def tool_group_count(self):
        return len(self.groups)

    def set_group_enabled(self, gid, enabled):
        self.toggles.append((gid, enabled))
        return True

    # ── MCP + hub (§5.7) ──
    mcp_servers: list = []
    hub_skills = [
        {"name": "arxiv", "description": "cari paper", "category": "Research",
         "source_path": "x", "installed": False},
        {"name": "notion", "description": "notion api", "category":
         "Productivity", "source_path": "y", "installed": True},
    ]

    def list_mcp_servers(self, probe=False):
        return self.mcp_servers

    def set_mcp_enabled(self, name, enabled):
        self.toggles.append(("mcp", name, enabled))
        return True

    def list_hub_skills(self, filter_text=""):
        return [s for s in self.hub_skills
                if filter_text.lower() in s["name"].lower()]

    def install_hub_skill(self, name):
        self.toggles.append(("install", name))
        return True, "ok"


def test_tab_skills_bangun_baris_dan_detail():
    _app()
    svc = _FakeService()
    panel = CapabilitiesPanel(service=svc)
    panel.refresh()
    assert set(panel._rows) == {"browser-media", "airtable"}
    # detail default = item pertama; badge learned + counter tampil
    text = panel._detail.toPlainText()
    assert "browser-media" in text and "learned" in text
    # baris disabled tanpa counter ×0 — cek lewat detail airtable
    panel._show_detail("airtable")
    text = panel._detail.toPlainText()
    assert "disabled" in text


def test_toggle_lewat_service_dan_search_filter():
    _app()
    svc = _FakeService()
    panel = CapabilitiesPanel(service=svc)
    panel.refresh()
    panel._on_toggle("airtable", True)
    assert svc.toggles == [("airtable", True)]
    panel._search.setText("browser")
    assert set(panel._rows) == {"browser-media"}


def test_tab_mcp_kosong_dan_berisi():
    _app()
    svc = _FakeService()
    panel = CapabilitiesPanel(service=svc)
    panel._set_tab("MCP")
    assert panel._rows == {}                    # tanpa server → empty state
    svc.mcp_servers = [
        {"name": "fs", "command": "npx", "args": ["-y", "srv"],
         "state": "connected", "enabled": True, "error": "",
         "tools": ["read_file"]},
    ]
    panel._reload_list()
    assert set(panel._rows) == {"fs"}
    assert "read_file" in panel._detail.toPlainText()
    panel._on_mcp_toggle("fs", False)
    assert ("mcp", "fs", False) in svc.toggles
    panel._set_tab("Skills")
    assert set(panel._rows) == {"browser-media", "airtable"}


def test_tab_hub_install():
    _app()
    svc = _FakeService()
    panel = CapabilitiesPanel(service=svc)
    panel._set_tab("Browse Hub")
    assert set(panel._rows) == {"arxiv", "notion"}
    panel._on_hub_install("arxiv")
    assert ("install", "arxiv") in svc.toggles
    panel._show_hub_detail("notion")
    assert "terinstal" in panel._detail.toPlainText()


def test_tab_tools_baris_dan_detail():
    _app()
    svc = _FakeService()
    panel = CapabilitiesPanel(service=svc)
    panel._set_tab("Tools")
    assert set(panel._rows) == {"file_operations", "spotify"}
    # detail default = grup pertama; chip per tool tampil
    text = panel._detail.toPlainText()
    assert "File Operations" in text
    assert "[read_file ×4]" in text and "[write_file ×1]" in text
    # grup unavailable: pill terkunci + detail bertanda
    panel._show_group_detail("spotify")
    assert "unavailable" in panel._detail.toPlainText()
    panel._on_group_toggle("file_operations", False)
    assert ("file_operations", False) in svc.toggles


def test_image_group_shows_interactive_controls(monkeypatch):
    _app()
    from jarvis.agent import image_gen_service
    # jaga service image agar tak menyentuh config/network nyata
    monkeypatch.setattr(image_gen_service, "list_providers", lambda: [])
    monkeypatch.setattr(image_gen_service, "current",
                        lambda: {"provider": "", "model": "gpt-image-2",
                                 "quality": "medium", "size": "1024x1024"})
    svc = _FakeService()
    svc.groups = svc.groups + [
        {"id": "image_generation", "name": "Image Generation",
         "subtitle": "image_generate", "tools": ["image_generate"],
         "available": True, "enabled": True, "calls": 0,
         "tool_calls": {"image_generate": 0}}]
    panel = CapabilitiesPanel(service=svc)
    panel._set_tab("Tools")

    panel._show_group_detail("file_operations")
    assert panel._image_controls.isHidden() is True

    panel._show_group_detail("image_generation")
    assert panel._image_controls.isHidden() is False
    # tiga tombol tier gpt-image-2 tersedia
    assert set(panel._image_controls._tier_btns) == {"low", "medium", "high"}

    # pindah ke grup lain menyembunyikan lagi
    panel._show_group_detail("file_operations")
    assert panel._image_controls.isHidden() is True


class _FakeMsgService:
    def __init__(self):
        self.calls: list[tuple] = []
        self.platforms = [
            {"id": "telegram", "name": "Telegram", "description": "d",
             "enabled": True, "configured": True, "allowlist_ok": True,
             "allow_all": False, "state": "connected", "live": True,
             "fields": [
                 {"key": "TELEGRAM_BOT_TOKEN", "required": True,
                  "secret": True, "is_allowlist": False, "is_set": True,
                  "redacted": "••••••••cret"},
                 {"key": "TELEGRAM_ALLOWED_USERS", "required": False,
                  "secret": False, "is_allowlist": True, "is_set": True,
                  "redacted": "42"},
             ]},
            {"id": "discord", "name": "Discord", "description": "d",
             "enabled": False, "configured": False, "allowlist_ok": False,
             "allow_all": False, "state": "disabled", "live": False,
             "fields": [
                 {"key": "DISCORD_BOT_TOKEN", "required": True,
                  "secret": True, "is_allowlist": False, "is_set": False,
                  "redacted": ""},
             ]},
        ]

    def list_platforms(self):
        return self.platforms

    def set_env(self, key, value):
        self.calls.append(("set_env", key, value))
        return True, "ok"

    def clear_env(self, key):
        self.calls.append(("clear_env", key))
        return True, "ok"

    def set_enabled(self, pid, enabled, allow_all_confirmed=False):
        self.calls.append(("set_enabled", pid, enabled, allow_all_confirmed))
        return True, "ok"

    def restart_gateway(self):
        self.calls.append(("restart",))
        return True, "ok"


def _sync_submit(panel):
    """Ganti worker thread dengan eksekusi langsung (deterministik)."""
    panel._submit = lambda fn: panel._on_op_done(*fn())


def test_messaging_panel_baris_dan_detail():
    _app()
    svc = _FakeMsgService()
    panel = MessagingPanel(service=svc)
    panel.refresh()
    assert set(panel._rows) == {"telegram", "discord"}
    # detail default = platform pertama; field ter-build
    assert "TELEGRAM_BOT_TOKEN" in panel._edits
    # secret ter-mask
    from PyQt6.QtWidgets import QLineEdit
    assert panel._edits["TELEGRAM_BOT_TOKEN"].echoMode() == \
        QLineEdit.EchoMode.Password


def test_messaging_toggle_terkunci_tanpa_allowlist():
    _app()
    svc = _FakeMsgService()
    panel = MessagingPanel(service=svc)
    panel.refresh()
    panel._select("discord")
    # discord: allowlist kosong + belum enabled → pill terkunci (§6.4)
    assert panel._enable_pill.isEnabled() is False
    panel._select("telegram")
    assert panel._enable_pill.isEnabled() is True


def test_messaging_save_kirim_ke_service():
    _app()
    svc = _FakeMsgService()
    panel = MessagingPanel(service=svc)
    _sync_submit(panel)
    panel.refresh()
    panel._edits["TELEGRAM_BOT_TOKEN"].setText("token-baru")
    panel._save_changes()
    assert ("set_env", "TELEGRAM_BOT_TOKEN", "token-baru") in svc.calls
    panel._save_changes()                        # edit sudah kosong pasca-refresh
    assert panel._status.text() == "Tidak ada perubahan."
