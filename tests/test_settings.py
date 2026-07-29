"""Fase 4 — config_write surgical scalar + SettingsService + SettingsPanel."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from jarvis.core import config, config_write, settings_service as svc

_SAMPLE = """\
# header
theme:
  accent: "#00e5ff"    # warna utama

ui:
  reduced_motion: false          # true = hemat gerak
  parallax:
    enabled: true
    max_px: 6
  themes:
    active: cyan_gold
    presets:
      cyan_gold:
        accent: "#00e5ff"

agent:
  ack_phrase: "Baik, sedang saya kerjakan."
  max_iterations: 50
"""


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    path = tmp_path / "config.yaml"
    path.write_text(_SAMPLE, encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", path)
    config.reload()
    yield path
    monkeypatch.undo()
    config.reload()


# ── config_write ─────────────────────────────────────────────────────────────

def test_set_scalar_nested_komentar_utuh(cfg):
    assert config_write.set_scalar("ui.reduced_motion", True) is True
    text = cfg.read_text(encoding="utf-8")
    assert "  reduced_motion: true          # true = hemat gerak" in text
    assert config.get("ui.reduced_motion") is True
    # level 3 — ui.themes.active; parallax (blok sela) tidak tersentuh
    assert config_write.set_scalar("ui.themes.active", "stealth_dark")
    text = cfg.read_text(encoding="utf-8")
    assert "    active: stealth_dark" in text
    assert "max_px: 6" in text and "# header" in text
    # nama key sama di level berbeda tidak boleh salah sasaran:
    # presets.cyan_gold.accent utuh, theme.accent yang berubah
    assert config_write.set_scalar("theme.accent", "#ffffff")
    text = cfg.read_text(encoding="utf-8")
    assert '  accent: "#ffffff"    # warna utama' in text
    assert '        accent: "#00e5ff"' in text


def test_set_scalar_string_dan_angka(cfg):
    assert config_write.set_scalar("agent.ack_phrase", "Siap, sir.")
    assert config.get("agent.ack_phrase") == "Siap, sir."
    assert config_write.set_scalar("agent.max_iterations", 75)
    assert config.get("agent.max_iterations") == 75


def test_set_scalar_path_baru_ditambah_di_akhir(cfg):
    assert config_write.set_scalar("hermes.enabled", True)
    text = cfg.read_text(encoding="utf-8")
    assert text.rstrip().endswith("hermes:\n  enabled: true")
    assert config.get("hermes.enabled") is True
    assert config.get("agent.max_iterations") == 50   # sisa file utuh


# ── settings_service ─────────────────────────────────────────────────────────

def test_resolve_mengisi_nilai(cfg):
    secs = {s["id"]: s for s in svc.resolve()}
    fields = {f["key"]: f for f in secs["chat"]["fields"]}
    assert fields["agent.ack_phrase"]["value"] == \
        "Baik, sedang saya kerjakan."
    assert fields["agent.max_iterations"]["value"] == 50


def test_set_value_validasi(cfg):
    ok, msg = svc.set_value("llm.live_model", "x", "text")
    assert ok is False and "read-only" in msg
    ok, _ = svc.set_value("agent.max_iterations", "bukan-angka", "int")
    assert ok is False
    ok, _ = svc.set_value("agent.max_iterations", "60", "int")
    assert ok is True and config.get("agent.max_iterations") == 60
    ok, _ = svc.set_value("key.asing", "x", "text")
    assert ok is False
    ok, _ = svc.set_value("ui.themes.active", "tema-hantu", "choice")
    assert ok is False                                  # bukan preset dikenal


# ── UI ───────────────────────────────────────────────────────────────────────

class _FakeSettings:
    def __init__(self):
        self.saved: list[tuple] = []

    def resolve(self):
        return [
            {"id": "chat", "title": "Chat", "hint": "h", "fields": [
                {"key": "agent.ack_phrase", "label": "ACK", "type": "text",
                 "value": "Baik."},
                {"key": "agent.persona_file", "label": "Persona",
                 "type": "readonly", "value": "core/prompt.txt"},
            ]},
            {"id": "model", "title": "Model", "hint": "h",
             "action": "providers", "fields": [
                 {"key": "agent.provider", "label": "Aktif",
                  "type": "readonly", "value": "gemini"},
             ]},
        ]

    def set_value(self, key, value, ftype):
        self.saved.append((key, value, ftype))
        return True, "tersimpan"


def test_settings_panel_form_dan_save():
    from PyQt6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    from jarvis.ui.panels import SettingsPanel
    fake = _FakeSettings()
    panel = SettingsPanel(service=fake)
    panel.refresh()
    assert set(panel._sec_buttons) == {"chat", "model"}
    # seksi chat aktif default; editor hanya untuk field non-readonly
    assert list(panel._editors) == ["agent.ack_phrase"]
    panel._editors["agent.ack_phrase"][1].setText("Siap.")
    panel._save()
    assert ("agent.ack_phrase", "Siap.", "text") in fake.saved
    # seksi model: tanpa editor, sinyal providers tersedia
    hits = []
    panel.open_providers.connect(lambda: hits.append(1))
    panel._select("model")
    assert panel._editors == {}
