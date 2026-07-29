"""Registry aksi instan — lookup data, bukan classifier."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from jarvis.core import app_registry, config


@dataclass(frozen=True)
class Action:
    kind: str                 # app | panel | system
    target: str
    verb: str                 # open | close | toggle | set
    args: dict = field(default_factory=dict)
    confidence: float = 0.90
    source: str = "L1"


_SYSTEM: dict[str, tuple[str, tuple[str, ...]]] = {
    "volume_up": ("set", ("naikkan volume", "turn up volume", "volume up")),
    "volume_down": ("set", ("turunkan volume", "turn down volume", "volume down")),
    "volume_mute": ("set", ("mute", "senyapkan suara", "matikan suara")),
    "brightness": ("set", ("kecerahan", "brightness")),
    "lock": ("set", ("kunci layar", "lock screen")),
    "screenshot": ("set", ("screenshot", "tangkap layar")),
    "wifi_on": ("set", ("nyalakan wifi", "enable wifi")),
    "wifi_off": ("set", ("matikan wifi", "disable wifi")),
}

# Alias adalah nama UI/sistem semata; daftar panel sendiri selalu dari config.
_PANEL_ALIASES = {"vision": ("kamera", "camera")}


class ActionRegistry:
    def __init__(self) -> None:
        self._actions: dict[str, list[Action]] = {}
        self._entities: set[str] = set()

    def refresh(self) -> "ActionRegistry":
        self._actions.clear()
        self._entities.clear()
        for match in app_registry.index().values():
            self._add(match.key, Action("app", match.key, "open",
                                        {"app": match.name}))
            self._add(match.key, Action("app", match.key, "close",
                                        {"app": match.name}))
            # Display name makes multiword apps available to command palette.
            self._entities.add(match.name)
        for panel in config.get("action_panel.icons", []) or []:
            name = str(panel).strip().lower()
            if not name:
                continue
            self._add(name, Action("panel", name, "toggle", {"panel": name}))
            for alias in _PANEL_ALIASES.get(name, ()):
                self._add(alias, Action("panel", name, "open", {"panel": name}))
        for target, (verb, aliases) in _SYSTEM.items():
            action = Action("system", target, verb, {"action": target})
            self._entities.add(target)
            for alias in aliases:
                self._add(alias, action)
        return self

    def _add(self, entity: str, action: Action) -> None:
        key = app_registry.normalize(entity)
        if not key:
            return
        bucket = self._actions.setdefault(key, [])
        if action not in bucket:
            bucket.append(action)
        self._entities.add(key)

    def lookup(self, entity: str) -> list[Action]:
        """Fuzzy lookup dapat mengembalikan lebih dari satu aksi/target."""
        key = app_registry.normalize(entity)
        if not key:
            return []
        direct = list(self._actions.get(key, ()))
        if direct:
            return direct
        app = app_registry.resolve(key)
        if app is not None:
            return list(self._actions.get(app.key, ()))
        return []

    def all_entities(self) -> list[str]:
        return sorted(self._entities)


_default: ActionRegistry | None = None


def default_registry() -> ActionRegistry:
    global _default
    if _default is None:
        _default = ActionRegistry().refresh()
    return _default


__all__ = ["Action", "ActionRegistry", "default_registry"]
