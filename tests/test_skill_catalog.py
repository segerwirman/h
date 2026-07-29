"""Framework maturity Phase 5 — local publish stores immutable versions."""
from __future__ import annotations


def test_publish_lokal_menyimpan_version_dan_rollback(tmp_path):
    from jarvis.agent.skill_catalog import LocalSkillCatalog

    catalog = LocalSkillCatalog(tmp_path / "catalog")
    catalog.publish("weather", "---\nname: weather\n---\nv1", version="1.0.0")
    catalog.publish("weather", "---\nname: weather\n---\nv2", version="1.1.0")

    assert [item["version"] for item in catalog.browse()] == ["1.1.0", "1.0.0"]
    assert catalog.rollback("weather", "1.0.0") == "---\nname: weather\n---\nv1"


def test_publish_menolak_overwrite_version(tmp_path):
    from jarvis.agent.skill_catalog import LocalSkillCatalog

    catalog = LocalSkillCatalog(tmp_path / "catalog")
    catalog.publish("weather", "v1", version="1.0.0")

    try:
        catalog.publish("weather", "changed", version="1.0.0")
    except FileExistsError:
        pass
    else:
        raise AssertionError("version existing must remain immutable")


def test_skill_hub_publish_dan_rollback_local(tmp_path, monkeypatch):
    from jarvis.agent import skill_hub, skills

    monkeypatch.setattr(skills, "skills_dir", lambda: tmp_path / "skills")
    ok, _ = skill_hub.publish_local("weather", "v1", "1.0.0")
    assert ok is True
    ok, content = skill_hub.rollback_local("weather", "1.0.0")
    assert ok is True
    assert content == "v1"
