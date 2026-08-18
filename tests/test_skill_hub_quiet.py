"""Fase 35 Slice 11 — local skill-hub fallback telemetry."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace


def _spy(monkeypatch, module):
    events: list[tuple[str, str]] = []

    def record(event, exc=None, **_context):
        events.append((str(event), type(exc).__name__ if exc else ""))

    from jarvis.core import quiet

    monkeypatch.setattr(quiet, "swallowed", record)
    return events


def test_hub_sources_skips_invalid_source_and_reports_failure(monkeypatch, tmp_path):
    from jarvis.agent import skill_hub

    events = _spy(monkeypatch, skill_hub)
    good = tmp_path / "good"
    good.mkdir()
    bad = tmp_path / "bad"

    monkeypatch.setattr(
        skill_hub.config,
        "get",
        lambda key, default=None: [str(bad), str(good)]
        if key == "skills.hub_sources" else default,
    )

    def resolve(raw):
        if str(raw) == str(bad):
            raise OSError("invalid configured source")
        return good

    monkeypatch.setattr(skill_hub.config, "resolve_path", resolve)

    assert skill_hub.hub_sources() == [good]
    assert events == [("agent.skill_hub.source_resolve_failed", "OSError")]


def test_list_available_skips_broken_frontmatter_and_keeps_valid_skill(
        monkeypatch, tmp_path):
    from jarvis.agent import skill_hub

    events = _spy(monkeypatch, skill_hub)
    valid = tmp_path / "valid" / "SKILL.md"
    broken = tmp_path / "broken" / "SKILL.md"
    valid.parent.mkdir()
    broken.parent.mkdir()
    valid.write_text("valid", encoding="utf-8")
    broken.write_text("broken", encoding="utf-8")

    monkeypatch.setattr(skill_hub, "hub_sources", lambda: [tmp_path])
    monkeypatch.setattr(skill_hub.skills, "list_metadata", lambda: [])

    def parse(text):
        if text == "broken":
            raise ValueError("frontmatter is invalid")
        return {"name": "valid", "description": "local"}, ""

    monkeypatch.setattr(skill_hub.skills, "_parse_frontmatter", parse)

    result = skill_hub.list_available()

    assert [item["name"] for item in result] == ["valid"]
    assert events == [("agent.skill_hub.frontmatter_parse_failed", "ValueError")]
