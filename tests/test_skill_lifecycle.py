"""Fase 9 — curator preserves skill ownership during lifecycle review."""
from __future__ import annotations

import importlib


def test_curator_dry_run_menandai_skill_lama_tanpa_mengarsipkan(monkeypatch):
    try:
        curator = importlib.import_module("jarvis.agent.curator")
    except ModuleNotFoundError:
        curator = None

    assert curator is not None
    states = []
    monkeypatch.setattr(curator.skill_usage, "all_usage", lambda: {
        "lama": {"last_used": 1, "pinned": False, "is_agent_created": True,
                 "lifecycle": "active"},
    })
    monkeypatch.setattr(curator.skill_usage, "set_lifecycle",
                        lambda name, state: states.append((name, state)))
    monkeypatch.setattr(curator.time, "time", lambda: 1000)

    report = curator.review(stale_after_s=100, dry_run=True)

    assert report == {"stale": ["lama"], "archived": []}
    assert states == []

    assert curator.review(stale_after_s=100, dry_run=False) == report
    assert states == [("lama", "stale")]


def test_curator_skill_pinned_tidak_bertransisi(monkeypatch):
    curator = importlib.import_module("jarvis.agent.curator")
    monkeypatch.setattr(curator.skill_usage, "all_usage", lambda: {
        "penting": {"last_used": 1, "pinned": True, "lifecycle": "active"},
    })
    monkeypatch.setattr(curator.time, "time", lambda: 1000)

    assert curator.review(stale_after_s=100) == {"stale": [], "archived": []}
