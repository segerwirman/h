"""Allowlisted release flags with deterministic rollback defaults."""
from __future__ import annotations

from jarvis.core import config

_OPTIONAL_FLAGS = frozenset({"naturalizer", "plugins", "gateway", "discord", "whatsapp"})
_CORE_FLAGS = frozenset({"deterministic_delivery"})

_ROLLOUT_RINGS = {
    "local-developer": {"gateway": False, "discord": False, "whatsapp": False},
    "desktop-trusted": {"gateway": False, "discord": False, "whatsapp": False},
    "telegram-paired": {"gateway": True, "discord": False, "whatsapp": False},
    "discord-sandbox": {"gateway": True, "discord": True, "whatsapp": False},
    "whatsapp-sandbox": {"gateway": True, "discord": True, "whatsapp": True},
}
_RING_ORDER = tuple(_ROLLOUT_RINGS)


def preset(current: dict, name: str) -> dict:
    """Apply a named rollback preset without activating unknown features."""
    if str(name) not in {"minimal", "desktop-only", "gateway-off", "plugins-off", "safe-mode"}:
        return dict(current or {})
    result = dict(current or {})
    if name in {"minimal", "safe-mode"}:
        for flag in _OPTIONAL_FLAGS:
            result[flag] = False
    elif name in {"desktop-only", "gateway-off"}:
        result.update({"gateway": False, "discord": False, "whatsapp": False})
    elif name == "plugins-off":
        result["plugins"] = False
    result["deterministic_delivery"] = True
    return result


def rollout_for_ring(name: str) -> dict:
    return dict(_ROLLOUT_RINGS.get(str(name), {}))


def can_advance_ring(current_ring: str, target_ring: str) -> bool:
    """Allow only a single known forward rollout step; rollback stays separate."""
    try:
        return _RING_ORDER.index(str(target_ring)) == _RING_ORDER.index(str(current_ring)) + 1
    except ValueError:
        return False


def status_for_ring(name: str, *, current_flags: dict | None = None,
                    prerequisites: dict | None = None) -> dict:
    """Return a side-effect-free release decision with explicit missing gates."""
    ring = str(name)
    desired = rollout_for_ring(ring)
    if ring not in _ROLLOUT_RINGS:
        return {"ring": ring, "eligible": False, "desired": {},
                "missing_flags": [], "missing_prerequisites": ["known_ring"]}
    flags = dict(current_flags if current_flags is not None else current())
    requirements = dict(prerequisites or {})
    missing_flags = sorted(flag for flag, enabled in desired.items()
                           if enabled and not bool(flags.get(flag, False)))
    missing_prerequisites = sorted(name for name, ready in requirements.items() if not ready)
    return {
        "ring": ring,
        "eligible": not missing_flags and not missing_prerequisites,
        "desired": desired,
        "missing_flags": missing_flags,
        "missing_prerequisites": missing_prerequisites,
    }


def current() -> dict:
    """Read non-secret rollout flags with fail-safe defaults."""
    raw = config.section("release_controls")
    return {
        "naturalizer": bool(raw.get("naturalizer", False)),
        "plugins": bool(raw.get("plugins", False)),
        "gateway": bool(raw.get("gateway", False)),
        "discord": bool(raw.get("discord", False)),
        "whatsapp": bool(raw.get("whatsapp", False)),
        "deterministic_delivery": bool(raw.get("deterministic_delivery", True)),
    }


def apply(current: dict, updates: dict) -> dict:
    """Apply known release flags only; ignore unknown input."""
    result = dict(current or {})
    for name in _OPTIONAL_FLAGS | _CORE_FLAGS:
        if name in updates:
            result[name] = bool(updates[name])
    return result


def rollback(current: dict) -> dict:
    """Disable optional features while retaining deterministic delivery."""
    result = dict(current or {})
    for name in _OPTIONAL_FLAGS:
        if name in result:
            result[name] = False
    result["deterministic_delivery"] = True
    return result
