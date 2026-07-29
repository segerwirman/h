"""Browse Hub — katalog skill dari sumber lokal yang dikonfigurasi eksplisit.

MK50 tidak mempunyai sumber hub bawaan. Khususnya, repo referensi
``hermes-agent-main`` tidak pernah dibaca atau disalin oleh runtime. Skill
lokal yang sudah terinstal tetap dikelola loader Jarvis yang ada.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from jarvis.core import config, log
from jarvis.agent import skill_usage, skills

_logger = log.get("agent.skill_hub")

# Defense-in-depth untuk sumber pihak ketiga yang dikonfigurasi user.
_BLOCKLIST_SUBSTRINGS = ("hermes", "petdex", "yuanbao")

_DEFAULT_SOURCES: tuple[str, ...] = ()


def local_catalog():
    """Version archive stays local until a signed remote registry exists."""
    from jarvis.agent.skill_catalog import LocalSkillCatalog
    return LocalSkillCatalog(skills.skills_dir() / ".catalog")


def publish_local(name: str, content: str, version: str) -> tuple[bool, str]:
    try:
        item = local_catalog().publish(name, content, version=version)
    except (ValueError, FileExistsError) as exc:
        return False, str(exc)[:120]
    _logger.info("hub.local_published", name=item["name"], version=item["version"])
    return True, f"skill {item['name']} version {item['version']} published locally"


def rollback_local(name: str, version: str) -> tuple[bool, str]:
    try:
        return True, local_catalog().rollback(name, version)
    except OSError:
        return False, "version skill tidak ditemukan"


def hub_sources() -> list[Path]:
    raw = config.get("skills.hub_sources", list(_DEFAULT_SOURCES))
    if isinstance(raw, str):
        raw = [raw]
    out = []
    for entry in raw or []:
        try:
            p = config.resolve_path(str(entry))
            if p.is_dir():
                out.append(p)
        except Exception:                                    # noqa: BLE001
            continue
    return out


def _blocked(name: str) -> bool:
    low = name.lower()
    return any(s in low for s in _BLOCKLIST_SUBSTRINGS)


def list_available(filter_text: str = "") -> list[dict]:
    """Katalog hub: {name, description, category, source_path, installed}.
    Nama duplikat antar sumber: sumber pertama menang."""
    installed = {m["name"] for m in skills.list_metadata()}
    needle = filter_text.strip().lower()
    seen: set[str] = set()
    out: list[dict] = []
    for root in hub_sources():
        for skill_file in sorted(root.glob("**/SKILL.md")):
            folder = skill_file.parent
            try:
                meta, _ = skills._parse_frontmatter(
                    skill_file.read_text(encoding="utf-8",
                                         errors="replace"))
            except Exception:                                # noqa: BLE001
                continue
            name = str(meta.get("name") or folder.name)
            if name in seen or _blocked(name) or _blocked(folder.name):
                continue
            desc = str(meta.get("description", ""))
            category = folder.parent.name.replace("-", " ").title() \
                if folder.parent != root else "General"
            if _blocked(category):
                continue
            if needle and needle not in \
                    f"{name} {desc} {category}".lower():
                continue
            seen.add(name)
            out.append({"name": name, "description": desc,
                        "category": category,
                        "source_path": str(folder),
                        "installed": name in installed})
    return sorted(out, key=lambda s: (s["installed"], s["name"]))


def install(name: str) -> tuple[bool, str]:
    """Salin folder skill hub → skills_data. Sumber tidak disentuh."""
    entry = next((s for s in list_available() if s["name"] == name), None)
    if entry is None:
        return False, f"skill hub tidak ditemukan: {name}"
    if entry["installed"]:
        return False, "sudah terinstal"
    safe = skills._safe_name(name)
    dst = skills.skills_dir() / safe
    if dst.exists():
        return False, "folder tujuan sudah ada"
    try:
        shutil.copytree(entry["source_path"], dst)
    except Exception as e:                                   # noqa: BLE001
        return False, str(e)[:120]
    skill_usage.mark_hub_installed(safe)
    _logger.info("hub.installed", name=safe)
    return True, f"skill {safe} terinstal dari hub"
