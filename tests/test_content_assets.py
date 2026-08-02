"""Studio B local selected-scene asset contract."""
from __future__ import annotations


def _project():
    from jarvis.core.content_project import ContentProject, Scene
    return ContentProject("P", "A", "T", "H", "C", (
        Scene("Satu", "V1", "N1", "prompt satu"),
        Scene("Dua", "V2", "N2", "prompt dua"),
    ))


def test_unconfigured_provider_fails_safely_without_asset_or_generator_call():
    from jarvis.core.content_assets import generate_selected_scene
    calls = []
    result = generate_selected_scene(_project(), 0, configured=False, generate=lambda *_: calls.append(1))
    assert result == {"ok": False, "reason": "content_image_provider_unavailable"}
    assert calls == []


def test_selected_scene_creates_one_local_metadata_asset_without_exposing_path(tmp_path):
    from jarvis.core.content_assets import generate_selected_scene
    calls = []
    def fake(prompt):
        calls.append(prompt)
        return tmp_path / "created.png"

    result = generate_selected_scene(_project(), 1, configured=True, provider="local-image", model="fake-v1", generate=fake)
    assert result == {"ok": True, "asset": {"scene_index": 1, "provider": "local-image", "model": "fake-v1", "state": "ready"}}
    assert calls == ["prompt dua"]
    assert str(tmp_path) not in str(result)
    assert "path" not in str(result).lower()


def test_invalid_or_unselected_scene_fails_closed_and_never_bulk_generates():
    from jarvis.core.content_assets import generate_selected_scene
    calls = []
    for index in (-1, 2, "all"):
        result = generate_selected_scene(_project(), index, configured=True, generate=lambda *_: calls.append(1))
        assert result == {"ok": False, "reason": "content_scene_selection_required"}
    assert calls == []


def test_active_provider_unavailable_fails_closed_without_generation(monkeypatch):
    import asyncio
    from jarvis.core import content_assets

    monkeypatch.setattr(content_assets, "_active_image_tool", lambda: None)
    assert asyncio.run(content_assets.generate_selected_scene_with_active_provider(_project(), 0)) == {
        "ok": False, "reason": "content_image_provider_unavailable",
    }


def test_configured_active_provider_runs_selected_scene_once_and_keeps_path_internal(monkeypatch, tmp_path):
    import asyncio
    from jarvis.core import content_assets

    captured = []
    class FakeImageTool:
        async def run(self, *, prompt, n):
            captured.append((prompt, n))
            return type("Result", (), {"ok": True, "meta": {"paths": [str(tmp_path / "secret.png")]}})()

    monkeypatch.setattr(content_assets, "_active_image_tool", lambda: ("configured", "model-x", FakeImageTool()))
    result = asyncio.run(content_assets.generate_selected_scene_with_active_provider(_project(), 0))
    assert result == {"ok": True, "asset": {"scene_index": 0, "provider": "configured", "model": "model-x", "state": "ready"}}
    assert captured == [("prompt satu", 1)]
    assert str(tmp_path) not in str(result)


def test_asset_module_has_no_remote_publish_or_oauth_secret_surface():
    from jarvis.core import content_assets
    source = open(content_assets.__file__, encoding="utf-8").read().lower()
    for forbidden in ("telegram", "publish", "requests", "webbrowser", "access_token", "refresh_token", "oauth"):
        assert forbidden not in source
