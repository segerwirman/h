"""Fase 2b — CapabilityService: list gabungan, sort Hermes, toggle persist
surgical ke config.yaml."""
from __future__ import annotations

import pytest

from jarvis.agent import capability_service as svc
from jarvis.agent import skill_usage, skills
from jarvis.core import config


@pytest.fixture()
def tmp_env(tmp_path, monkeypatch):
    """skills_dir + config.yaml sementara; cache config dipulihkan setelahnya."""
    d = tmp_path / "skills_data"
    d.mkdir()
    monkeypatch.setattr(skills, "skills_dir", lambda: d)

    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "# komentar atas\n"
        "window:\n"
        "  width: 1100    # jangan tersentuh\n"
        "\n"
        "skills:                          # blok toggle\n"
        "  disabled: []                   # komentar inline\n"
        "\n"
        "tools:\n"
        "  disabled_groups: []\n",
        encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    config.reload()
    yield d, cfg
    monkeypatch.undo()
    config.reload()


def _write_skill(root, name, category=None):
    folder = root / name
    folder.mkdir()
    cat = f"category: {category}\n" if category else ""
    (folder / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: d-{name}\n{cat}---\n\nbody-{name}\n",
        encoding="utf-8")


def test_list_skills_gabungkan_usage_provenance_enabled(tmp_env):
    d, _ = tmp_env
    _write_skill(d, "alpha", "Media")
    _write_skill(d, "beta")
    skill_usage.bump("alpha", "use")
    skill_usage.mark_agent_created("alpha")

    items = {s["name"]: s for s in svc.list_skills()}
    assert items["alpha"]["usage"] == 1
    assert items["alpha"]["provenance"] == "agent"
    assert items["alpha"]["category"] == "Media"
    assert items["alpha"]["enabled"] is True
    assert items["beta"]["usage"] == 0
    assert items["beta"]["provenance"] == "bundled"
    assert items["beta"]["category"] == "General"


def test_sort_counter_dulu_lalu_alfabetis(tmp_env):
    items = [
        {"name": "zeta", "usage": 0},
        {"name": "mid", "usage": 3},
        {"name": "top", "usage": 9},
        {"name": "abc", "usage": 0},
    ]
    order = [s["name"] for s in svc.sort_skills(items)]
    assert order == ["top", "mid", "abc", "zeta"]
    order_asc = [s["name"] for s in svc.sort_skills(items, descending=False)]
    assert order_asc == ["mid", "top", "abc", "zeta"]


def test_toggle_persist_dan_hilang_dari_prompt(tmp_env):
    d, cfg = tmp_env
    _write_skill(d, "target")
    assert "target" in skills.prompt_block()

    assert svc.set_skill_enabled("target", False) is True
    text = cfg.read_text(encoding="utf-8")
    assert "  disabled: [target]" in text
    # surgical: komentar & seksi lain utuh
    assert "# komentar atas" in text
    assert "width: 1100    # jangan tersentuh" in text
    assert "disabled_groups: []" in text
    # config sudah reload — prompt sesi baru tidak memuat skill itu
    assert "target" not in skills.prompt_block()

    assert svc.set_skill_enabled("target", True) is True
    assert "  disabled: []" in cfg.read_text(encoding="utf-8")
    assert "target" in skills.prompt_block()


def test_toggle_blok_hilang_ditambah_di_akhir(tmp_env, tmp_path, monkeypatch):
    d, _ = tmp_env
    cfg2 = tmp_path / "polos.yaml"
    cfg2.write_text("window:\n  width: 900\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg2)
    config.reload()
    _write_skill(d, "x")
    assert svc.set_skill_enabled("x", False) is True
    text = cfg2.read_text(encoding="utf-8")
    assert text.startswith("window:")
    assert "skills:\n  disabled: [x]" in text


def test_skill_detail(tmp_env):
    d, _ = tmp_env
    _write_skill(d, "alpha", "Media")
    skill_usage.bump("alpha", "view")
    detail = svc.skill_detail("alpha")
    assert detail["view"] == 1
    assert "body-alpha" in detail["body"]
    assert svc.skill_detail("ghost") is None
