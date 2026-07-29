"""Skill loader (§3.1.M) — markdown dengan frontmatter, body lazy-load.

Skill = ``jarvis/agent/skills_data/<nama>/SKILL.md``:

    ---
    name: nama-skill
    description: Kapan skill ini dipakai
    triggers: [kata, kunci]
    ---
    (isi/instruksi)

Hanya name+description masuk system prompt; body dibaca via ``skill_view``.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

from jarvis.core import config, log

_logger = log.get("agent.skills")

_FM_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*\n?", re.DOTALL)


def skills_dir() -> Path:
    p = config.resolve_path(str(config.get("agent.skills_dir",
                                           "jarvis/agent/skills_data")))
    p.mkdir(parents=True, exist_ok=True)
    return p


def _parse_frontmatter(text: str) -> tuple[dict, str]:
    m = _FM_RE.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    for line in m.group(1).splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        v = v.strip()
        if v.startswith("[") and v.endswith("]"):
            meta[k.strip()] = [x.strip().strip("'\"")
                               for x in v[1:-1].split(",") if x.strip()]
        else:
            meta[k.strip()] = v.strip("'\"")
    return meta, text[m.end():]


def list_metadata(filter_text: str = "") -> list[dict]:
    out = []
    for skill_file in sorted(skills_dir().glob("*/SKILL.md")):
        try:
            meta, _ = _parse_frontmatter(
                skill_file.read_text(encoding="utf-8"))
        except Exception:                                    # noqa: BLE001
            continue
        name = meta.get("name") or skill_file.parent.name
        desc = meta.get("description", "")
        if filter_text and filter_text.lower() not in \
                f"{name} {desc}".lower():
            continue
        category = str(meta.get("category") or "").strip() or "General"
        out.append({"name": name, "description": desc,
                    "triggers": meta.get("triggers", []),
                    "category": category})
    return out


def _normalize_names(values) -> set[str]:
    """Normalisasi nilai config jadi set nama skill.

    ``None`` (YAML null) → kosong; scalar (``disabled: x``) → satu item,
    BUKAN set karakternya (pola Hermes skills_config #13026)."""
    if values is None:
        return set()
    if isinstance(values, str):
        values = [values]
    try:
        return {str(v).strip() for v in values if str(v).strip()}
    except TypeError:
        return set()


def disabled_names() -> set[str]:
    """Skill yang dimatikan user — config.yaml ``skills.disabled`` (§4.3)."""
    return _normalize_names(config.get("skills.disabled", []))


def list_for_prompt() -> list[dict]:
    """Metadata skill untuk system prompt: skill disabled TIDAK masuk sama
    sekali — bukan masuk lalu ditolak (PARITY v2 §4.3)."""
    disabled = disabled_names()
    return [m for m in list_metadata() if m["name"] not in disabled]


def view(name: str) -> str | None:
    path = skills_dir() / _safe_name(name) / "SKILL.md"
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None


def manage(action: str, name: str, content: str = "") -> tuple[bool, str]:
    name_safe = _safe_name(name)
    if not name_safe:
        return False, "nama skill tidak valid"
    folder = skills_dir() / name_safe
    path = folder / "SKILL.md"
    if action == "delete":
        if not folder.exists():
            return False, "skill tidak ditemukan"
        shutil.rmtree(folder)
        return True, f"skill {name_safe} dihapus"
    if action in ("create", "update"):
        if not content.strip():
            return False, "content kosong"
        if not _FM_RE.match(content):
            content = (f"---\nname: {name_safe}\n"
                       f"description: {name_safe}\n---\n\n" + content)
        folder.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        _logger.info("skill.saved", name=name_safe, action=action)
        return True, f"skill {name_safe} tersimpan"
    return False, f"action tidak dikenal: {action}"


def _safe_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", (name or "").strip())[:64].strip("-")


def prompt_block() -> str:
    metas = list_for_prompt()
    if not metas:
        return "(belum ada skill)"
    return "\n".join(f"- {m['name']}: {m['description']}" for m in metas)
