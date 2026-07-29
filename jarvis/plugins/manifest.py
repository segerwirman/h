"""Strict, import-free validation for trusted local plugin manifests."""
from __future__ import annotations

from jarvis.agent import toolsets

_ALLOWED_CONTRIBUTIONS = frozenset({"tools", "skill_sources", "panels", "commands", "adapters"})
_ALLOWED_PERMISSIONS = frozenset({"tools", "skills", "panels", "commands", "adapters"})


def validate(data: dict) -> tuple[bool, str]:
    """Validate structure before any plugin code is imported."""
    if not isinstance(data, dict):
        return False, "manifest bukan object"
    for key in ("id", "name", "version", "entrypoint"):
        if not str(data.get(key, "")).strip():
            return False, f"field wajib kosong: {key}"
    contributions = data.get("contributions", {})
    if not isinstance(contributions, dict) or any(key not in _ALLOWED_CONTRIBUTIONS
                                                   for key in contributions):
        return False, "contribution tidak valid"
    required = {str(item) for item in data.get("required_toolsets", [])}
    if not required or not required <= set(toolsets._TOOLSETS):
        return False, "required_toolsets tidak valid"
    permissions = {str(item) for item in data.get("permissions", [])}
    if not permissions <= _ALLOWED_PERMISSIONS:
        return False, "permission tidak valid"
    allowed_tools = set().union(*(toolsets._TOOLSETS[name] for name in required))
    if any(str(name) not in allowed_tools for name in contributions.get("tools", [])):
        return False, "tool di luar required_toolsets"
    return True, ""
