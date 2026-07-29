"""Fase 1 (PARITY v2 §4.5) — usage counter, provenance, toggle, kategori.

Tanpa UI, tanpa network, tanpa Qt.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from jarvis.agent import skill_usage, skills
from jarvis.agent.tools.skill_tools import SkillManage, SkillView
from jarvis.core import config


@pytest.fixture()
def tmp_skills(tmp_path, monkeypatch):
    """Arahkan skills_dir (dan sidecar) ke folder sementara."""
    d = tmp_path / "skills_data"
    d.mkdir()
    monkeypatch.setattr(skills, "skills_dir", lambda: d)
    return d


def _write_skill(root, name, category=None, description="deskripsi"):
    folder = root / name
    folder.mkdir()
    cat = f"category: {category}\n" if category else ""
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n{cat}---\n\nisi\n",
        encoding="utf-8")


@pytest.fixture()
def no_disabled(monkeypatch):
    """Config bersih: skills.disabled kosong, apa pun isi config.yaml user."""
    orig = config.get

    def fake(key, default=None):
        if key == "skills.disabled":
            return []
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)


# ── Usage counter ─────────────────────────────────────────────────────────────

def test_bump_naikkan_usage(tmp_skills):
    assert skill_usage.usage_of("x") == 0
    skill_usage.bump("x", "use")
    skill_usage.bump("x", "view")
    skill_usage.bump("x", "patch")
    assert skill_usage.usage_of("x") == 3


def test_bump_kind_tidak_dikenal_diabaikan(tmp_skills):
    skill_usage.bump("x", "bogus")
    assert skill_usage.usage_of("x") == 0
    assert not skill_usage.sidecar_path().exists()


def test_sidecar_corrupt_tidak_crash(tmp_skills):
    skill_usage.sidecar_path().write_text("{jelas bukan json", encoding="utf-8")
    assert skill_usage.usage_of("x") == 0          # baca: mulai kosong
    skill_usage.bump("x", "use")                   # tulis: pulih dari korup
    assert skill_usage.usage_of("x") == 1
    data = json.loads(skill_usage.sidecar_path().read_text(encoding="utf-8"))
    assert data["x"]["use"] == 1


def test_bump_set_last_used(tmp_skills):
    skill_usage.bump("x", "use")
    data = json.loads(skill_usage.sidecar_path().read_text(encoding="utf-8"))
    assert data["x"]["last_used"] > 0
    assert data["x"]["lifecycle"] == "active"


# ── Provenance / badge "learned" ──────────────────────────────────────────────

def test_skill_manage_create_tandai_agent_created(tmp_skills):
    result = asyncio.run(SkillManage().run(
        action="create", name="skill-baru", content="instruksi"))
    assert result.ok
    assert skill_usage.is_agent_created("skill-baru") is True
    assert skill_usage.provenance("skill-baru") == "agent"


def test_skill_bundled_bukan_learned(tmp_skills):
    _write_skill(tmp_skills, "bawaan")
    assert skill_usage.is_agent_created("bawaan") is False
    assert skill_usage.provenance("bawaan") == "bundled"


def test_manage_update_bump_patch_delete_forget(tmp_skills):
    asyncio.run(SkillManage().run(action="create", name="s", content="a"))
    asyncio.run(SkillManage().run(action="update", name="s", content="b"))
    assert skill_usage.usage_of("s") == 1          # 1 patch; create tidak bump
    asyncio.run(SkillManage().run(action="delete", name="s"))
    assert skill_usage.usage_of("s") == 0
    data = json.loads(skill_usage.sidecar_path().read_text(encoding="utf-8"))
    assert "s" not in data


def test_skill_view_bump_view(tmp_skills):
    _write_skill(tmp_skills, "dibaca")
    result = asyncio.run(SkillView().run(name="dibaca"))
    assert result.ok
    assert skill_usage.usage_of("dibaca") == 1


def test_skill_view_gagal_tidak_bump(tmp_skills):
    result = asyncio.run(SkillView().run(name="tidak-ada"))
    assert not result.ok
    assert skill_usage.usage_of("tidak-ada") == 0


# ── Toggle enable/disable ─────────────────────────────────────────────────────

def test_disabled_hilang_dari_prompt(tmp_skills, monkeypatch):
    _write_skill(tmp_skills, "aktif")
    _write_skill(tmp_skills, "mati")
    orig = config.get

    def fake(key, default=None):
        if key == "skills.disabled":
            return ["mati"]
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    block = skills.prompt_block()
    assert "aktif" in block
    assert "mati" not in block
    names = [m["name"] for m in skills.list_for_prompt()]
    assert names == ["aktif"]


def test_enabled_masuk_prompt(tmp_skills, no_disabled):
    _write_skill(tmp_skills, "aktif")
    assert "aktif" in skills.prompt_block()


def test_disabled_scalar_dan_null(tmp_skills):
    # YAML null → kosong; scalar string → satu nama, bukan set karakter
    assert skills._normalize_names(None) == set()
    assert skills._normalize_names("satu-skill") == {"satu-skill"}
    assert skills._normalize_names(["a", " b ", ""]) == {"a", "b"}


def test_list_metadata_tetap_tampilkan_disabled(tmp_skills, monkeypatch):
    """list_metadata = tampilan manajemen (UI Fase 2) — tidak difilter."""
    _write_skill(tmp_skills, "mati")
    orig = config.get

    def fake(key, default=None):
        if key == "skills.disabled":
            return ["mati"]
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    assert [m["name"] for m in skills.list_metadata()] == ["mati"]


# ── Kategori ──────────────────────────────────────────────────────────────────

def test_kategori_dari_frontmatter(tmp_skills):
    _write_skill(tmp_skills, "berkategori", category="Productivity")
    (meta,) = skills.list_metadata()
    assert meta["category"] == "Productivity"


def test_kategori_default_general(tmp_skills):
    _write_skill(tmp_skills, "polos")
    (meta,) = skills.list_metadata()
    assert meta["category"] == "General"
