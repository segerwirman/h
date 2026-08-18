"""Fase 35 Slice 9 — app registry sidecar fallback observability."""
from __future__ import annotations

import json

from jarvis.core import app_registry, quiet


def _spy(monkeypatch):
    events = []
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **_context: events.append(
            (event, type(exc).__name__ if exc is not None else None)),
    )
    return events


def test_corrupt_store_returns_empty_store_and_records_event(tmp_path, monkeypatch):
    path = tmp_path / "app_aliases.json"
    path.write_text("{bukan json", encoding="utf-8")
    monkeypatch.setattr(app_registry, "_store_path", lambda: path)
    events = _spy(monkeypatch)

    assert app_registry._load_store() == {"aliases": {}, "preferences": {}}
    assert events == [("core.app_registry.store_read_failed", "JSONDecodeError")]


def test_missing_store_returns_empty_store_and_records_event(tmp_path, monkeypatch):
    path = tmp_path / "missing.json"
    monkeypatch.setattr(app_registry, "_store_path", lambda: path)
    events = _spy(monkeypatch)

    assert app_registry._load_store() == {"aliases": {}, "preferences": {}}
    assert events == [("core.app_registry.store_read_failed", "FileNotFoundError")]


def test_valid_store_does_not_record_failure(tmp_path, monkeypatch):
    path = tmp_path / "app_aliases.json"
    path.write_text(
        json.dumps({"aliases": {"ig": "instagram"}}),
        encoding="utf-8")
    monkeypatch.setattr(app_registry, "_store_path", lambda: path)
    events = _spy(monkeypatch)

    assert app_registry._load_store() == {
        "aliases": {"ig": "instagram"},
        "preferences": {},
    }
    assert events == []
