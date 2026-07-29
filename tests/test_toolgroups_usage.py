"""Fase 2c — toolgroups (pemetaan + enabled vs available), tool_usage
(agregasi incremental), toggle grup persist, exclude schema LLM."""
from __future__ import annotations

import json

import pytest

from jarvis.agent import capability_service as svc
from jarvis.agent import registry, tool_usage, toolgroups
from jarvis.agent.base import Tool, ToolResult
from jarvis.core import config


class EchoTool(Tool):
    name = "echo"
    description = "echo"
    read_only = True
    timeout_s = 5

    async def run(self, **_) -> ToolResult:
        return ToolResult.success("ok")


# ── pemetaan grup ─────────────────────────────────────────────────────────────

def test_semua_tool_nyata_terpetakan_tanpa_fallback():
    groups = toolgroups.all_groups()
    ids = [g["id"] for g in groups]
    assert len(ids) == len(set(ids))
    union = {t for g in groups for t in g["tools"]}
    assert union == set(registry.all_tools())
    # pemetaan lengkap: tidak ada modul nyata yang jatuh ke fallback "other"
    assert "other" not in ids


def test_modul_tak_terpetakan_masuk_fallback(monkeypatch):
    monkeypatch.setattr(registry, "_tools", {"echo": EchoTool()})
    groups = {g["id"]: g for g in toolgroups.all_groups()}
    assert "other" in groups
    assert groups["other"]["tools"] == ["echo"]
    # grup terpetakan yang modulnya tidak menghasilkan tool → unavailable
    assert groups["file_operations"]["available"] is False
    assert groups["file_operations"]["availability_reason"]


def test_integrasi_tidak_siap_menjelaskan_yang_harus_dihubungkan(monkeypatch):
    monkeypatch.setattr(registry, "_tools", {"echo": EchoTool()})
    groups = {g["id"]: g for g in toolgroups.all_groups()}
    assert "Google OAuth" in groups["google_cloud"]["availability_reason"]
    assert "Spotify" in groups["spotify"]["availability_reason"]


def test_disabled_tool_names_dari_config(monkeypatch):
    monkeypatch.setattr(registry, "_tools", {"echo": EchoTool()})
    orig = config.get

    def fake(key, default=None):
        if key == "tools.disabled_groups":
            return ["other"]
        return orig(key, default)

    monkeypatch.setattr(config, "get", fake)
    assert toolgroups.disabled_tool_names() == {"echo"}
    # rantai penegakan §5.8: schema LLM tidak memuat tool grup mati
    schemas = registry.schemas(exclude=sorted(toolgroups.disabled_tool_names()))
    assert all(s["function"]["name"] != "echo" for s in schemas)


# ── agregasi JSONL ────────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_jsonl(tmp_path, monkeypatch):
    monkeypatch.setattr(tool_usage, "logs_dir", lambda: tmp_path)
    return tmp_path / "tools.jsonl"


def _rec(tool: str, ok: bool) -> str:
    return json.dumps({"ts": 1.0, "tool": tool, "ok": ok}) + "\n"


def test_aggregate_hanya_yang_sukses(tmp_jsonl):
    tmp_jsonl.write_text(_rec("read_file", True) + _rec("read_file", False)
                         + _rec("patch", True) + "bukan json\n",
                         encoding="utf-8")
    assert tool_usage.aggregate() == {"read_file": 1, "patch": 1}


def test_aggregate_incremental_dan_truncate(tmp_jsonl):
    tmp_jsonl.write_text(_rec("a", True), encoding="utf-8")
    assert tool_usage.aggregate() == {"a": 1}
    with tmp_jsonl.open("a", encoding="utf-8") as f:
        f.write(_rec("a", True))
    assert tool_usage.aggregate() == {"a": 2}
    # baris setengah jadi (tanpa newline) belum dihitung
    with tmp_jsonl.open("a", encoding="utf-8") as f:
        f.write('{"ts": 2.0, "tool": "a"')
    assert tool_usage.aggregate() == {"a": 2}
    with tmp_jsonl.open("a", encoding="utf-8") as f:
        f.write(', "ok": true}\n')
    assert tool_usage.aggregate() == {"a": 3}
    # file menyusut → reset, baca ulang
    tmp_jsonl.write_text(_rec("b", True), encoding="utf-8")
    assert tool_usage.aggregate() == {"b": 1}


def test_rotasi_ukuran_membuat_rollup_tanpa_hilang_counter(
        tmp_jsonl, monkeypatch):
    original_get = config.get

    def fake_get(key, default=None):
        if key == "telemetry.tools.max_bytes":
            return 1
        if key == "telemetry.tools.rotate_daily":
            return False
        return original_get(key, default)

    monkeypatch.setattr(config, "get", fake_get)
    tool_usage.append_record({"ts": 1, "tool": "read_file", "ok": True})
    tool_usage.append_record({"ts": 2, "tool": "read_file", "ok": True})
    assert tool_usage.aggregate() == {"read_file": 2}
    rollup = json.loads((tmp_jsonl.parent / "tools_rollup.json")
                        .read_text(encoding="utf-8"))
    assert rollup["counts"] == {"read_file": 1}
    assert list(tmp_jsonl.parent.glob("tools-*.jsonl"))


# ── service + persist ─────────────────────────────────────────────────────────

@pytest.fixture()
def tmp_cfg(tmp_path, monkeypatch):
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        "skills:\n  disabled: []\n"
        "tools:                # blok grup\n"
        "  disabled_groups: [] # komentar\n",
        encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_PATH", cfg)
    config.reload()
    yield cfg
    monkeypatch.undo()
    config.reload()


def test_list_tool_groups_gabungkan_counter(tmp_jsonl, tmp_cfg, monkeypatch):
    monkeypatch.setattr(registry, "_tools", {"echo": EchoTool()})
    tmp_jsonl.write_text(_rec("echo", True) * 3, encoding="utf-8")
    groups = {g["id"]: g for g in svc.list_tool_groups()}
    assert groups["other"]["calls"] == 3
    assert groups["other"]["tool_calls"] == {"echo": 3}
    # sort: ber-calls di atas
    assert svc.list_tool_groups()[0]["id"] == "other"


def test_set_group_enabled_persist_surgical(tmp_cfg, monkeypatch):
    monkeypatch.setattr(registry, "_tools", {"echo": EchoTool()})
    assert svc.set_group_enabled("other", False) is True
    text = tmp_cfg.read_text(encoding="utf-8")
    assert "  disabled_groups: [other]" in text
    assert "tools:                # blok grup" in text
    assert "skills:\n  disabled: []" in text
    assert toolgroups.disabled_group_ids() == {"other"}
    assert svc.set_group_enabled("other", True) is True
    assert "  disabled_groups: []" in tmp_cfg.read_text(encoding="utf-8")


def test_set_group_enabled_tolak_grup_asing(tmp_cfg):
    assert svc.set_group_enabled("tidak-ada", False) is False
