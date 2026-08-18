"""CapabilityService (PARITY v2 §3) — service layer panel Capabilities.

UI bicara ke modul ini, tidak pernah langsung ke skills/sidecar/registry.
Fase 2b: daftar skill (metadata + usage + provenance + enabled), toggle
enable/disable dengan persistensi ke config.yaml.

Penulisan config.yaml SURGICAL: hanya baris ``disabled:`` di dalam blok
``skills:`` yang diganti — komentar dan sisa file utuh. yaml.dump ulang
seluruh file akan menghancurkan komentar user; jangan pernah.
"""
from __future__ import annotations

import re
import threading

from jarvis.core import config, log, quiet
from jarvis.agent import skill_usage, skills, tool_usage, toolgroups

_logger = log.get("agent.capability")
_lock = threading.Lock()


def list_skills(filter_text: str = "") -> list[dict]:
    """Semua skill untuk UI manajemen (termasuk yang disabled).

    Urutan Hermes (img 1-2): yang punya counter dulu (desc), sisanya
    alfabetis. Field: name, description, category, triggers, usage,
    provenance, enabled.
    """
    disabled = skills.disabled_names()
    usage = skill_usage.all_usage()
    out = []
    for meta in skills.list_metadata(filter_text):
        entry = usage.get(meta["name"]) or {}
        total = sum(int(entry.get(k, 0) or 0) for k in skill_usage.KINDS)
        out.append({
            **meta,
            "usage": total,
            "provenance": ("agent" if entry.get("is_agent_created")
                           else "bundled"),
            "enabled": meta["name"] not in disabled,
            "pinned": bool(entry.get("pinned")),
            "lifecycle": entry.get("lifecycle", "active"),
        })
    return sort_skills(out)


def sort_skills(items: list[dict], descending: bool = True) -> list[dict]:
    """Counter > 0 di atas (sort pemakaian), sisanya alfabetis di bawah."""
    sign = -1 if descending else 1
    used = sorted((s for s in items if s["usage"] > 0),
                  key=lambda s: (sign * s["usage"], s["name"]))
    rest = sorted((s for s in items if s["usage"] <= 0),
                  key=lambda s: s["name"])
    return used + rest


def skill_detail(name: str) -> dict | None:
    """Detail satu skill untuk pane kanan (body penuh, breakdown counter)."""
    for meta in skills.list_metadata():
        if meta["name"] == name:
            entry = (skill_usage.all_usage().get(name) or {})
            return {
                **meta,
                "body": skills.view(name) or "",
                "use": int(entry.get("use", 0) or 0),
                "view": int(entry.get("view", 0) or 0),
                "patch": int(entry.get("patch", 0) or 0),
                "provenance": ("agent" if entry.get("is_agent_created")
                               else "bundled"),
                "enabled": name not in skills.disabled_names(),
                "pinned": bool(entry.get("pinned")),
                "lifecycle": entry.get("lifecycle", "active"),
            }
    return None


def set_skill_enabled(name: str, enabled: bool) -> bool:
    """Toggle skill: mutasi ``skills.disabled`` di config.yaml + reload.

    Berlaku untuk sesi/tugas agent BERIKUTNYA (prompt disusun per run).
    Return False bila penulisan gagal; state lama tetap berlaku.
    """
    with _lock:
        disabled = set(skills.disabled_names())
        before = set(disabled)
        if enabled:
            disabled.discard(name)
        else:
            disabled.add(name)
        if disabled == before:
            return True
        try:
            _write_disabled(sorted(disabled))
            config.reload()
            _logger.info("capability.skill_toggled", name=name,
                         enabled=enabled)
            return True
        except Exception as e:                               # noqa: BLE001
            _logger.error("capability.toggle_failed", name=name,
                          error=str(e)[:120])
            return False


def _format_list_line(key: str, names: list[str]) -> str:
    return f"  {key}: [{', '.join(names)}]"


def _write_disabled(names: list[str]) -> None:
    _write_list_key("skills", "disabled", names)


def _write_list_key(block: str, key: str, names: list[str]) -> None:
    """Ganti HANYA baris ``<key>:`` di blok top-level ``<block>:``.

    Blok tidak ada → tambahkan di akhir file. Baris lain (komentar,
    seksi lain) tidak tersentuh — yaml.dump ulang seluruh file dilarang.
    """
    path = config.CONFIG_PATH
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    in_block = False
    for i, line in enumerate(lines):
        if re.match(rf"^{block}:", line):
            in_block = True
            continue
        if in_block:
            if re.match(r"^\S", line):                 # key top-level berikut
                break
            if re.match(rf"^\s+{key}:", line):
                eol = "\n" if line.endswith("\n") else ""
                lines[i] = _format_list_line(key, names) + eol
                path.write_text("".join(lines), encoding="utf-8")
                return
    # blok/key tidak ditemukan — tambah di akhir
    suffix = "" if text.endswith("\n") else "\n"
    path.write_text(text + suffix + f"\n{block}:\n"
                    + _format_list_line(key, names) + "\n", encoding="utf-8")


