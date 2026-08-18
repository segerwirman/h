"""Fase 35 Slice 9 — local target audit fallback observability."""
from __future__ import annotations

import json

from jarvis.core import quiet, target_resolver


def _spy(monkeypatch):
    events = []
    monkeypatch.setattr(
        quiet,
        "swallowed",
        lambda event, exc=None, **_context: events.append(
            (event, type(exc).__name__ if exc is not None else None)),
    )
    return events


def test_audit_filesystem_failure_is_fail_open_and_recorded(tmp_path, monkeypatch):
    parent = tmp_path / "not_a_directory"
    parent.write_text("occupied", encoding="utf-8")
    monkeypatch.setattr(
        target_resolver.config,
        "resolve_path",
        lambda _value: parent / "audit.jsonl",
    )
    events = _spy(monkeypatch)

    assert target_resolver._audit({"event": "close"}) is None
    assert events == [("core.target_resolver.audit_failed", "FileExistsError")]


def test_audit_writes_local_jsonl_without_failure(tmp_path, monkeypatch):
    path = tmp_path / "audit.jsonl"
    monkeypatch.setattr(target_resolver.config, "resolve_path", lambda _value: path)
    events = _spy(monkeypatch)

    assert target_resolver._audit({"event": "close"}) is None
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["event"] == "close"
    assert isinstance(record["ts"], float)
    assert events == []
