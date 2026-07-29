"""Fase 5 (§8) — Curator: transisi lifecycle, archive/unarchive,
invarian (bundled & pinned tidak disentuh, tidak pernah delete)."""
from __future__ import annotations

import time

import pytest

from jarvis.agent import curator, skill_usage, skills
from jarvis.core import config

_DAY = 86400


@pytest.fixture()
def env(tmp_path, monkeypatch):
    d = tmp_path / "skills_data"
    d.mkdir()
    monkeypatch.setattr(skills, "skills_dir", lambda: d)
    orig = config.get

    def fake(key, default=None):
        if key == "curator.stale_after_days":
            return 14
        if key == "curator.archive_after_days":
            return 45
        if key == "curator.interval_hours":
            return 24
        if key == "curator.enabled":
            return True
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    return d


def _mk(root, name, agent=True, idle_days=0, pinned=False):
    folder = root / name
    folder.mkdir()
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d\n---\nisi", encoding="utf-8")
    if agent:
        skill_usage.mark_agent_created(name)
    if pinned:
        skill_usage.set_pinned(name, True)
    skill_usage._mutate(name, lambda e: e.__setitem__(
        "last_used", int(time.time() - idle_days * _DAY)))


def test_transisi_hanya_menandai_stale_tanpa_auto_archive(env):
    _mk(env, "segar", idle_days=1)
    _mk(env, "basi", idle_days=20)
    _mk(env, "tua", idle_days=60)
    result = curator.run_transitions()
    assert result == {"stale": ["basi", "tua"], "archived": []}
    assert skill_usage.entry_of("basi")["lifecycle"] == "stale"
    assert skill_usage.entry_of("tua")["lifecycle"] == "stale"
    names = [m["name"] for m in skills.list_metadata()]
    assert {"segar", "basi", "tua"}.issubset(names)
    assert curator.list_archived() == []


def test_archive_manual_memindahkan_skill_stale_tanpa_delete(env):
    _mk(env, "tua", idle_days=60)
    curator.run_transitions()
    ok, _ = curator.archive_skill("tua")
    assert ok is True
    assert curator.list_archived() == ["tua"]
    assert (curator.archive_dir() / "tua" / "SKILL.md").exists()


def test_bundled_dan_pinned_tidak_disentuh(env):
    _mk(env, "bawaan", agent=False, idle_days=999)
    _mk(env, "kesayangan", agent=True, idle_days=999, pinned=True)
    result = curator.run_transitions()
    assert result == {"stale": [], "archived": []}
    assert [m["name"] for m in skills.list_metadata()] == \
        ["bawaan", "kesayangan"]


def test_unarchive_pulih_dan_tidak_langsung_stale_ulang(env):
    _mk(env, "tua", idle_days=60)
    curator.run_transitions()
    ok, _ = curator.archive_skill("tua")
    assert ok is True
    assert curator.list_archived() == ["tua"]
    ok, _ = curator.unarchive_skill("tua")
    assert ok is True
    assert "tua" in [m["name"] for m in skills.list_metadata()]
    assert skill_usage.entry_of("tua")["lifecycle"] == "active"
    assert curator.run_transitions()["stale"] == []


def test_archive_manual_hanya_buatan_agent(env):
    _mk(env, "bawaan", agent=False)
    ok, msg = curator.archive_skill("bawaan")
    assert ok is False and "agent" in msg
    ok, _ = curator.archive_skill("tidak-ada")
    assert ok is False


def test_maybe_run_gated_interval_hanya_review_stale(env):
    _mk(env, "tua", idle_days=60)
    first = curator.maybe_run()
    assert first == {"stale": ["tua"], "archived": []}
    _mk(env, "tua2", idle_days=60)
    assert curator.maybe_run() is None          # belum lewat interval
    # lewat interval → review lagi, tanpa arsip otomatis
    later = time.time() + 25 * 3600
    result = curator.maybe_run(now=later)
    assert result == {"stale": ["tua2"], "archived": []}


def test_maybe_run_disabled(env, monkeypatch):
    orig = config.get

    def fake(key, default=None):
        if key == "curator.enabled":
            return False
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    assert curator.maybe_run() is None