def skill_count() -> int:
    return len(skills.list_metadata())


# ── Curator (Fase 5 §8) ──────────────────────────────────────────────────────

def set_skill_pinned(name: str, pinned: bool) -> bool:
    """Pin = curator tidak menyentuh skill ini. Selalu boleh."""
    try:
        skill_usage.set_pinned(name, pinned)
        return True
    except Exception as exc:                                 # noqa: BLE001
        quiet.swallowed("agent.capability_service.skill_pin_failed", exc)
        return False


def archive_skill(name: str) -> tuple[bool, str]:
    from jarvis.agent import curator
    return curator.archive_skill(name)


def unarchive_skill(name: str) -> tuple[bool, str]:
    from jarvis.agent import curator
    return curator.unarchive_skill(name)


def list_archived_skills() -> list[str]:
    from jarvis.agent import curator
    return curator.list_archived()


# ── Tools (Fase 2c) ──────────────────────────────────────────────────────────

def list_tool_groups(filter_text: str = "") -> list[dict]:
    """Grup tool untuk tab Tools: + counter agregat & per-tool dari JSONL.

    Urutan pola Hermes: total calls desc, sisanya alfabetis nama grup.
    """
    calls = tool_usage.aggregate()
    out = []
    needle = filter_text.strip().lower()
    for g in toolgroups.all_groups():
        tool_calls = {t: calls.get(t, 0) for t in g["tools"]}
        entry = {**g, "calls": sum(tool_calls.values()),
                 "tool_calls": tool_calls}
        if needle and needle not in " ".join(
                [g["name"], g["subtitle"], *g["tools"]]).lower():
            continue
        out.append(entry)
    return sort_tool_groups(out)


def sort_tool_groups(items: list[dict], descending: bool = True) -> list[dict]:
    sign = -1 if descending else 1
    used = sorted((g for g in items if g["calls"] > 0),
                  key=lambda g: (sign * g["calls"], g["name"]))
    rest = sorted((g for g in items if g["calls"] <= 0),
                  key=lambda g: g["name"])
    return used + rest


def set_group_enabled(group_id: str, enabled: bool) -> bool:
    """Toggle grup tool → config.yaml ``tools.disabled_groups`` + reload.

    Grup unavailable tidak bisa di-enable dari sini (§5.5 — itu urusan
    kredensial/dependency, bukan toggle). Berlaku untuk run berikutnya.
    """
    with _lock:
        known = {g["id"] for g in toolgroups.all_groups()}
        if group_id not in known:
            _logger.warning("capability.unknown_group", group=group_id)
            return False
        disabled = set(toolgroups.disabled_group_ids())
        before = set(disabled)
        if enabled:
            disabled.discard(group_id)
        else:
            disabled.add(group_id)
        if disabled == before:
            return True
        try:
            _write_list_key("tools", "disabled_groups", sorted(disabled))
            config.reload()
            _logger.info("capability.group_toggled", group=group_id,
                         enabled=enabled)
            return True
        except Exception as e:                               # noqa: BLE001
            _logger.error("capability.group_toggle_failed", group=group_id,
                          error=str(e)[:120])
            return False


def tool_group_count() -> int:
    return len(toolgroups.all_groups())


# ── Browse Hub (§5.7) ────────────────────────────────────────────────────────

def list_hub_skills(filter_text: str = "") -> list[dict]:
    from jarvis.agent import skill_hub
    return skill_hub.list_available(filter_text)


def install_hub_skill(name: str) -> tuple[bool, str]:
    from jarvis.agent import skill_hub
    return skill_hub.install(name)


# ── MCP (§5.7) ───────────────────────────────────────────────────────────────

def list_mcp_servers(probe: bool = False) -> list[dict]:
    from jarvis.agent import mcp_client
    return mcp_client.statuses(probe=probe)


def set_mcp_enabled(name: str, enabled: bool) -> bool:
    """Toggle server MCP → config.yaml ``mcp.disabled`` (surgical)."""
    from jarvis.agent import mcp_client
    with _lock:
        known = {s["name"] for s in mcp_client.server_specs()}
        if name not in known:
            _logger.warning("capability.unknown_mcp", server=name)
            return False
        disabled = set(mcp_client.disabled_names())
        before = set(disabled)
        if enabled:
            disabled.discard(name)
        else:
            disabled.add(name)
        if disabled == before:
            return True
        try:
            _write_list_key("mcp", "disabled", sorted(disabled))
            config.reload()
            return True
        except Exception as e:                               # noqa: BLE001
            _logger.error("capability.mcp_toggle_failed", server=name,
                          error=str(e)[:120])
            return False
