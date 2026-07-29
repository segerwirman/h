"""PROMPT L — resolver lookup-only, konservatif, tanpa LLM/UI."""
from __future__ import annotations

from pathlib import Path

import pytest

from jarvis.core import app_registry as apps


@pytest.fixture()
def registry(monkeypatch, tmp_path):
    from jarvis.core import action_registry

    fake_apps = {
        "spotify": apps.AppMatch("spotify", "Spotify", "Spotify.lnk", "start_menu"),
        "visual studio code": apps.AppMatch(
            "visual studio code", "Visual Studio Code", "code.exe", "start_menu"),
        "chrome": apps.AppMatch("chrome", "Google Chrome", "chrome.exe", "start_menu"),
        "instagram": apps.AppMatch("instagram", "Instagram", "Instagram.lnk", "start_menu"),
    }
    monkeypatch.setattr(apps, "_index", fake_apps)
    monkeypatch.setattr(apps, "_index_built_at", 9e9)
    monkeypatch.setattr(apps.shutil, "which", lambda *_a, **_k: None)
    monkeypatch.setattr(apps, "_store_path", lambda: tmp_path / "aliases.json")
    return action_registry.ActionRegistry().refresh()


def _resolve(registry, text, source="text"):
    from jarvis.core.resolver import resolve
    return resolve(text, source=source, registry=registry)


@pytest.mark.parametrize("text,kind,target,verb", [
    ("buka spotify", "app", "spotify", "open"),
    ("buka vscode", "app", "visual studio code", "open"),
    ("tutup chrome", "app", "chrome", "close"),
    ("buka kamera", "panel", "vision", "open"),
    ("naikkan volume", "system", "volume_up", "set"),
])
def test_l1_lookup_tunggal_mengeksekusi_instan(registry, text, kind, target, verb):
    from jarvis.core.resolver import Action
    result = _resolve(registry, text)
    assert isinstance(result, Action)
    assert (result.kind, result.target, result.verb, result.source) == (
        kind, target, verb, "L1")
    assert result.confidence < 1.0


@pytest.mark.parametrize("text", [
    "gimana ya cara buka spotify",
    "spotify bagus nggak sih?",
    "kemarin aku buka spotify terus lupa nutup",
    "kayaknya enak nih dengerin spotify",
    "menurutmu spotify atau youtube music?",
    "buka spotify dong",
])
def test_percakapan_tidak_boleh_bocor_ke_l1(registry, text):
    from jarvis.core.resolver import FallthroughToLLM
    assert isinstance(_resolve(registry, text), FallthroughToLLM)


def test_app_dan_situs_memicu_clarify(registry):
    from jarvis.core.resolver import ClarifyNeeded
    result = _resolve(registry, "buka instagram")
    assert isinstance(result, ClarifyNeeded)
    assert result.topic == "instagram"
    assert result.options == ("aplikasi", "browser")


def test_target_close_vague_memicu_clarify(registry):
    from jarvis.core.resolver import ClarifyNeeded
    result = _resolve(registry, "tutup semua")
    assert isinstance(result, ClarifyNeeded)
    assert result.kind == "close_target"


def test_l0_prefix_langsung_tanpa_heuristik(registry):
    from jarvis.core.resolver import Action
    result = _resolve(registry, "/open spotify")
    assert isinstance(result, Action)
    assert (result.kind, result.target, result.verb, result.confidence, result.source) == (
        "app", "spotify", "open", 1.0, "L0")


def test_palette_adalah_l0_karena_user_sudah_memilih(registry):
    from jarvis.core.resolver import Action
    result = _resolve(registry, "open spotify", source="palette")
    assert isinstance(result, Action)
    assert result.source == "L0"


def test_registry_memakai_config_panel_bukan_daftar_panel_hardcode(registry):
    panels = {action.target for action in registry.lookup("vision") if action.kind == "panel"}
    assert "vision" in panels
    entities = registry.all_entities()
    assert "spotify" in entities
    assert "volume_up" in entities


def test_alias_app_registry_dipakai(registry):
    from jarvis.core.resolver import ClarifyNeeded
    result = _resolve(registry, "buka ig")
    assert isinstance(result, ClarifyNeeded)
    assert result.topic == "instagram"


def test_resolver_tidak_mengimpor_ui_atau_router_legacy():
    text = Path("jarvis/core/resolver.py").read_text(encoding="utf-8")
    assert "jarvis.ui" not in text
    assert "IntentRouter" not in text
    assert "llm.generate" not in text
