"""Game updater: Steam library fallback stays observable and bounded."""
from __future__ import annotations

from pathlib import Path

from actions import game_updater
from jarvis.core import quiet


def test_steam_library_read_failure_records_event_and_keeps_default(
    monkeypatch, tmp_path
):
    steam_path = tmp_path / "Steam"
    steamapps = steam_path / "steamapps"
    steamapps.mkdir(parents=True)
    vdf_path = steamapps / "libraryfolders.vdf"
    vdf_path.write_text("not used", encoding="utf-8")

    original_read_text = Path.read_text

    def failing_read_text(path, *args, **kwargs):
        if path == vdf_path:
            raise OSError("libraryfolders locked")
        return original_read_text(path, *args, **kwargs)

    events = []
    monkeypatch.setattr(Path, "read_text", failing_read_text)
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **context: events.append((event, exc, context)),
    )

    libraries = game_updater._get_steam_libraries(steam_path)

    assert libraries == [steamapps]
    assert len(events) == 1
    assert events[0][0] == "actions.game_updater.libraryfolders_read_failed"
    assert isinstance(events[0][1], OSError)
